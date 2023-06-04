import os
import googleapiclient.discovery
import googleapiclient.errors
import youtube_dl
import time
from isodate import parse_duration
import random
import html
import fnmatch
from retry import retry

import logging
logger = logging.getLogger(__name__)



class YtFetch():
    def __init__(self):
        self.youtube = googleapiclient.discovery.build("youtube", "v3", 
                                                       developerKey=os.environ['YT_API_KEY'])
        self.last_response = None
        self.video_ids_returned = []
    
    def search_video(self, query, orderby="relevance"):
        
        request = self.youtube.search().list(
            part="snippet",
            type="video",
            q=query,
            videoDefinition="high",
            maxResults=1,
            fields="items(id(videoId),snippet(channelId,title,description,thumbnails))",
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

    def search_video_with_duration(self, query, min_duration, max_duration, duration_search_filter = None, description_filters=None, orderby="relevance"):
        """Searches for a video that falls within the specified duration range"""

        # First, perform a general search
        request = self.youtube.search().list(
            part="snippet",
            type="video",
            q=query,
            videoDefinition="any",
            videoDuration="any" if duration_search_filter is None else duration_search_filter,
            maxResults=20,
            fields="items(id(videoId),snippet(channelId,title,description,thumbnails))",
            order=orderby #rating, relevance, viewCount, date, title, videoCount
        )
        response = request.execute()

        # Randomize the order of items in the response
        random.shuffle(response['items'])
    
        # Now, for each video in the search results, check the duration
        for item in response['items']:
            video_id = item['id']['videoId']
            
            #only return a video once per session
            if video_id in self.video_ids_returned:
                logger.info(f"Video {video_id} already returned. Skipping.")
                continue

            # Check if the description contains the filter string
            logger.info(f"Checking video description {item['snippet']['description']}")
            if description_filters:
                matched_filter = None
                for description_filter in description_filters:
                    if fnmatch.fnmatch(item['snippet']['description'], description_filter):
                        matched_filter = description_filter
                        break

                if matched_filter is not None:
                    logger.info(f"Video {video_id} matches description filter {matched_filter}. Skipping.")
                    continue
        
            # Fetch the video details
            video_request = self.youtube.videos().list(
                part="contentDetails",
                id=video_id
            )
            video_response = video_request.execute()

            # Get the video duration and convert it to seconds
            duration = video_response['items'][0]['contentDetails']['duration']
            duration_seconds = self.duration_in_seconds(duration)

            # If the duration falls within the specified range, return this video
            if min_duration <= duration_seconds <= max_duration:
                return {
                    'video_id': video_id,
                    'title': html.unescape(item['snippet']['title']),
                    'thumbnail': item['snippet']['thumbnails']['high']['url'],
                    'video_url': f"https://www.youtube.com/watch?v={video_id}"
                }
            else:
                logger.info(f"Video {video_id} duration {duration_seconds} does not fall within the specified range, {min_duration}:{max_duration}. Skipping.")

        # If no videos in the specified duration range were found, return None
        return None



    def search_and_download_audio_with_duration(self, query, output_file, min_duration, max_duration, duration_search_filter, description_filters):
        """Searches for a video within a specified duration range and downloads its audio"""
        # Search for a video within the specified duration range
        video = self.search_video_with_duration(query, min_duration, max_duration, duration_search_filter, description_filters)

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

    import time

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