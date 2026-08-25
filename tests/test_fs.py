from __future__ import annotations

from screenwright.fs import atomic_write_text


def test_atomic_write_text_writes_content(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello")
    assert target.read_text() == "hello"


def test_atomic_write_text_leaves_no_stray_temp_file(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello")
    leftovers = [p for p in tmp_path.iterdir() if p != target]
    assert leftovers == []


def test_atomic_write_text_preserves_old_content_on_failure(tmp_path, monkeypatch):
    # A process killed mid-write (or any failure before the atomic replace)
    # must never leave the real target file partially overwritten — the old
    # content (or nothing, if it didn't exist yet) must still be there,
    # exactly like before the call started.
    target = tmp_path / "out.txt"
    target.write_text("original content")

    def broken_replace(_src, _dst):
        raise OSError("simulated failure during os.replace")

    monkeypatch.setattr("screenwright.fs.os.replace", broken_replace)

    try:
        atomic_write_text(target, "new content that should never land")
    except OSError:
        pass

    assert target.read_text() == "original content"
    leftovers = [p for p in tmp_path.iterdir() if p != target]
    assert leftovers == []


def test_atomic_write_text_overwrites_existing_content(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "first")
    atomic_write_text(target, "second")
    assert target.read_text() == "second"
