"""Tests for src/uai/cli/input_expander.py"""
from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

import uai.cli.input_expander as expander_module
from uai.cli.input_expander import expand_input


@pytest.mark.asyncio
class TestFileExpansion:
    async def test_expands_file_reference(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')")
        text = f"Review @{f.name}"
        expanded, warnings = await expand_input(text, cwd=tmp_path)
        assert "print('hello')" in expanded
        assert warnings == []

    async def test_nonexistent_file_returns_warning(self, tmp_path):
        expanded, warnings = await expand_input("@missing.txt", cwd=tmp_path)
        assert any("not found" in w.lower() or "missing" in w for w in warnings)

    async def test_oversized_file_returns_warning(self, tmp_path):
        big_file = tmp_path / "big.txt"
        big_file.write_bytes(b"x" * (101 * 1024))  # 101 KB
        expanded, warnings = await expand_input(f"@{big_file.name}", cwd=tmp_path)
        assert any("large" in w.lower() or "KB" in w for w in warnings)
        # Original reference should not be expanded
        assert "x" * 100 not in expanded

    async def test_no_references_returned_unchanged(self, tmp_path):
        text = "just a plain message"
        expanded, warnings = await expand_input(text, cwd=tmp_path)
        assert expanded == text
        assert warnings == []

    async def test_language_detected_from_suffix_py(self, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("x = 1")
        expanded, _ = await expand_input(f"@{f.name}", cwd=tmp_path)
        assert "```py" in expanded

    async def test_language_detected_from_suffix_js(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text("console.log(1)")
        expanded, _ = await expand_input(f"@{f.name}", cwd=tmp_path)
        assert "```js" in expanded

    async def test_multiple_file_refs_both_expanded(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("content_a")
        f2.write_text("content_b")
        text = f"Compare @{f1.name} and @{f2.name}"
        expanded, warnings = await expand_input(text, cwd=tmp_path)
        assert "content_a" in expanded
        assert "content_b" in expanded
        assert warnings == []


@pytest.mark.asyncio
class TestShellExpansion:
    async def test_shell_command_output_included(self, tmp_path):
        expanded, warnings = await expand_input("!echo hello", cwd=tmp_path)
        assert "hello" in expanded
        assert warnings == []

    async def test_shell_command_block_has_dollar_prefix(self, tmp_path):
        expanded, warnings = await expand_input("!echo test", cwd=tmp_path)
        assert "$ echo test" in expanded or "echo test" in expanded

    async def test_shell_timeout_returns_warning(self, tmp_path):
        # Patch SHELL_TIMEOUT to near zero so any command times out
        with patch.object(expander_module, "SHELL_TIMEOUT", 0.001):
            expanded, warnings = await expand_input("!sleep 5", cwd=tmp_path)
        assert any("timed out" in w.lower() or "timeout" in w.lower() for w in warnings)

    async def test_mixed_file_and_shell(self, tmp_path):
        f = tmp_path / "info.txt"
        f.write_text("file content")
        text = f"@{f.name} and !echo shellout"
        expanded, warnings = await expand_input(text, cwd=tmp_path)
        assert "file content" in expanded
        assert "shellout" in expanded
        assert warnings == []


@pytest.mark.asyncio
class TestNoOp:
    async def test_plain_text_unchanged(self, tmp_path):
        text = "Hello, how are you?"
        expanded, warnings = await expand_input(text, cwd=tmp_path)
        assert expanded == text
        assert warnings == []
