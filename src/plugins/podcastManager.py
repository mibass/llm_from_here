from common import log_exception
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


class PodcastManager:
    def __init__(self, params, global_results, plugin_instance_name):
        self.params = params
        self.global_results = global_results
        self.plugin_instance_name = plugin_instance_name

        self.podcast_title_template = self.params.get('podcast_title')
        self.final_guests_list_variable = self.params.get(
            'final_guests_list_variable')
        self.podcast_description_template = self.params.get(
            'podcast_description_template')
        self.podcast_feed_url = self.params.get('podcast_feed_url')
        self.podcast_file_name_final_template = self.params.get(
            'podcast_file_name_final_template')

        # get global results
        self.file_name = self.global_results.get(
            self.params.get('source_file_name_variable'))
        logger.info(f"Found source file name: {self.file_name} ")

        self.guests_audio_segments = self.global_results.get(
            self.final_guests_list_variable, [])
        self.guests_audio_segments_key = self.params.get(
            'final_guests_list_key')

    @log_exception(logger.error)
    def generate_distinct_guests(self, list_of_dicts, key):
        return list({d[key] for d in list_of_dicts if key in d})

    @log_exception(logger.error)
    def generate_description(self, guests_audio_segments, guest_key, gen_date=datetime.today()):
        template = Template(self.podcast_description_template)

        distinct_guests = self.generate_distinct_guests(
            guests_audio_segments, guest_key)

        return template.render(guests_audio_segments=distinct_guests, gen_date=gen_date)

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
        final_file_path = os.path.join(
            original_file_directory, final_file_name)
        shutil.copy(self.file_name, final_file_path)
        return final_file_path

    @log_exception(logger.error)
    def execute(self):
        logger.info(
            f"Generating podcast description with guests: {self.guests_audio_segments} and key {self.guests_audio_segments_key}")

        description = self.generate_description(
            self.guests_audio_segments, self.guests_audio_segments_key)
        logger.info(f"Generated podcast description: {description}")

        episode_number = self.get_latest_episode_number() + 1
        logger.info(f"Generated episode number: {episode_number}")

        title = self.generate_podcast_title(episode_number)
        logger.info(f"Generated podcast title: {title}")

        final_file_path = self.copy_file_to_final_destination()
        logger.info(f"Copied file to final destination: {final_file_path}")
        return {
            'podcast_description': description,
            'podcast_title': title,
            'podcast_file_path': final_file_path,
            'episode_number': episode_number
        }
