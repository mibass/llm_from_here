import pytest

from llm_from_here.plugins.guestSelection import _dedupe_preserve_order


def test_dedupe_preserve_order_strings():
    assert _dedupe_preserve_order(["a", "b", "a", "c"]) == ["a", "b", "c"]


def test_dedupe_preserve_order_coerces_non_string():
    assert _dedupe_preserve_order(["x", 1, "x"]) == ["x", "1"]
