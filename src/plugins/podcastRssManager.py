

import pickle
import os
from jinja2 import Template
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
import yaml
import datetime

class PodcastRssManager:
    def __init__(self):
        # self.pickle_path = pickle_path
        self.podcasts = []
        # if os.path.exists(self.pickle_path):
        #     with open(self.pickle_path, 'rb') as f:
        #         self.podcasts = pickle.load(f)

    def add_podcast(self, podcast_dict, template_str, global_results):
        template = Template(template_str)
        description = template.render(global_results)
        podcast_dict["description"] = description
        self.podcasts.append(podcast_dict)
        # with open(self.pickle_path, 'wb') as f:
        #     pickle.dump(self.podcasts, f)

    def export_to_rss(self, filepath):
        rss = Element('rss', version='2.0')
        channel = SubElement(rss, 'channel')

        for podcast in self.podcasts:
            item = SubElement(channel, 'item')
            for key, value in podcast.items():
                SubElement(item, key).text = value

        xml_string = tostring(rss, 'utf-8')
        parsed_string = minidom.parseString(xml_string)
        pretty_string = parsed_string.toprettyxml(indent="  ")

        # with open(filepath, 'w') as f:
        #     f.write(pretty_string)
        print(xml_string)
            
    def execute(self, params, global_results, plugin_instance_name):
        podcast_dict = params.get('podcast_dict', {})
        template_str = params.get('template_str', '')
        
        #add date to global_results
        global_results[plugin_instance_name+'_date'] = datetime.datetime.now()
        
        self.add_podcast(podcast_dict, template_str, global_results)
            
        return {'podcasts': self.podcasts}
            
        
