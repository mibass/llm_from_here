import freesound
from dotenv import load_dotenv
import os
import random
import pathvalidate
import logging

logger = logging.getLogger(__name__)


load_dotenv()  # take environment variables from .env.

class FreeSoundFetch:
    def __init__(self, params, global_results, plugin_instance_name, out_dir="."):
        self.params = params
        self.global_results = global_results
        self.plugin_instance_name = plugin_instance_name

        self.client = freesound.FreesoundClient()
        self.client.set_token(os.getenv('FREESOUND_API_KEY'), "token")
        self.temp_files = []
        self.out_dir = out_dir

    def search_samples(self, query, filter_params=None):
        if not query:
            raise ValueError("Query should not be empty")

        if filter_params is None:
            filter_params = {}

        # Perform the search
        results = self.client.text_search(query=query, sort="rating_desc", **filter_params)
        #print(results)
        
        
        return results

    def download_sample(self, sound):
        sanitized_filename = pathvalidate.sanitize_filename(sound.name)
        temp_file_name = os.path.join(self.out_dir, f"{sanitized_filename}")
        sound.retrieve_preview(self.out_dir, name=temp_file_name)
        #the file names always have .mp3 appended to them
        self.temp_files.append(temp_file_name + ".mp3")

    def search_and_download_top_samples(self, query, num_samples=1, filter_params=None):
        #TODO: come up with a better way to clear the query of certain strings
        clear_strings = ['[BACKGROUND']
        for clear_string in clear_strings:
            query = query.replace(clear_string, '')
        sorted_results = self.search_samples(query, filter_params)
        sounds = [sound for sound in sorted_results]
        random.shuffle(sounds)
        # Download the top samples
        i=0
        for sound in sounds:
            logger.info(f"Downloading sample {i+1} of {num_samples}: {sound.name}")
            self.download_sample(sound)
            i+=1
            if i>=num_samples:
                break
        return i

    def execute(self):
        query = self.params.get('query')
        num_samples = self.params.get('num_samples', 1)
        filter_params = self.params.get('filter_params', {})
        if 'out_dir' in self.global_results:
            self.out_dir = self.params.get('out_dir')
        if not os.path.isdir(self.out_dir):
            os.makedirs(self.out_dir, exist_ok=True)
        self.search_and_download_top_samples(query, num_samples, filter_params)
        return {'temp_files': self.temp_files}

    def get_temp_file_names(self):
        return self.temp_files
