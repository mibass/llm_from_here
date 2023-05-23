import requests
from requests.auth import HTTPBasicAuth

import logging
logger = logging.getLogger(__name__)

class PodbeanManager:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
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
        response = requests.post(url, headers=headers, data=data, auth=HTTPBasicAuth(self.client_id, self.client_secret))
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

    def upload_episode(self, episode):
        if len(self.episodes) >= 5:
            self.delete_oldest_episode()
        self._upload(episode)
        self.episodes.append(episode)

    def delete_oldest_episode(self):
        if self.episodes:
            oldest_episode = self.episodes.pop(0)
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


    def _upload(self, filename, content_type, filesize):
        # URL for authorizing the file upload
        auth_url = "https://api.podbean.com/v1/files/uploadAuthorize"

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
            with open(filename, 'rb') as file:
                upload_response = requests.put(presigned_url, data=file)

            # Check if the upload was successful
            if upload_response.status_code == 200:
                print(f"Upload successful. File key: {file_key}")
            else:
                print(f"Upload failed. Response: {upload_response.text}")

        elif auth_response.status_code == 400 and auth_response.json()['error'] == "storage_limit_reach":
            logger.critical("Storage limit reached.")
        else:
            logger.critical(f"Authorization failed. Response: {auth_response.text}")


    def _delete(self, episode):
        url = f"https://api.podbean.com/v1/episodes/{episode['episode_id']}/delete"
        data = {
            'access_token': self.access_token
        }
        response = requests.post(url, data=data)
        if response.status_code != 200:
            raise Exception(f'Failed to delete episode: {response.content}')


if __name__ == "__main__":
    import dotenv
    # #get command line args
    # text = sys.argv[1]
    # speed = sys.argv[2]
    # output_file = sys.argv[3]
    
    pbm = PodbeanManager(dotenv.get_key('.env', 'PODBEAN_CLIENT_ID'), dotenv.get_key('.env', 'PODBEAN_CLIENT_SECRET'))
    
    pbm.get_access_token()
    pbm.get_episodes()
    print(pbm.episodes)