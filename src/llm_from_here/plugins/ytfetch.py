import copy
import glob
import json
import os
import shutil
import tempfile
import uuid
import googleapiclient.discovery
import googleapiclient.errors
# import youtube_dl
import yt_dlp as youtube_dl
from yt_dlp.utils import DownloadError, ExtractorError, YoutubeDLError
import time
from isodate import parse_duration
import random
import html
import fnmatch
from retry import retry
from llm_from_here.supaSet import SupaSet
from jinja2 import Template
from llm_from_here.common import is_production_prefix
import ytmusicapi
from llm_from_here.common import get_nested_value
from llm_from_here.schemas.llm_outputs import LlmFilterResponse

import logging
logger = logging.getLogger(__name__)

# Progressive audio first (HTTPS / plain HTTP URL); exclude definite DRM and yt-dlp's
# "maybe" DRM bucket. Aligns selection with ``FFmpegExtractAudio`` → WAV post-process.
# Installing Deno helps YouTube n-parameter / JS challenges without cookies (see yt-dlp EJS wiki).
YOUTUBE_AUDIO_FORMAT_SPEC = (
    "bestaudio[has_drm!=true][has_drm!=maybe][protocol=https]/"
    "bestaudio[has_drm!=true][has_drm!=maybe][protocol^=http]/"
    "bestaudio[has_drm!=true][has_drm!=maybe]/"
    "bestaudio[has_drm!=true]/"
    "bestaudio"
)


def _resolved_deno_executable() -> str | None:
    """
    Path to the Deno binary for yt-dlp JS/EJS challenges.

    Order: YT_DLP_DENO, ``deno`` on PATH, then the default install.sh location ``~/.deno/bin/deno``.
    """
    env_p = os.getenv("YT_DLP_DENO", "").strip()
    if env_p and os.path.isfile(env_p) and os.access(env_p, os.X_OK):
        return env_p
    which = shutil.which("deno")
    if which and os.access(which, os.X_OK):
        return which
    default = os.path.join(os.path.expanduser("~"), ".deno", "bin", "deno")
    if os.path.isfile(default) and os.access(default, os.X_OK):
        return default
    return None


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _deep_merge_dict(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for key, val in overlay.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(val, dict)
        ):
            out[key] = _deep_merge_dict(out[key], val)
        else:
            out[key] = val
    return out


def merge_yt_dlp_env_into(ydl_opts: dict) -> None:
    """
    Apply optional yt-dlp overrides from the environment (GitHub Actions iteration knobs).

    See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp

    YT_DLP_COOKIE_FILE — path to Netscape cookies.txt (write from Actions secret if needed).
    YT_DLP_PLAYER_CLIENT — comma-separated list → extractor_args youtube player_client
    YT_DLP_EXTRACTOR_ARGS_JSON — JSON object merged into extractor_args (overrides CSV keys).
    YT_DLP_COMPAT_OPTIONS — comma-separated compat_opts (e.g. 2025).
    YT_DLP_IMPERSONATE — passed to ImpersonateTarget.from_str (requires curl-cffi).
    YT_DLP_USER_AGENT — optional HTTP User-Agent (skipped if YT_DLP_IMPERSONATE is set).
    YT_DLP_SOCKET_TIMEOUT — float seconds for socket_timeout.
    YT_DLP_VERBOSE — if truthy, forces verbose logging and disables quiet/noprogress.
    YT_DLP_DISABLE_FALLBACK — single attempt only (disables automatic no-cookie preset rotation).
    YT_DLP_FORMAT — full yt-dlp -f string (overrides default progressive-audio chain).
    YT_DLP_DENO — explicit path to ``deno`` (otherwise PATH / ~/.deno/bin/deno).
    """
    extractor_args: dict = {}

    cookie_file = os.getenv("YT_DLP_COOKIE_FILE", "").strip()
    if cookie_file:
        if os.path.isfile(cookie_file):
            ydl_opts["cookiefile"] = cookie_file
        else:
            logger.warning(
                "YT_DLP_COOKIE_FILE is set but file is missing: %s",
                cookie_file,
            )

    raw_clients = os.getenv("YT_DLP_PLAYER_CLIENT", "").strip()
    if raw_clients:
        clients = [x.strip() for x in raw_clients.split(",") if x.strip()]
        if clients:
            extractor_args.setdefault("youtube", {})["player_client"] = clients

    json_blob = os.getenv("YT_DLP_EXTRACTOR_ARGS_JSON", "").strip()
    if json_blob:
        try:
            parsed = json.loads(json_blob)
            if isinstance(parsed, dict):
                extractor_args = _deep_merge_dict(extractor_args, parsed)
            else:
                logger.warning(
                    "YT_DLP_EXTRACTOR_ARGS_JSON must be a JSON object; ignoring",
                )
        except json.JSONDecodeError as err:
            logger.warning(
                "YT_DLP_EXTRACTOR_ARGS_JSON is not valid JSON (%s); ignoring",
                err,
            )

    if extractor_args:
        existing = ydl_opts.get("extractor_args") or {}
        if not isinstance(existing, dict):
            existing = {}
        ydl_opts["extractor_args"] = _deep_merge_dict(existing, extractor_args)

    compat_raw = os.getenv("YT_DLP_COMPAT_OPTIONS", "").strip()
    if compat_raw:
        parts = {x.strip() for x in compat_raw.split(",") if x.strip()}
        if parts:
            prev = ydl_opts.get("compat_opts") or set()
            ydl_opts["compat_opts"] = set(prev) | parts

    impersonate_raw = os.getenv("YT_DLP_IMPERSONATE", "").strip()
    if impersonate_raw:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        ydl_opts["impersonate"] = ImpersonateTarget.from_str(
            impersonate_raw.lower(),
        )

    if not impersonate_raw:
        ua = os.getenv("YT_DLP_USER_AGENT", "").strip()
        if ua:
            headers = dict(ydl_opts.get("http_headers") or {})
            headers["User-Agent"] = ua
            ydl_opts["http_headers"] = headers

    timeout_raw = os.getenv("YT_DLP_SOCKET_TIMEOUT", "").strip()
    if timeout_raw:
        try:
            ydl_opts["socket_timeout"] = float(timeout_raw)
        except ValueError:
            logger.warning(
                "YT_DLP_SOCKET_TIMEOUT must be a float; got %r",
                timeout_raw,
            )

    if _truthy_env("YT_DLP_VERBOSE"):
        ydl_opts["quiet"] = False
        ydl_opts["noprogress"] = False
        ydl_opts["verbose"] = True

    format_override = os.getenv("YT_DLP_FORMAT", "").strip()
    if format_override:
        ydl_opts["format"] = format_override


def _explicit_yt_dlp_strategy_env() -> bool:
    """True when the operator set tuning env vars (skip automatic preset rotation)."""
    return bool(
        os.getenv("YT_DLP_COOKIE_FILE", "").strip()
        or os.getenv("YT_DLP_IMPERSONATE", "").strip()
        or os.getenv("YT_DLP_PLAYER_CLIENT", "").strip()
        or os.getenv("YT_DLP_EXTRACTOR_ARGS_JSON", "").strip()
        or os.getenv("YT_DLP_COMPAT_OPTIONS", "").strip()
        or os.getenv("YT_DLP_USER_AGENT", "").strip()
        or os.getenv("YT_DLP_FORMAT", "").strip()
    )


def _merge_ydl_overlay(base: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in overlay.items():
        if key == "extractor_args":
            out[key] = _deep_merge_dict(out.get(key) or {}, val)
        elif key == "compat_opts":
            prev = out.get("compat_opts") or set()
            out[key] = set(prev) | set(val)
        else:
            out[key] = val
    return out


def _yt_dlp_fallback_overlays() -> tuple[dict, ...]:
    """Preset rotation without cookies (TLS fingerprint + YouTube client paths).

    Stronger presets run first so datacenter IPs (e.g. GitHub-hosted runners) fail fast past vanilla `{}`.
    """
    from yt_dlp.networking.impersonate import ImpersonateTarget

    I = ImpersonateTarget.from_str
    return (
        {
            "impersonate": I("chrome-136"),
            "extractor_args": {"youtube": {"player_client": ["tv"]}},
        },
        {
            "impersonate": I("chrome-136"),
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        },
        {"impersonate": I("chrome-136")},
        {
            "impersonate": I("chrome-131:android-12"),
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        },
        {
            "impersonate": I("chrome-99:android-12"),
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        },
        {
            "impersonate": I("edge-101:windows-10"),
            "extractor_args": {"youtube": {"player_client": ["web"]}},
        },
        {"impersonate": I("firefox-135:macos-14")},
        {},
    )


def info_has_playable_youtube_audio(info: dict) -> bool:
    """
    True when yt-dlp extracted metadata shows at least one audio stream that is
    not DRM-flagged as definite or ``maybe`` (matches ``YOUTUBE_AUDIO_FORMAT_SPEC`` filters).

    Videos that only expose DRM formats will fail actual downloads; probing avoids that.
    """
    formats = info.get("formats")
    if not formats:
        return False
    for fmt in formats:
        acodec = fmt.get("acodec")
        if acodec in (None, "none"):
            continue
        drm = fmt.get("has_drm")
        if drm is True or drm == "maybe":
            continue
        return True
    return False


def build_yt_dlp_download_attempt_opts(base_opts: dict) -> list[dict]:
    """
    Build yt-dlp option dicts to try in order.

    When YT_DLP_DISABLE_FALLBACK is set, or when cookie / impersonate / extractor tuning
    env vars are set, returns a single attempt (operator-controlled).

    Otherwise returns default presets (no cookies).
    """
    if _truthy_env("YT_DLP_DISABLE_FALLBACK") or _explicit_yt_dlp_strategy_env():
        return [copy.deepcopy(base_opts)]
    return [_merge_ydl_overlay(base_opts, o) for o in _yt_dlp_fallback_overlays()]


def _scrub_partial_downloads(output_stem: str) -> None:
    """Remove partial outputs before the next yt-dlp attempt."""
    for match in glob.glob(glob.escape(output_stem) + "*"):
        try:
            os.remove(match)
        except OSError:
            pass


class YtFetch():
    def __init__(self, **kwargs):
        api_key = os.getenv('YT_API_KEY')
        if not api_key:
            raise ValueError("Missing required environment variable: YT_API_KEY")
        self.youtube = googleapiclient.discovery.build("youtube", "v3", 
                                                       developerKey=api_key)
        self.ytmusic = ytmusicapi.YTMusic()
        self.last_response = None
        supaset_name = f'{is_production_prefix()}ytfetch_video_ids_returned'
        self.video_ids_returned = SupaSet(supaset_name,
                                          autoexpire = kwargs.get('video_ids_supaset_autoexpire_days', 180))

    def _build_youtube_audio_ydl_opts(
        self,
        output_stem: str,
        max_duration=None,
        *,
        for_download: bool = False,
    ) -> dict:
        """Options aligned between probe and ``download_audio`` (same format chain + env)."""
        ffmpeg_pp_args = ["-ac", "2"]
        ydl_opts = {
            "format": YOUTUBE_AUDIO_FORMAT_SPEC,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                    "preferredquality": "192",
                }
            ],
            "outtmpl": output_stem,
            "nocheckcertificate": True,
            "remote_components": {"ejs:github"},
            "quiet": True,
            "noprogress": True,
            "postprocessor_args": ffmpeg_pp_args,
        }
        deno_exe = _resolved_deno_executable()
        if deno_exe:
            ydl_opts["js_runtimes"] = {"deno": {"path": deno_exe}}
        if for_download:
            # HEAD/quick fragment test on the chosen format only (too slow for search probes).
            ydl_opts["check_formats"] = "selected"
        if max_duration:
            logger.info(f"Setting max duration to {max_duration}")
            ffmpeg_pp_args.extend(["-t", str(max_duration)])
        return ydl_opts

    def youtube_video_has_extractable_audio(self, video_url: str, max_duration=None) -> bool:
        """
        Run yt-dlp metadata extraction (no download) and check that at least one
        non-DRM audio format exists, using the same env-driven presets as ``download_audio``.
        """
        probe_stem = os.path.join(
            tempfile.gettempdir(),
            f"llmfh_yt_probe_{uuid.uuid4().hex}",
        )
        ydl_opts = self._build_youtube_audio_ydl_opts(probe_stem, max_duration)
        merge_yt_dlp_env_into(ydl_opts)
        attempts = build_yt_dlp_download_attempt_opts(ydl_opts)
        last_err: BaseException | None = None
        for idx, attempt_opts in enumerate(attempts):
            opts = copy.deepcopy(attempt_opts)
            opts["quiet"] = True
            opts["noprogress"] = True
            try:
                with youtube_dl.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                if info_has_playable_youtube_audio(info):
                    return True
            except (DownloadError, ExtractorError, YoutubeDLError, OSError) as err:
                last_err = err
                logger.debug(
                    "yt-dlp DRM/audio probe attempt %s/%s failed: %s",
                    idx + 1,
                    len(attempts),
                    err,
                )
            finally:
                _scrub_partial_downloads(probe_stem)
        if last_err:
            logger.info(
                "yt-dlp probe could not confirm playable audio for %s: %s",
                video_url,
                last_err,
            )
        return False

    @retry((googleapiclient.errors.HttpError,), tries=3, delay=2)
    def _execute_with_retry(self, request, operation_name):
        try:
            return request.execute()
        except googleapiclient.errors.HttpError as error:
            logger.warning(f"{operation_name} failed, retrying: {error}")
            raise
        
    def finalize(self):
        logger.info("Finalizing YtFetch")
        self.video_ids_returned.complete_session()
    
    def search_video(self, query, orderby="relevance"):
        return self.search_videos(query, orderby=orderby, max_results=1)[0]
    
    def search_videos(self, query, duration_search_filter=None, orderby="relevance", max_results=30):
        
        request = self.youtube.search().list(
            part="snippet",
            type="video",
            q=query,
            videoDefinition="any",
            videoDuration="any" if duration_search_filter is None else duration_search_filter,
            maxResults=30,
            fields="items(id(videoId),snippet(channelId,title,description,channelTitle))",
            safeSearch="strict",
            order=orderby #rating, relevance, viewCount, date, title, videoCount
        )
        response = self._execute_with_retry(request, "youtube_search")
        self.last_response = response
        videos = []
        for item in response['items']:
            videos.append({
                'video_id': item['id']['videoId'],
                'title': html.unescape(item['snippet']['title']),
                'description': html.unescape(item['snippet']['description']),
                'channel_title': html.unescape(item['snippet']['channelTitle']),
                'video_url': f"https://www.youtube.com/watch?v={item['id']['videoId']}"
            })
        
        return videos
        
    def search_music(self, query, orderby=None, max_results=30):
        results = self.ytmusic.search(query, filter="videos", limit=max_results)
        
        videos = []
        for result in results:
            #convert duration to seconds from HH:MM:SS, or MM:SS, or SS formats
            duration = None
            if duration_text := result.get('duration', None):
                duration = 0
                for i, d in enumerate(reversed(duration_text.split(':'))):
                    duration += int(d) * 60**i
            
            videos.append({
                'video_id': result['videoId'],
                'title': get_nested_value(result, 'artists.0.name', '') + ' - ' + result['title'],
                'description': None,
                'channel_title': get_nested_value(result, 'artists.0.name', ''),
                'video_url': f"https://www.youtube.com/watch?v={result['videoId']}",
                'duration': duration
            })
        return videos
        
    
    def download_audio(self, video_url, output_file, max_duration=None):
        output_file = output_file.replace(".wav", "")
        ydl_opts = self._build_youtube_audio_ydl_opts(
            output_file, max_duration, for_download=True
        )
        merge_yt_dlp_env_into(ydl_opts)

        attempts = build_yt_dlp_download_attempt_opts(ydl_opts)
        last_err: BaseException | None = None
        for idx, attempt_opts in enumerate(attempts):
            if idx:
                _scrub_partial_downloads(output_file)
            try:
                with youtube_dl.YoutubeDL(attempt_opts) as ydl:
                    ydl.download([video_url])
                if idx:
                    logger.info(
                        "yt-dlp download succeeded using fallback preset %s/%s",
                        idx + 1,
                        len(attempts),
                    )
                break
            except (DownloadError, ExtractorError, YoutubeDLError, OSError) as err:
                last_err = err
                logger.warning(
                    "yt-dlp attempt %s/%s failed: %s",
                    idx + 1,
                    len(attempts),
                    err,
                )
        else:
            if last_err is None:
                raise RuntimeError("yt-dlp: no download attempts were made")
            raise last_err
        
        #confirm file exists and is not empty
        if not os.path.exists(output_file + ".wav"):
            raise Exception(f"File {output_file + '.wav'} does not exist")
        
        for i in range(5):
            if os.path.getsize(output_file + ".wav") == 0:
                time.sleep(i)
        if os.path.getsize(output_file + ".wav") == 0:
            raise Exception(f"File {output_file + '.wav'} is empty")
            

    def search_and_download_audio(self, query, output_file=None):
        video = self.search_video(query)
        video_id = video['video_id']
        logger.info(f"Video Title: {video['title']}")
        if output_file is None:
            output_file = f"{video_id}.wav"
        
        self.download_audio(video['video_url'], output_file)
        logger.info(f"Audio saved as {output_file}")
        
    
    def duration_in_seconds(self, iso_duration):
        """Helper function to convert ISO 8601 duration to seconds"""
        if iso_duration is None:
            return None
        else:
            duration = parse_duration(iso_duration)
            return duration.total_seconds()

    def llm_filter_title(self, chat_app, llm_filter_prompt, title, description, channel_title):
        """
        Filter videos based on title, description, and channel title using a call to GPT.
        """
        if llm_filter_prompt:
            template = Template(llm_filter_prompt)
            logger.info(f"LLM Checking video title {title}")
            prompt = template.render(title=title, description=description, channel_title=channel_title)
            logger.info(f"Prompt: {prompt}")
            response = chat_app.run_structured(prompt, LlmFilterResponse, log_prompt=True)
            logger.info(f"Response: {response}")
            if response.get("answer", "").lower() == "no":
                return True
        return False

    def search_video_with_duration(self, query, **kwargs):
        """Searches for a video that falls within the specified duration range"""
        duration_search_filter = kwargs.get('duration_search_filter')
        description_filters = kwargs.get('description_filters')
        orderby = kwargs.get('orderby', 'relevance')
        llm_filter_prompt = kwargs.get('llm_filter_prompt')
        chat_app = kwargs.get('chat_app')
        min_duration = kwargs.get('duration_min_sec')
        max_duration = kwargs.get('duration_max_sec')
        truncation_duration_sec = kwargs.get('truncation_duration_sec')
        random_shuffle = kwargs.get('random_shuffle', False)
        use_music = kwargs.get('use_music_search', False)

        # First, perform a general search
        if use_music:
            videos = self.search_music(query, max_results=30)
        else:
            videos = self.search_videos(query, duration_search_filter, orderby, max_results=30)


        # Randomize the order of items in the response
        if random_shuffle:
            random.shuffle(videos)
    
        # Now, for each video in the search results, check the duration
        for video in videos:
            video_id = video['video_id']
            title = video['title']
            description_trimmed = video['description']
            channel_title = video['channel_title']
            duration_seconds = video['duration'] if use_music else None
            
            if video_id in self.video_ids_returned:
                logger.info(f"Video {video_id} already returned. Skipping.")
                continue

            # Check if the description contains the filter string
            if self.description_filter(description_trimmed, description_filters):
                continue
        
            # Fetch the video details, only for non-music searches
            if not use_music:
                video_request = self.youtube.videos().list(
                    part="snippet, contentDetails",
                    id=video_id
                )
                video_response = self._execute_with_retry(video_request, "youtube_video_details")

                # Get the video duration and description
                duration = video_response['items'][0]['contentDetails']['duration']
                duration_seconds = self.duration_in_seconds(duration)
                full_description = html.unescape(video_response['items'][0]['snippet']['description'])
            
                # Check if the full description contains the filter string
                if self.description_filter(full_description, description_filters):
                    continue
            else:
                full_description = description_trimmed
            
            #check duration
            if min_duration and max_duration:
                if duration_seconds is None:
                    logger.info(f"Video {video_id} duration is None. Skipping.")
                    continue
                if not (min_duration <= duration_seconds <= max_duration):
                    logger.info(f"Video {video_id} duration {duration_seconds} does not fall within the specified range, {min_duration}:{max_duration}. Skipping.")
                    continue
            
            #llm filter for title and description and channel_title
            if self.llm_filter_title(
                chat_app, llm_filter_prompt, title, full_description, channel_title
            ):
                logger.info(f"Video https://www.youtube.com/watch?v={video_id} removed by llm filter. Skipping.")
                continue

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            if not self.youtube_video_has_extractable_audio(
                video_url, truncation_duration_sec
            ):
                logger.info(
                    "Skipping video %s (%r): yt-dlp metadata shows no non-DRM extractable audio",
                    video_id,
                    title,
                )
                continue

            if not self.video_ids_returned.add(video_id):
                logger.info(f"Video {video_id} already returned (could not reserve). Skipping.")
                continue

            return {
                        'video_id': video_id,
                        'title': title,
                        'channel_title': channel_title,
                        'video_url': video_url,
                        'truncation_duration_sec': truncation_duration_sec
                    }

        # If no videos in the specified duration range were found, return None
        return None

    def description_filter(self, description, description_filters):
        """Check if the description contain the filter strings"""
        if description_filters:
            matched_filter = None
            for description_filter in description_filters:
                if fnmatch.fnmatch(description, description_filter):
                    matched_filter = description_filter
                    break

            if matched_filter is not None:
                logger.info(f"Video matches description filter {matched_filter}. Skipping.")
                return True
        
        return False

    def search_and_download_audio_with_duration(self, query, output_file, 
                                                **kwargs):
        """Searches for a video within a specified duration range and downloads its audio"""
        # Search for a video within the specified duration range
        video = self.search_video_with_duration(query, **kwargs)

        # If no video was found, print a message and return
        if video is None:
            logger.info(f"No video found within the specified duration range.")
            return

        # If a video was found, download its audio
        video_id = video['video_id']
        logger.info(f"Video returned: {video}")
        if output_file is None:
            output_file = f"{video_id}.wav"
        
        truncation_duration_sec = video.get('truncation_duration_sec')
        
        self.download_audio(video['video_url'], output_file, truncation_duration_sec)
        logger.info(f"Audio saved as {output_file}")
        
        return video

    def get_playlist_items(self, playlist_id, max_results=50):
        """Get items from a playlist"""
        request = self.youtube.playlistItems().list(
            part="snippet",
            maxResults=max_results,
            playlistId=playlist_id,
            fields="items(snippet(resourceId(videoId)))"
        )
        response = self._execute_with_retry(request, "youtube_playlist_items")
        self.last_response = response
        return [item['snippet']['resourceId']['videoId'] for item in response['items']]


    def download_random_video_from_playlist(self, playlist_id, output_file=None, max_retries=5):
        """Randomly choose a video from a playlist to download"""
        logger.info(f"Retrieving playlist items for playlist id: {playlist_id}")
        video_ids = self.get_playlist_items(playlist_id)

        # Retry loop
        retry_count = 0

        @retry((youtube_dl.utils.ExtractorError, 
                AssertionError,
                youtube_dl.utils.DownloadError), tries=max_retries, delay=2)
        def download_random_video():
            nonlocal retry_count, output_file
            retry_count += 1
            try:
                random_video_id = random.choice(video_ids)
                random_video_url = f"https://www.youtube.com/watch?v={random_video_id}"
                logger.info(f"Chosen Video URL: {random_video_url}")

                # Get video details
                video_request = self.youtube.videos().list(
                    part="snippet",
                    id=random_video_id
                )
                video_response = self._execute_with_retry(video_request, "youtube_video_metadata")

                assert 'items' in video_response and video_response['items'], 'No video details found'
                video_item = video_response['items'][0]
                video_details = {
                    'video_id': random_video_id,
                    'title': html.unescape(video_item['snippet']['title']),
                    'thumbnail': video_item['snippet']['thumbnails']['high']['url'],
                    'video_url': random_video_url
                }
                logger.info(f"Video Title: {video_details['title']}")

                if not self.youtube_video_has_extractable_audio(random_video_url):
                    logger.info(
                        "Skipping DRM/non-downloadable playlist pick: %s",
                        random_video_url,
                    )
                    raise ExtractorError(
                        "No extractable non-DRM audio for playlist candidate",
                    )

                # Download audio
                if not output_file:
                    output_file = f"{random_video_id}.wav"
                self.download_audio(random_video_url, output_file)
                logger.info(f"Audio saved as {output_file}")

                return video_details
            except Exception as e:
                logger.error(f"Error downloading video: {e}")
                if retry_count < max_retries:
                    logger.info(f"Retrying download...{retry_count} of {max_retries}")
                raise e

        return download_random_video()