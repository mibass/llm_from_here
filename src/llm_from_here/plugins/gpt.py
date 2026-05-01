"""Deprecated compatibility shim.

Prefer ``from llm_from_here.llm_session import LlmSession``.
"""

from llm_from_here.llm_session import LlmSession

ChatApp = LlmSession

__all__ = ["ChatApp", "LlmSession"]
