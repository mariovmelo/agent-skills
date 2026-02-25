"""Tests for src/uai/core/project_context.py"""
from __future__ import annotations
import pytest
from pathlib import Path

from uai.core.project_context import find_project_config, find_project_instructions


class TestFindProjectInstructions:
    def test_finds_uai_md_in_cwd(self, tmp_path):
        uai_md = tmp_path / "UAI.md"
        uai_md.write_text("# Instructions\nDo something.")
        result = find_project_instructions(cwd=tmp_path)
        assert result is not None
        assert "Instructions" in result

    def test_finds_uai_md_in_parent(self, tmp_path):
        # Place UAI.md in parent, start search from subdir
        uai_md = tmp_path / "UAI.md"
        uai_md.write_text("parent instructions")
        subdir = tmp_path / "sub" / "deep"
        subdir.mkdir(parents=True)
        result = find_project_instructions(cwd=subdir)
        assert result is not None
        assert "parent instructions" in result

    def test_returns_none_when_no_file(self, tmp_path):
        # Use tmp_path as a standalone dir with no UAI.md anywhere above
        # We need a directory deep enough that no UAI.md exists in parents up to home
        # Use a fresh temp directory which has no UAI.md
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        # We can't guarantee no UAI.md exists above tmp_path up to home,
        # but tmp_path itself has no UAI.md
        # Patch home to be tmp_path so the search stops early
        import unittest.mock as mock
        with mock.patch("uai.core.project_context.Path.home", return_value=tmp_path):
            result = find_project_instructions(cwd=deep)
        assert result is None

    def test_finds_dot_uai_instructions(self, tmp_path):
        dot_uai = tmp_path / ".uai"
        dot_uai.mkdir()
        instructions = dot_uai / "instructions.md"
        instructions.write_text("dot uai instructions")
        result = find_project_instructions(cwd=tmp_path)
        assert result is not None
        assert "dot uai instructions" in result

    def test_uai_md_takes_precedence_over_dot_uai(self, tmp_path):
        # Both exist: UAI.md (first candidate) should win
        (tmp_path / "UAI.md").write_text("primary")
        dot_uai = tmp_path / ".uai"
        dot_uai.mkdir()
        (dot_uai / "instructions.md").write_text("secondary")
        result = find_project_instructions(cwd=tmp_path)
        assert result == "primary"

    def test_returns_file_content_as_string(self, tmp_path):
        (tmp_path / "UAI.md").write_text("hello world")
        result = find_project_instructions(cwd=tmp_path)
        assert isinstance(result, str)
        assert result == "hello world"


class TestFindProjectConfig:
    def test_finds_config_in_cwd(self, tmp_path):
        dot_uai = tmp_path / ".uai"
        dot_uai.mkdir()
        config = dot_uai / "config.yaml"
        config.write_text("defaults:\n  provider: gemini\n")
        result = find_project_config(cwd=tmp_path)
        assert result is not None
        assert result == config

    def test_finds_config_in_parent(self, tmp_path):
        dot_uai = tmp_path / ".uai"
        dot_uai.mkdir()
        config = dot_uai / "config.yaml"
        config.write_text("defaults:\n  provider: ollama\n")
        subdir = tmp_path / "subproject"
        subdir.mkdir()
        result = find_project_config(cwd=subdir)
        assert result is not None
        assert result == config

    def test_returns_none_when_no_config(self, tmp_path):
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        import unittest.mock as mock
        with mock.patch("uai.core.project_context.Path.home", return_value=tmp_path):
            result = find_project_config(cwd=deep)
        assert result is None

    def test_returns_path_object(self, tmp_path):
        dot_uai = tmp_path / ".uai"
        dot_uai.mkdir()
        config = dot_uai / "config.yaml"
        config.write_text("")
        result = find_project_config(cwd=tmp_path)
        assert isinstance(result, Path)
