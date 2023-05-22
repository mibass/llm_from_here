import freesound
from dotenv import load_dotenv
import os
import random
import pathvalidate

load_dotenv()  # take environment variables from .env.

#TODO: sanitze file names like 
#FileNotFoundError: [Errno 2] No such file or directory: "/Users/matthewbass/Documents/modules/pymb/lfh/src/../outputs/show_run74/Neurofunk/ D'n'B Style Distorted Synth Bass Wob.wav"

class FreeSoundFetch:
    def __init__(self, out_dir="."):
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
        temp_file_name = os.path.join(self.out_dir, f"{sanitized_filename}.wav")
        sound.retrieve_preview(self.out_dir, name=temp_file_name)
        self.temp_files.append(temp_file_name)

    def search_and_download_top_samples(self, query, num_samples=1, filter_params=None):
        sorted_results = self.search_samples(query, filter_params)
        sounds = [sound for sound in sorted_results]
        random.shuffle(sounds)
        # Download the top samples
        i=0
        for sound in sounds:
            self.download_sample(sound)
            i+=1
            if i>=num_samples:
                break

    def execute(self, params, global_params, plugin_instance_name):
        query = params.get('query')
        num_samples = params.get('num_samples', 1)
        filter_params = params.get('filter_params', {})
        if 'out_dir' in global_params:
            self.out_dir = params.get('out_dir')
        if not os.path.isdir(self.out_dir):
            os.makedirs(self.out_dir, exist_ok=True)
        self.search_and_download_top_samples(query, num_samples, filter_params)
        return {'temp_files': self.temp_files}

    def get_temp_file_names(self):
        return self.temp_files
