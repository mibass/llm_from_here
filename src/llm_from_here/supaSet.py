
"""
SupaSet is a simple set implementation using Supabase as the backend.

This requires a table to be created in Supabase with the following schema:

DROP TABLE supasets;
CREATE TABLE IF NOT EXISTS supasets (
    id SERIAL PRIMARY KEY,
    value TEXT NOT NULL,
    set_name TEXT NOT NULL,
    session_id UUID NOT NULL,
    is_session_complete BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
    
);

CREATE UNIQUE INDEX idx_supasets_unique_value 
ON supasets (value, set_name);

It also requires environment variables to be set for SUPASET_URL and SUPASET_KEY.
"""
from supabase import create_client
from uuid import uuid4
import logging
import os
from datetime import datetime, timedelta
from llm_from_here.common import is_production

logger = logging.getLogger(__name__)

def clear_supaset(set_name):
    """
    Clear all values from the passed supaset.
    """
    if is_production():
        logger.error("Cannot clear supaset in production.")
        return False
    
    ss = SupaSet(set_name)
    data = ss._table().delete().eq("set_name", set_name).execute()
    logger.info(f"Cleared supaset: {set_name}, data: {data}")


class SupaSet:
    table_name = 'supasets'

    def __init__(self, set_name, autoexpire=None, case_sensitive=False):
        SUPASET_URL = os.environ.get('SUPASET_URL')
        SUPASET_KEY = os.environ.get('SUPASET_KEY')

        self.client = create_client(SUPASET_URL, SUPASET_KEY)
        self.set_name = set_name
        self.session_id = uuid4().hex  # Generate a new UUID for this session
        self.case_sensitive = case_sensitive
        self._cleanup_incomplete_sessions()
        self.autoexpire(autoexpire)

    def autoexpire(self, autoexpire):
        if autoexpire:
            if isinstance(autoexpire, int):
                #delete entries older than autoexpire days
                current_date = datetime.now()
                date_90_days_ago = current_date - timedelta(days=90)
                data = self._table().delete().eq("set_name", self.set_name).lt("created_at", date_90_days_ago).execute()
                logger.info(f"Deleted entries older than {autoexpire} days {date_90_days_ago} for set {self.set_name}; data: {data}")
            else:
                logger.error(f"Invalid autoexpire value: {autoexpire}")
                raise Exception(f"Invalid autoexpire value: {autoexpire}")

    def _table(self):
        return self.client.table(self.table_name)

    def add(self, value):
        """
        Add a value to the set. Returns True if the value was added, False if it already exists.
        """
        if not self.case_sensitive:
            value = value.lower()
        try:
            logger.info(f"Adding {value} to supaset {self.set_name}")
            if value in self:
                return False
            self._table().insert(
                {"value": value, "session_id": str(self.session_id), "set_name": self.set_name, "is_session_complete": False}).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to insert {value}, error: {e}")

    def remove(self, value):
        if not self.case_sensitive:
            value = value.lower()
        try:
            self._table().delete().eq("value", value).eq(
                "session_id", str(self.session_id)).eq("set_name", self.set_name).execute()
        except Exception as e:
            logger.error(f"Failed to remove {value}, error: {e}")

    def complete_session(self):
        try:
            self._table().update({"is_session_complete": True}).eq(
                "session_id", str(self.session_id)).eq("set_name", self.set_name).execute()
        except Exception as e:
            logger.error(f"Failed to complete session, error: {e}")


    def _cleanup_incomplete_sessions(self):
        try:
            self._table().delete().eq("is_session_complete",
                                                 False).eq("set_name", self.set_name).execute()
        except Exception as e:
            logger.error(
                f"Failed to delete incomplete session entries, error: {e}")

    def elements(self):
        try:
            data = self._table().select("value").eq("set_name", self.set_name).execute()
            return [item['value'] for item in data.data]
        except Exception as e:
            logger.error(f"Failed to retrieve values, error: {e}")
            
    def __contains__(self, value):
        if not self.case_sensitive:
            value = value.lower()
        logger.info(f"Checking if {value} is in supaset {self.set_name}")
        try:
            data = self._table().select("value").eq("set_name", self.set_name).eq("value", value).execute()
            return len(data.data) > 0
        except Exception as e:
            logger.error(f"Failed to retrieve values, error: {e}")
