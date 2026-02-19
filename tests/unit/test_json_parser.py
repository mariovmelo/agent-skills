"""Tests for robust JSON extraction."""
from __future__ import annotations
from uai.utils.json_parser import extract_json, is_valid_json


def test_plain_json():
    result = extract_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_json_in_markdown_fence():
    text = '```json\n{"status": "ok", "result": 42}\n```'
    result = extract_json(text)
    assert result == {"status": "ok", "result": 42}


def test_json_embedded_in_prose():
    text = 'Here is the result: {"status": "OK", "count": 5} end of message'
    result = extract_json(text)
    assert result is not None
    assert result["status"] == "OK"


def test_json_array():
    result = extract_json('[1, 2, 3]')
    assert result == [1, 2, 3]


def test_invalid_json_returns_none():
    result = extract_json("this is not json at all")
    assert result is None


def test_is_valid_json_true():
    assert is_valid_json('{"a": 1}')


def test_is_valid_json_false():
    assert not is_valid_json("not json")


def test_nested_json():
    text = '```\n{"outer": {"inner": [1, 2, 3]}}\n```'
    result = extract_json(text)
    assert result["outer"]["inner"] == [1, 2, 3]
