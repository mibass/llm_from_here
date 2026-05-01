"""Resolve Supabase URL and API key from environment (canonical + legacy names)."""

from __future__ import annotations

import os


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
