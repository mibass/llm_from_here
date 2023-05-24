import requests
from requests.auth import HTTPBasicAuth
import dotenv
import os
import mimetypes

import logging
logger = logging.getLogger(__name__)


class PodbeanManager:
    def __init__(self, params, global_results, plugin_instance_name):
        self.params = params
        self.global_results = global_results
        self.plugin_instance_name = plugin_instance_name

        # get client_id and client_secret from .env file
        self.client_id = os.getenv('PODBEAN_CLIENT_ID')
        self.client_secret = os.getenv('PODBEAN_CLIENT_SECRET')

        # get podcast variables
        self.description = global_results.get(
            params.get('description_variable'))
        self.title = global_results.get(params.get('title_variable'))
        self.file_path = global_results.get(params.get('file_path_variable'))
        self.episode_number = global_results.get(
            params.get('episode_number_variable'))
        self.max_episodes = params.get('max_episodes', 5)

        # error if any of these is None
        if not self.description:
            raise ValueError("Description should not be empty")
        if not self.title:
            raise ValueError("Title should not be empty")
        if not self.file_path:
            raise ValueError("File path should not be empty")
        if not self.episode_number:
            raise ValueError("Episode number should not be empty")

        self.access_token = None
        self.episodes = []

    def get_access_token(self):
        url = "https://api.podbean.com/v1/oauth/token"
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {
            'grant_type': 'client_credentials',
        }
        response = requests.post(url, headers=headers, data=data, auth=HTTPBasicAuth(
            self.client_id, self.client_secret))
        if response.status_code == 200:
            self.access_token = response.json()['access_token']
        else:
            raise Exception(f'Failed to get access token: {response.content}')

    def get_episodes(self):
        url = "https://api.podbean.com/v1/episodes"
        params = {
            'access_token': self.access_token,
            'offset': 0,
            'limit': 10
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            self.episodes = response.json()['episodes']
        else:
            raise Exception(f'Failed to get episodes: {response.content}')

    def upload_episode(self):
        if len(self.episodes) >= self.max_episodes:
            logging.info(f"Deleting oldest episode; max episodes: {self.max_episodes}, current episodes: {len(self.episodes)}")
            self.delete_oldest_episode()
        file_key = self._upload()

        return file_key

    def delete_oldest_episode(self):
        if self.episodes:
            oldest_episode = self.episodes.pop()
            self._delete(oldest_episode)

    def publish_episode(self, title, content, status, episode_type, media_key=None, logo_key=None, transcripts_key=None,
                        remote_logo_url=None, remote_media_url=None, remote_transcripts_url=None,
                        season_number=None, episode_number=None, apple_episode_type=None,
                        publish_timestamp=None, content_explicit=None):
        url = "https://api.podbean.com/v1/episodes"

        data = {
            'access_token': self.access_token,
            'title': title,
            'content': content,
            'status': status,
            'type': episode_type,
        }

        optional_params = {
            'media_key': media_key,
            'logo_key': logo_key,
            'transcripts_key': transcripts_key,
            'remote_logo_url': remote_logo_url,
            'remote_media_url': remote_media_url,
            'remote_transcripts_url': remote_transcripts_url,
            'season_number': season_number,
            'episode_number': episode_number,
            'apple_episode_type': apple_episode_type,
            'publish_timestamp': publish_timestamp,
            'content_explicit': content_explicit,
        }

        # Add optional parameters to the data if they are provided
        for key, value in optional_params.items():
            if value is not None:
                data[key] = value

        response = requests.post(url, data=data)
        if response.status_code == 200:
            logging.info(f'Successfully published episode: {response.json()}')
        else:
            logging.error(f'Failed to publish episode: {response.content}')
            raise Exception(f'Failed to publish episode: {response.content}')
        
        return response.json()

    def _upload(self):
        # URL for authorizing the file upload
        auth_url = "https://api.podbean.com/v1/files/uploadAuthorize"

        # Extract the file name from the file path
        filename = os.path.basename(self.file_path)

        # Determine the content type
        content_type, _ = mimetypes.guess_type(self.file_path)

        if content_type is None:
            raise Exception(
                f"Failed to determine content type for file: {self.file_path}")

        # Determine the file size
        filesize = os.path.getsize(self.file_path)

        # Parameters for the authorization request
        auth_params = {
            'access_token': self.access_token,
            'filename': filename,
            'filesize': filesize,
            'content_type': content_type
        }

        # Send the authorization request
        auth_response = requests.get(auth_url, params=auth_params)

        # Check if the request was successful
        if auth_response.status_code == 200:
            # Extract the presigned URL, expiration time, and file key from the response
            presigned_url = auth_response.json()['presigned_url']
            expire_at = auth_response.json()['expire_at']
            file_key = auth_response.json()['file_key']

            # Upload the file to the presigned URL
            with open(self.file_path, 'rb') as file:
                upload_response = requests.put(presigned_url, data=file)

            # Check if the upload was successful
            if upload_response.status_code == 200:
                logger.info(f"Upload successful. File key: {file_key}")
                
            else:
                logger.info(f"Upload failed. Response: {upload_response.text}")
                raise Exception(f"Upload failed. Response: {upload_response.text}")

        elif auth_response.status_code == 400 and auth_response.json()['error'] == "storage_limit_reach":
            logger.critical("Storage limit reached.")
            raise Exception("Storage limit reached.")
        else:
            logger.critical(
                f"Authorization failed. Response: {auth_response.text}")
            raise Exception(
                f"Authorization failed. Response: {auth_response.text}")

        return file_key

    def _delete(self, episode):
        url = f"https://api.podbean.com/v1/episodes/{episode['id']}/delete"
        data = {
            'access_token': self.access_token,
            'delete_media_file': 'yes'
        }
        response = requests.post(url, data=data)
        if response.status_code != 200:
            raise Exception(f'Failed to delete episode: {response.content}')
        
        logging.info(f'Successfully deleted episode: {response.json()}')

    def execute(self):
        self.get_access_token()
        logger.info(f"Got access token")

        self.get_episodes()
        logger.info(f"Found {len(self.episodes)} episodes in feed")
        logger.info(f"Last episodes title was {self.episodes[0]['title']}")

        file_key = self.upload_episode()
        logger.info(f"Uploaded file and got key {file_key} ")

        publish_response = self.publish_episode(title=self.title, content=self.description,
                             status='publish', episode_type='public', media_key=file_key)

        return {'publish_response': publish_response}


if __name__ == "__main__":
    import dotenv
    # #get command line args
    # text = sys.argv[1]
    # speed = sys.argv[2]
    # output_file = sys.argv[3]

    pbm = PodbeanManager(dotenv.get_key(
        '.env', 'PODBEAN_CLIENT_ID'), dotenv.get_key('.env', 'PODBEAN_CLIENT_SECRET'))

    pbm.get_access_token()
    pbm.get_episodes()
    print(pbm.episodes)
