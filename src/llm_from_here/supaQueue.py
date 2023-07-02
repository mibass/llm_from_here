"""
SupaQueue is a simple queue implementation using Supabase as the backend.

This requires a table to be created in Supabase with the following schema:

DROP TABLE supaqueue;
CREATE TABLE IF NOT EXISTS supaqueue (
    id SERIAL PRIMARY KEY,
    value TEXT NOT NULL,
    queue_name TEXT NOT NULL,
    to_be_deleted BOOLEAN DEFAULT FALSE  
);

It also requires environment variables to be set for SUPASET_URL and SUPASET_KEY.
"""
from supabase import create_client
import logging
import os

logger = logging.getLogger(__name__)

class SupaQueue:
    table_name = 'supaqueue'

    def __init__(self, queue_name, case_sensitive=True):
        SUPASET_URL = os.environ.get('SUPASET_URL')
        SUPASET_KEY = os.environ.get('SUPASET_KEY')

        self.client = create_client(SUPASET_URL, SUPASET_KEY)
        self.queue_name = queue_name
        self.case_sensitive = case_sensitive
        self._cleanup_incomplete_sessions()

    def _table(self):
        return self.client.table(self.table_name)

    def enqueue(self, values):
        if not isinstance(values, list):
            values = [values]
        
        if not self.case_sensitive:
            values = [value.lower() for value in values]
        try:
            for value in values:
                logger.info(f"Enqueueing {value} to SupaQueue {self.queue_name}")
                self._table().insert(
                    {"value": value, "queue_name": self.queue_name, "to_be_deleted": False}).execute()
        except Exception as e:
            logger.error(f"Failed to enqueue {values}, error: {e}")

    def dequeue(self, n_entries=1):
        """
        Dequeue n_entries items from the queue.
        """
        if n_entries == 0:
            return []
        try:
            data = self._table().select("value").eq("queue_name", self.queue_name).eq("to_be_deleted", False).order("id").limit(n_entries).execute()
            values = [item['value'] for item in data.data]
            for v in values:
                logger.info(f"Dequeuing {v} from SupaQueue {self.queue_name}")
                self._table().update({"to_be_deleted": True}).eq("queue_name", self.queue_name).eq("value", v).execute()
            return values
        except Exception as e:
            logger.error(f"Failed to dequeue, error: {e}")

    def peek(self, n_entries=1):
        """
        Returns the next n_entries items in the queue without dequeuing.
        """
        try:
            data = self._table().select("value").eq("queue_name", self.queue_name).eq("to_be_deleted", False).order("id").limit(n_entries).execute()
            values = [item['value'] for item in data.data]
            return values
        except Exception as e:
            logger.error(f"Failed to peek, error: {e}")


    def _cleanup_incomplete_sessions(self):
        try:
            self._table().update({"to_be_deleted": False}).eq("queue_name", self.queue_name).execute()
        except Exception as e:
            logger.error(f"Failed to clean incomplete session entries, error: {e}")
            
    def clear(self):
        try:
            self._table().delete().eq("queue_name", self.queue_name).execute()
            logger.info(f"Cleared supaqueue: {self.queue_name}")
        except Exception as e:
            logger.error(f"Failed to clear {self.queue_name}, error: {e}")
            
    def length(self):
        """
        Returns the current length (i.e., the number of items) in the queue.
        """
        try:
            data = self._table().select("value").eq("queue_name", self.queue_name).eq("to_be_deleted", False).execute()
            return len(data.data)
        except Exception as e:
            logger.error(f"Failed to get length of queue, error: {e}")


    def finalize(self):
        """
        Finalizes the queue, deleting all entries with to_be_deleted set to True.
        """
        try:
            self._table().delete().eq("queue_name", self.queue_name).eq("to_be_deleted", True).execute()
            logger.info(f"Finalized queue: {self.queue_name}")
        except Exception as e:
            logger.error(f"Failed to finalize queue, error: {e}")

