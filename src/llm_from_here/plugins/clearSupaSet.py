"""
Simple helper pluging to clear a supaset.
"""

from llm_from_here.supaSet import clear_supaset

class ClearSupaSet:
    def __init__(self, params, global_params, plugin_instance_name):
        self.params = params
        self.global_params = global_params
        self.plugin_instance_name = plugin_instance_name

    def execute(self):
        set_name = self.params['set_name']
        clear_supaset(set_name)
        return None