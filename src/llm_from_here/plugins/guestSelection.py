from llm_from_here.supaQueue import SupaQueue
import llm_from_here.plugins.gpt as gpt
from llm_from_here.common import is_production_prefix
import os
import numpy as np
import logging

logger = logging.getLogger(__name__)


class GuestSelection:
    def __init__(self, params, global_results, plugin_instance_name, chat_app=None):
        self.chat_app = chat_app or gpt.ChatApp()
        self.params = params
        self.global_results = global_results
        self.plugin_instance_name = plugin_instance_name

    def add_to_queue(self, sq, n, prompt):
        # x = self.chat_app.enforce_list_response_consensus(prompt, n, log_prompt=True)
        x = self.chat_app.enforce_list_response(prompt, n, log_prompt=True)
        sq.enqueue(x)

    def get_params(self, guest_category):
        if not (name := guest_category.get("name")):
            raise Exception("Guest category name not specified.")
        if not (prompt := guest_category.get("prompt")):
            raise Exception("Guest category prompt not specified.")
        select_n = guest_category.get("select_n", 1)
        select_probability = guest_category.get("select_probability", 1)
        queue_size = guest_category.get("queue_size", 100)
        n_times = guest_category.get("n_times", 1)
        n_times_probability = guest_category.get("n_times_probability", 1)

        return (
            name,
            prompt,
            select_n,
            select_probability,
            queue_size,
            n_times,
            n_times_probability,
        )

    def execute(self):
        supaqs = {}
        guests = []
        # get guest_categories from params
        guest_categories = self.params.get("guest_categories", [])

        for guest_category in guest_categories:
            (
                name,
                prompt,
                select_n,
                select_probability,
                queue_size,
                n_times,
                n_times_probability,
            ) = self.get_params(guest_category)

            # ensure SupaQueue is initialized
            supaqs[name] = SupaQueue(queue_name=f"{is_production_prefix()}{name}")

            # make sure queue contains enough elements
            if (q_len := supaqs[name].length()) < select_n:
                logger.info(
                    f"Queue {name} is not long enough. Adding {queue_size} elements..."
                )
                self.add_to_queue(supaqs[name], queue_size, prompt)
                if (q_len := supaqs[name].length()) < select_n:
                    raise Exception(
                        f"Queue {name} is still not long enough; length is {q_len}. Aborting..."
                    )

            # select select_n elements with probability select_probability
            n = np.random.binomial(select_n, select_probability)
            selected_guests = supaqs[name].dequeue(n)
            
            # repeat n_times with probability n_times_probability
            selected_guests = [
                guest
                for guest in selected_guests
                for _ in range(np.random.binomial(n_times, n_times_probability))
            ]

            for guest in selected_guests:
                guests.append({"guest_name": guest, "guest_category": name})

        supaqs["guests"] = guests
        return supaqs
