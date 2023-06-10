import os
import googleapiclient.discovery
import googleapiclient.errors
# import youtube_dl
import yt_dlp as youtube_dl
import time
from isodate import parse_duration
import random
import html
import fnmatch
from retry import retry
from llm_from_here.supaSet import SupaSet
from jinja2 import Template
from llm_from_here.common import is_production_prefix

import logging
logger = logging.getLogger(__name__)



class YtFetch():
    def __init__(self, **kwargs):
        self.youtube = googleapiclient.discovery.build("youtube", "v3", 
                                                       developerKey=os.environ['YT_API_KEY'])
        self.last_response = None
        supaset_name = f'{is_production_prefix()}ytfetch_video_ids_returned'
        self.video_ids_returned = SupaSet(supaset_name,
                                          autoexpire = kwargs.get('video_ids_supaset_autoexpire_days', 90))
        
    
    def search_video(self, query, orderby="relevance"):
        
        request = self.youtube.search().list(
            part="snippet",
            type="video",
            q=query,
            videoDefinition="high",
            maxResults=1,
            fields="items(id(videoId),snippet(channelId,title,description,thumbnails,channelTitle))))",
            order=orderby
        )
        response = request.execute()
        self.last_response = response
        return {'video_id': response['items'][0]['id']['videoId'],
                'title': html.unescape(response['items'][0]['snippet']['title']),
                'thumbnail': response['items'][0]['snippet']['thumbnails']['high']['url'],
                'video_url': f"https://www.youtube.com/watch?v={response['items'][0]['id']['videoId']}"
        }
    
    def download_audio(self, video_url, output_file):
        #strip .wav from output_file
        output_file = output_file.replace(".wav", "")

        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
            'outtmpl': output_file,
            'nocheckcertificate': True, 
            "quiet": True
        }
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        time.sleep(5)

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
        duration = parse_duration(iso_duration)
        return duration.total_seconds()

    def llm_filter_title(self, chat_app, llm_filter_prompt, llm_filter_js, title, description, channel_title):
        """
        Filter videos based on title, description, and channel title using a call to GPT.
        """
        if llm_filter_prompt and llm_filter_js:
            template = Template(llm_filter_prompt)
            logger.info(f"LLM Checking video title {title}")
            prompt = template.render(title=title, description=description, channel_title=channel_title)
            logger.info(f"Prompt: {prompt}")
            response = chat_app.enforce_json_response(prompt, llm_filter_js, log_prompt=True)
            logger.info(f"Response: {response}")
            if response['answer'] == 'no':
                return True
        return False

    def search_video_with_duration(self, query, **kwargs):
        """Searches for a video that falls within the specified duration range"""
        duration_search_filter = kwargs.get('duration_search_filter')
        description_filters = kwargs.get('description_filters')
        orderby = kwargs.get('orderby', 'relevance')
        llm_filter_prompt = kwargs.get('llm_filter_prompt')
        llm_filter_js = kwargs.get('llm_filter_js')
        chat_app = kwargs.get('chat_app')
        min_duration = kwargs.get('duration_min_sec')
        max_duration = kwargs.get('duration_max_sec')

        # First, perform a general search
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
        response = request.execute()

        # Randomize the order of items in the response
        random.shuffle(response['items'])
    
        # Now, for each video in the search results, check the duration
        for item in response['items']:
            video_id = item['id']['videoId']
            title = html.unescape(item['snippet']['title'])
            description_trimmed = html.unescape(item['snippet']['description'])
            channel_title = html.unescape(item['snippet']['channelTitle'])
            
            # Check if this video has already been returned
            if not self.video_ids_returned.add(video_id):
                logger.info(f"Video {video_id} already returned. Skipping.")
                continue

            # Check if the description contains the filter string
            if self.description_filter(description_trimmed, description_filters):
                continue
        
            # Fetch the video details
            video_request = self.youtube.videos().list(
                part="snippet, contentDetails",
                id=video_id
            )
            video_response = video_request.execute()

            # Get the video duration and description
            duration = video_response['items'][0]['contentDetails']['duration']
            duration_seconds = self.duration_in_seconds(duration)
            full_description = html.unescape(video_response['items'][0]['snippet']['description'])
            
            # Check if the full description contains the filter string
            if self.description_filter(full_description, description_filters):
                continue
            
            #check duration
            if min_duration and max_duration:
                if not (min_duration <= duration_seconds <= max_duration):
                    logger.info(f"Video {video_id} duration {duration_seconds} does not fall within the specified range, {min_duration}:{max_duration}. Skipping.")
                    continue
            
            #llm filter for title and description and channel_title
            if self.llm_filter_title(chat_app, llm_filter_prompt, llm_filter_js, 
                                     title, full_description, channel_title):
                logger.info(f"Video https://www.youtube.com/watch?v={video_id} removed by llm filter. Skipping.")
                continue
            
            # if everything passes, return the video
            return {
                        'video_id': video_id,
                        'title': title,
                        'channel_title': channel_title,
                        'video_url': f"https://www.youtube.com/watch?v={video_id}"
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
        logger.info(f"Video Title: {video['title']}")
        if output_file is None:
            output_file = f"{video_id}.wav"
        
        self.download_audio(video['video_url'], output_file)
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
        response = request.execute()
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
                video_response = video_request.execute()

                assert 'items' in video_response and video_response['items'], 'No video details found'
                video_item = video_response['items'][0]
                video_details = {
                    'video_id': random_video_id,
                    'title': html.unescape(video_item['snippet']['title']),
                    'thumbnail': video_item['snippet']['thumbnails']['high']['url'],
                    'video_url': random_video_url
                }
                logger.info(f"Video Title: {video_details['title']}")

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