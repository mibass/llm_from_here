import yaml
from jinja2 import Template
import feedparser
import re
import shutil
from datetime import datetime
import os
import logging
import functools

logger = logging.getLogger(__name__)

from common import log_exception

class PodcastManager:
    def __init__(self):
        self.podcast_title_template = None
        self.final_guests_list_variable = None
        self.podcast_description_template = None
        self.podcast_feed_url = None
        self.podcast_file_name_final_template = None

    @log_exception(logger.error)
    def generate_description(self, guests_audio_segments, gen_date=datetime.today()):
        template = Template(self.podcast_description_template)
        return template.render(guests_audio_segments=guests_audio_segments, gen_date=gen_date)

    @log_exception(logger.error)
    def generate_podcast_title(self, episode_number):
        template = Template(self.podcast_title_template)
        return template.render(episode_number=episode_number)

    @log_exception(logger.error)
    def generate_file_name(self, gen_date=datetime.today()):
        template = Template(self.podcast_file_name_final_template)
        latest_episode_number = self.get_latest_episode_number()
        return template.render(gen_date=gen_date, episode_number=latest_episode_number + 1)

    @log_exception(logger.error)
    @functools.lru_cache(maxsize=None)
    def get_latest_episode_number(self):
        episode_numbers = []
        pattern = re.compile(r"Episode (\d+)")

        feed = feedparser.parse(self.podcast_feed_url)

        for entry in feed.entries:
            match = pattern.search(entry.title)
            if match:
                episode_numbers.append(int(match.group(1)))

        return max(episode_numbers) if episode_numbers else 0

    @log_exception(logger.error)
    def copy_file_to_final_destination(self, gen_date=datetime.today()):
        final_file_name = self.generate_file_name(gen_date)
        original_file_directory = os.path.dirname(self.file_name)
        final_file_path = os.path.join(original_file_directory, final_file_name)
        shutil.copy(self.file_name, final_file_path)
        return final_file_path

    @log_exception(logger.error)
    def execute(self, params, global_results, plugin_instance_name):
        
        self.podcast_title_template = params.get('podcast_title')
        self.final_guests_list_variable = params.get('final_guests_list_variable')
        self.podcast_description_template = params.get('podcast_description_template')
        self.podcast_feed_url = params.get('podcast_feed_url')
        self.podcast_file_name_final_template = params.get('podcast_file_name_final_template')
        
        
        #get global results
        print(params)
        self.file_name = global_results.get(params.get('source_file_name_variable'))
        logger.info(f"Found source file name: {self.file_name} ")
        
        
        guests_audio_segments = global_results.get(self.final_guests_list_variable, [])
        
        logger.info(f"Generating podcast description with guests: {guests_audio_segments}")

        description = self.generate_description(guests_audio_segments)
        logger.info(f"Generated podcast description: {description}")
        
        episode_number = self.get_latest_episode_number() + 1
        logger.info(f"Generated episode number: {episode_number}")
        
        title = self.generate_podcast_title(episode_number)
        logger.info(f"Generated podcast title: {title}")
        
        final_file_path = self.copy_file_to_final_destination()
        logger.info (f"Copied file to final destination: {final_file_path}")
        return {
            'podcast_description': description,
            'podcast_title': title,
            'podcast_file_path': final_file_path,
            'episode_number': episode_number
        }