import asyncio
import os
import tempfile
import zipfile
from requests_html import AsyncHTMLSession
import requests
import dotenv
import argparse
import shutil
dotenv.load_dotenv()


class DownloadEffects:
    def __init__(self):
        self.template_url = os.getenv('DE_TEMPLATE_URL')
        self.download_url = os.getenv('DE_DOWNLOAD_URL')

    def get_ids(self, search_term):
        async def scrape_page():
            # Create an asynchronous HTML session
            session = AsyncHTMLSession()

            # Construct the URL with the search term
            url = self.template_url.format(search_term)

            # Send a GET request to the URL
            response = await session.get(url, timeout=20)

            # Execute JavaScript on the page
            await response.html.arender(wait=1, scrolldown=5, sleep=1)

            # Get the modified HTML source code after executing JavaScript
            html = response.html.html

            divs_with_id = response.html.find('div[id]')

            # Iterate over the found <div> elements
            ids = []
            for div in divs_with_id:
                # Print the id attribute and the contents of the div
                print(f"ID: {div.attrs['id']}")
                if div.attrs['id'] not in ('root'):
                    text = div.find('p.text-sm')[0].text
                    duration_text = div.find('div.text-sm')[0].text
                    #convert 0:05 format to seconds
                    duration = int(duration_text.split(':')[0]) * 60 + int(duration_text.split(':')[1])
                    ids.append({'id': div.attrs['id'], 
                                'text': text.strip(),
                                'duration': duration})

            # Close the session
            await session.close()
            return ids

        # Run the asynchronous scraping function
        return asyncio.run(scrape_page())
    
    def download_id(self, id, file_path):
        url = self.download_url.format(id)
        print(f"Downloading file from: {url}")
        # Download the file
        r = requests.get(url, stream=True)
        
        if r.status_code != 200:
            print(f"Error: received status code {r.status_code} when trying to download file.")
            return

        with tempfile.NamedTemporaryFile() as tf:
            for chunk in r.iter_content(1024):
                if chunk:
                    tf.write(chunk)
            tf.seek(0)

            try:
                with zipfile.ZipFile(tf.name, 'r') as zip_ref:
                    zip_ref.extractall(os.path.dirname(file_path))
                    filename = zip_ref.namelist()[0]
                    original_file_path = os.path.join(os.path.dirname(file_path), filename)
                    shutil.move(original_file_path, file_path)
            except zipfile.BadZipFile:
                print(f"Error: The file downloaded from {url} was not a valid zip file.")
                return

        return file_path

    def search_and_download(self, search_term, file_path):
        # Get the IDs of the effects
        ids = self.get_ids(search_term)
        print(f"Found {ids}")

        # Download the first entry
        if ids:
            filename = self.download_id(ids[0].get('id'), file_path)
            print(f"Downloaded and extracted file: {filename}")
            if os.path.isfile(filename):
                return True
        else:
            print("No effects found for the search term.")
        return False


# Initialize the DownloadEffects class
effects = DownloadEffects()

# Search and download the first entry for a search term
download_status = effects.search_and_download('bang', 'bang.wav')

