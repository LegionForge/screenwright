from __future__ import annotations

from pathlib import Path

import pytest

from screenwright.mcp_server import _resolve_capture_path


def test_resolve_capture_path_accepts_safe_name(tmp_path):
    result = _resolve_capture_path(tmp_path, "homepage-full")
    assert result == (tmp_path / "homepage-full.png").resolve()


@pytest.mark.parametrize(
    "malicious_name",
    [
        "../../../../etc/passwd",
        "..",
        "foo/../../bar",
        "/etc/passwd",
        "a/b",
    ],
)
def test_resolve_capture_path_rejects_traversal(tmp_path, malicious_name):
    with pytest.raises(ValueError):
        _resolve_capture_path(tmp_path, malicious_name)


def test_resolve_capture_path_stays_inside_output_root(tmp_path):
    result = _resolve_capture_path(tmp_path, "safe-name")
    assert Path(result).resolve().is_relative_to(tmp_path.resolve())
