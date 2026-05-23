from llm_from_here.supaQueue import SupaQueue
from llm_from_here.supaSet import SupaSet
import llm_from_here.plugins.gpt as gpt
from llm_from_here.common import is_production_prefix
import random
import numpy as np
import logging

logger = logging.getLogger(__name__)


def _dedupe_preserve_order(names: list) -> list:
    seen: set[str] = set()
    out: list[str] = []
    for item in names:
        if not isinstance(item, str):
            item = str(item)
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _dedupe_guest_rows_by_name(guests: list) -> list:
    """Keep first occurrence per ``guest_name`` (episode roster uniqueness)."""
    seen: set[str] = set()
    out: list[dict] = []
    for g in guests:
        name = g.get("guest_name")
        if not isinstance(name, str):
            name = str(name)
        if name in seen:
            continue
        seen.add(name)
        out.append(g)
    return out


class GuestSelection:
    def __init__(self, params, global_results, plugin_instance_name, chat_app=None):
        self.chat_app = chat_app or gpt.ChatApp()
        self.params = params
        self.global_results = global_results
        self.plugin_instance_name = plugin_instance_name
        autoexpire = params.get("guests_used_autoexpire_days", 365)
        # Same supasets set_name as Intro (dev_guests_set / guests_set): people
        # already booked. ``supaqueue`` only tracks pending FIFO rows and deletes them when consumed,
        # so it never acted as a denylist across refills.
        self.guests_used = SupaSet(
            f"{is_production_prefix()}guests_set",
            autoexpire=autoexpire or None,
        )
        self._guest_names_this_run: list[str] = []

    def _sample_used_names(self, limit: int) -> list[str]:
        els = self.guests_used.elements()
        pool = els or []
        if len(pool) <= limit:
            return list(pool)
        return random.sample(pool, limit)

    def add_to_queue(self, sq, n, prompt):
        def fetch_list(extra_suffix: str = "") -> list[str]:
            raw = self.chat_app.enforce_list_response(
                prompt + extra_suffix, n, log_prompt=True
            )
            cleaned = _dedupe_preserve_order(raw)
            fresh = [x for x in cleaned if x not in self.guests_used]
            skipped = len(cleaned) - len(fresh)
            if skipped:
                logger.info(
                    "Skipping %s names already used on the show when enqueueing to %s",
                    skipped,
                    sq.queue_name,
                )
            return fresh

        fresh = fetch_list()
        if not fresh:
            excluded = self._sample_used_names(60)
            suffix = ""
            if excluded:
                suffix = (
                    "\n\nThese people have already been booked on the show; "
                    "do not include them — choose different real names only:\n"
                    + "\n".join(f"- {x}" for x in excluded)
                )
            logger.warning(
                "LLM returned only repeat guests for %s; retrying with exclusions",
                sq.queue_name,
            )
            fresh = fetch_list(suffix)
        if not fresh:
            raise RuntimeError(
                f"Could not enqueue any fresh guest names for queue {sq.queue_name}; "
                "try clearing guests_set supaset or widen prompts."
            )
        sq.enqueue(fresh)

    def _dequeue_fresh_guests(self, sq, n_needed: int) -> list[str]:
        """FIFO dequeue, dropping heads that are already in guests_used."""
        if n_needed <= 0:
            return []
        picked: list[str] = []
        max_ops = max(n_needed * 80, 400)
        ops = 0
        while len(picked) < n_needed and ops < max_ops:
            ops += 1
            batch = sq.dequeue(1)
            if not batch:
                break
            guest = batch[0]
            if guest in self.guests_used:
                logger.info(
                    "Removing repeat guest %r from queue %s (already used on the show)",
                    guest,
                    sq.queue_name,
                )
                continue
            picked.append(guest)
        if len(picked) < n_needed:
            logger.warning(
                "Queue %s: wanted %s fresh guests, got %s (exhausted or too many repeats)",
                sq.queue_name,
                n_needed,
                len(picked),
            )
        return picked

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
            selected_guests = self._dequeue_fresh_guests(supaqs[name], n)
            
            # repeat n_times with probability n_times_probability
            selected_guests = [
                guest
                for guest in selected_guests
                for _ in range(np.random.binomial(n_times, n_times_probability))
            ]

            for guest in selected_guests:
                guests.append({"guest_name": guest, "guest_category": name})

        if self.params.get("dedupe_guests_per_episode", True):
            guests = _dedupe_guest_rows_by_name(guests)

        self._guest_names_this_run = [g["guest_name"] for g in guests]
        supaqs["guests"] = guests
        return supaqs

    def finalize(self):
        """Record this episode's guests so future runs skip them."""
        names = getattr(self, "_guest_names_this_run", []) or []
        for name in names:
            self.guests_used.add(name)
        self.guests_used.complete_session()
        logger.info(
            "GuestSelection finalized guests_used with %s names for this episode",
            len(names),
        )
