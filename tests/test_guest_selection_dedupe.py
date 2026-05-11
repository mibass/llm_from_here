from llm_from_here.plugins.guestSelection import (
    _dedupe_guest_rows_by_name,
    _dedupe_preserve_order,
)


def test_dedupe_preserve_order_strings():
    assert _dedupe_preserve_order(["a", "b", "a", "c"]) == ["a", "b", "c"]


def test_dedupe_preserve_order_coerces_non_string():
    assert _dedupe_preserve_order(["x", 1, "x"]) == ["x", "1"]


def test_dedupe_guest_rows_by_name_keeps_first_category():
    rows = [
        {"guest_name": "Pat", "guest_category": "music"},
        {"guest_name": "Pat", "guest_category": "music"},
        {"guest_name": "Sam", "guest_category": "comedy"},
    ]
    assert _dedupe_guest_rows_by_name(rows) == [
        {"guest_name": "Pat", "guest_category": "music"},
        {"guest_name": "Sam", "guest_category": "comedy"},
    ]
