import supabase
from datetime import datetime
import dotenv
import os
import logging
import tempfile
dotenv.load_dotenv()

logger = logging.getLogger(__name__)


class SupabaseBucketManager:
    def __init__(self, params, global_results, plugin_instance_name):
        self.params = params
        self.global_results = global_results
        self.plugin_instance_name = plugin_instance_name
        
        # Initialize with your supabase url and supabase key
        url = os.getenv('SUPASET_URL')
        key = os.getenv('SUPASET_KEY')
        
        self.supabase = supabase.create_client(url, key)
        
        self.bucket_name = self.params.get('bucket_name')
        if not self.bucket_name:
            raise Exception('bucket_name is not defined in params')
        
        self.file_parameter = self.params.get('file_parameter')
        self.file_to_upload = self.global_results.get(self.file_parameter)
        if not self.file_to_upload:
            raise Exception('file_parameter is not defined in params')
        self.file_name = self.file_to_upload.split('/')[-1]
        self.truncate_size_mb = self.params.get('truncate_size_mb')
    
    def create_bucket(self):
        res = self.supabase.storage.create_bucket(self.bucket_name)
        return res

    def truncate_file(self, file_path):
        if self.truncate_size_mb is not None:
            truncate_size_bytes = self.truncate_size_mb * 1024 * 1024
            with open(file_path, 'rb') as file:
                truncated_content = file.read(truncate_size_bytes)

            # Create a temporary file and write the truncated content to it
            with tempfile.NamedTemporaryFile(delete=False) as temp:
                temp.write(truncated_content)
                return temp.name
        else:
            return file_path
        
    def add_file(self, source, destination):
        temp_file_path = self.truncate_file(source)
        res = self.supabase.storage.from_(self.bucket_name).upload(destination, temp_file_path)
        return res

    def get_bucket_size(self):
        files = self.supabase.storage.from_(self.bucket_name).list()
        print(files)
        total_size = sum(file['metadata']['size'] for file in files)
        logger.info(f'Bucket size: {total_size}')
        return total_size

    def delete_old_files(self):
        limit = 0.9*(1 * 1024 * 1024 * 1024)  # 1GB
        if self.get_bucket_size() > limit:
            logger.info('Bucket is almost full, deleting old files')
            files = self.supabase.storage.from_(self.bucket_name).list()
            #files.sort(key=lambda x: x['metadata']['lastModified']')
            while self.get_bucket_size() > limit:
                oldest_file = files.pop(0)
                self.supabase.storage.from_(self.bucket_name).remove(oldest_file['name'])
                logger.info(f"Deleted file {oldest_file['name']}")

    def list_bucket_contents(self):
        files = self.supabase.storage.from_(self.bucket_name).list()
        return files
    
    def execute(self):
        try:
            self.delete_old_files()
            res = self.add_file(self.file_to_upload, self.file_name)
            logger.info(f"Uploaded file to {res}")
        except Exception as e:
            logger.error(f"Non-fatal error uploading file: {e}")
        
        
        return {}
        
