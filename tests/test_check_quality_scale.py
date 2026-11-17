"""Exercise the archive cache and download failures without network access."""

from email.message import Message
from io import BytesIO
from pathlib import Path
import tarfile
import time
from unittest.mock import Mock, call
from urllib.error import HTTPError
import urllib.request

import pytest

from script import check_quality_scale

VERSION = "2026.11.0"
URL = f"https://github.com/home-assistant/core/archive/refs/tags/{VERSION}.tar.gz"


def archive_for(version: str) -> bytes:
    """Create a source archive whose contents identify the release."""
    data = BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        core = tarfile.TarInfo(f"core-{version}/.strict-typing")
        content = version.encode()
        core.size = len(content)
        archive.addfile(core, BytesIO(content))
    return data.getvalue()


def test_reuse_pristine_archive_only_for_exact_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse downloaded bytes while extracting a new copy for each check."""
    beta = "2026.11.0b1"
    stable_archive = archive_for(VERSION)
    beta_archive = archive_for(beta)
    download = Mock(side_effect=[BytesIO(stable_archive), BytesIO(beta_archive)])
    monkeypatch.setattr(urllib.request, "urlopen", download)
    cache = tmp_path / "cache"

    first_tree = tmp_path / "first"
    check_quality_scale.extract_core(VERSION, first_tree, cache)
    download.assert_called_once_with(URL, timeout=60)
    assert (first_tree / ".strict-typing").read_text(encoding="utf-8") == VERSION
    cached = cache / "core-2026.11.0.tar.gz"
    assert cached.read_bytes() == stable_archive

    (first_tree / ".strict-typing").write_text(
        "modified by the checker", encoding="utf-8"
    )
    second_tree = tmp_path / "second"
    check_quality_scale.extract_core(VERSION, second_tree, cache)
    download.assert_called_once_with(URL, timeout=60)
    assert (second_tree / ".strict-typing").read_text(encoding="utf-8") == VERSION

    beta_tree = tmp_path / "beta"
    check_quality_scale.extract_core(beta, beta_tree, cache)
    assert download.call_args_list == [
        call(URL, timeout=60),
        call(
            "https://github.com/home-assistant/core/archive/refs/tags/2026.11.0b1.tar.gz",
            timeout=60,
        ),
    ]
    assert (beta_tree / ".strict-typing").read_text(encoding="utf-8") == beta
    assert cached.read_bytes() == stable_archive
    assert (cache / "core-2026.11.0b1.tar.gz").read_bytes() == beta_archive


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (archive_for(VERSION)[:-1], "end-of-stream marker"),
        (archive_for("2026.11.0b1"), "expected all paths under core-2026.11.0/"),
    ],
    ids=["truncated-gzip-trailer", "wrong-release"],
)
def test_invalid_download_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: bytes, error: str
) -> None:
    """An extractable tar member does not make a damaged download cacheable."""
    download = Mock(return_value=BytesIO(data))
    monkeypatch.setattr(urllib.request, "urlopen", download)
    cache = tmp_path / "cache"

    with pytest.raises(SystemExit, match=f"Cannot extract Home Assistant .*{error}"):
        check_quality_scale.extract_core(VERSION, tmp_path / "source", cache)

    assert not list(cache.iterdir())


def http_error(status: int, retry_after: str | None) -> HTTPError:
    """Return a simulated server response with an optional retry header."""
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(URL, status, "test response", headers, BytesIO())


@pytest.mark.freeze_time("2026-11-17 19:30:00+00:00")
@pytest.mark.parametrize(
    ("responses", "waits", "error"),
    [
        ([(429, "Tue, 17 Nov 2026 19:30:03 GMT"), (503, "invalid")], [3, 2], None),
        ([(503, None), (502, None), (504, None)], [1, 2], 504),
        ([(429, "6 "), (503, "5")], [6], 503),
        ([(404, "1")], [], 404),
    ],
    ids=["recovery", "attempt-limit", "wait-limit", "permanent-error"],
)
def test_download_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    responses: list[tuple[int, str | None]],
    waits: list[int],
    error: int | None,
) -> None:
    """Retry transient errors within both limits and report the final HTTP error."""
    data = archive_for(VERSION)
    download = Mock(
        side_effect=[*(http_error(*response) for response in responses), BytesIO(data)]
    )
    sleep = Mock()
    monkeypatch.setattr(urllib.request, "urlopen", download)
    monkeypatch.setattr(time, "sleep", sleep)
    cache = tmp_path / "cache"
    tree = tmp_path / "source"

    if error is None:
        check_quality_scale.extract_core(VERSION, tree, cache)
        assert (tree / ".strict-typing").read_text(encoding="utf-8") == VERSION
        assert (cache / "core-2026.11.0.tar.gz").read_bytes() == data
    else:
        with pytest.raises(
            SystemExit, match=f"Cannot download Home Assistant .*HTTP Error {error}"
        ):
            check_quality_scale.extract_core(VERSION, tree, cache)
        assert not list(cache.iterdir())

    assert download.call_args_list == [call(URL, timeout=60)] * (
        len(responses) + (error is None)
    )
    assert sleep.call_args_list == [call(wait) for wait in waits]
