"""Robust JSON extraction from AI output.

AI models often embed JSON inside prose. This module extracts and validates JSON
even when surrounded by markdown code blocks or explanatory text.
"""
from __future__ import annotations
import json
import re


def extract_json(text: str) -> dict | list | None:
    """
    Try to extract a JSON object or array from arbitrary text.
    Returns parsed object or None if no valid JSON found.
    """
    # 1. Try parsing the whole text first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown code fences: ```json ... ```
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Find the first {...} or [...] span
    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    return None


def is_valid_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False
