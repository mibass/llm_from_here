"""Resolve Supabase URL and API key from environment (canonical + legacy names)."""

from __future__ import annotations

import os

DEFAULT_SUPABASE_TIMEOUT_SEC = 30.0


def create_supabase_client(*, timeout_sec: float = DEFAULT_SUPABASE_TIMEOUT_SEC):
    """Create a Supabase client whose postgrest calls are bounded by a timeout.

    Without a timeout, a dropped/half-closed postgrest connection can leave the
    event loop waiting in ``kevent`` forever, hanging the whole pipeline (observed
    in prod ShowRunner runs at SupaSet/SupaQueue writes). Bound the postgrest
    requests so they raise instead of deadlocking.
    """
    from supabase import ClientOptions, create_client

    url, key = require_supabase_credentials()
    return create_client(
        url,
        key,
        options=ClientOptions(postgrest_client_timeout=timeout_sec),
    )


def get_supabase_url() -> str | None:
    return os.getenv("SUPABASE_URL") or os.getenv("SUPASET_URL")


def get_supabase_service_role_key() -> str | None:
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_API_KEY")
        or os.getenv("SUPASET_KEY")
    )


def require_supabase_credentials() -> tuple[str, str]:
    url = get_supabase_url()
    key = get_supabase_service_role_key()
    if not url or not key:
        raise ValueError(
            "Missing Supabase credentials: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
            "(or legacy SUPASET_URL and SUPASET_KEY)."
        )
    return url, key
