import re

import pytest
from curl_cffi import requests

from leads.collect.fetch import (
    ATTEMPTS,
    TIMEOUT_SECONDS,
    USER_AGENT,
    Fetcher,
    FetchError,
    write_atomic,
)

URL = "https://example.lt/file.zip"
ZIP = b"PK\x03\x04"
WEB_PAGE = b"<!DOCTYPE html><title>Please wait</title>"


def test_session_has_browser_settings_our_user_agent_and_a_timeout(session):
    with Fetcher(offline=False):
        pass
    assert session.options == {
        "impersonate": "chrome",
        "headers": {"User-Agent": USER_AGENT},
        "timeout": TIMEOUT_SECONDS,
    }
    assert session.closed


def test_get_returns_the_body(session):
    session.reply(b"data")
    with Fetcher(offline=False) as fetcher:
        assert fetcher.get(URL) == b"data"
    assert session.requests == [("GET", URL, None, None)]


@pytest.mark.parametrize(
    "trouble",
    [{"status": 429}, {"status": 503}, requests.RequestsError("connection reset")],
    ids=["rate-limit", "server-error", "lost-connection"],
)
def test_get_retries_until_the_body_arrives(session, trouble):
    if isinstance(trouble, Exception):
        session.fail(trouble)
    else:
        session.reply(**trouble)
    session.reply(b"data")
    with Fetcher(offline=False) as fetcher:
        assert fetcher.get(URL) == b"data"
    assert len(session.requests) == 2
    assert session.waits == [2.0]


def test_get_backs_off_and_gives_up_after_the_last_attempt(session, caplog):
    for _ in range(ATTEMPTS):
        session.reply(status=503)
    with (
        Fetcher(offline=False) as fetcher,
        pytest.raises(FetchError, match=f"HTTP 503 after {ATTEMPTS} attempts"),
    ):
        fetcher.get(URL)
    assert len(session.requests) == ATTEMPTS
    assert session.waits == [2.0, 4.0, 8.0]  # none after the last attempt
    assert caplog.messages == [f"{URL}: HTTP 503; retrying"] * (ATTEMPTS - 1)


@pytest.mark.parametrize("status", [403, 204], ids=["refused", "no-content"])
def test_anything_but_ok_and_retryable_fails_at_once(session, status):
    session.reply(status=status)
    with (
        Fetcher(offline=False) as fetcher,
        pytest.raises(FetchError, match=rf"HTTP {status}$"),
    ):
        fetcher.get(URL)
    assert len(session.requests) == 1


def test_an_error_outside_the_request_is_not_retried(session):
    session.fail(ValueError("a bug, not a network problem"))
    with Fetcher(offline=False) as fetcher, pytest.raises(ValueError):
        fetcher.get(URL)
    assert (len(session.requests), session.waits) == (1, [])


def test_get_json_asks_for_json(session):
    session.reply(b'{"rows": 1}')
    with Fetcher(offline=False) as fetcher:
        assert fetcher.get_json(URL) == {"rows": 1}
    assert session.requests == [("GET", URL, {"Accept": "application/json"}, None)]


def test_post_json_sends_the_payload_with_extra_headers(session):
    session.reply(b'{"state": "done"}')
    with Fetcher(offline=False) as fetcher:
        answer = fetcher.post_json(URL, {"url": "x"}, {"Authorization": "Bearer key"})
    assert answer == {"state": "done"}
    headers = {"Accept": "application/json", "Authorization": "Bearer key"}
    assert session.requests == [("POST", URL, headers, {"url": "x"})]


def test_get_json_rejects_a_web_page(session):
    session.reply(WEB_PAGE)
    with (
        Fetcher(offline=False) as fetcher,
        pytest.raises(FetchError, match=re.escape(f"expected JSON, got {WEB_PAGE!r}")),
    ):
        fetcher.get_json(URL)


def test_offline_fetcher_never_sends_a_request(session):
    with (
        Fetcher(offline=True) as fetcher,
        pytest.raises(FetchError, match="only the current month can be fetched"),
    ):
        fetcher.get(URL)
    assert session.requests == []


def test_download_saves_the_file_once(session, tmp_path):
    target = tmp_path / "raw" / "file.zip"
    session.reply(ZIP + b"rest")
    with Fetcher(offline=False) as fetcher:
        assert fetcher.download(URL, target, ZIP) == target
        assert fetcher.download(URL, target, ZIP) == target
    assert target.read_bytes() == ZIP + b"rest"
    assert len(session.requests) == 1


def test_download_uses_a_file_saved_by_hand_even_offline(session, tmp_path):
    target = tmp_path / "file.zip"
    target.write_bytes(ZIP + b"by hand")
    with Fetcher(offline=True) as fetcher:
        assert fetcher.download(URL, target, ZIP) == target
    assert session.requests == []


def test_download_refuses_a_web_page_saved_by_hand(session, tmp_path):
    target = tmp_path / "file.zip"
    target.write_bytes(WEB_PAGE)
    with (
        Fetcher(offline=True) as fetcher,
        pytest.raises(FetchError, match=re.escape(f"{target} (replace it): expected {ZIP!r}")),
    ):
        fetcher.download(URL, target, ZIP)


@pytest.mark.parametrize("page", [WEB_PAGE, WEB_PAGE + ZIP], ids=["page", "signature-later"])
def test_download_rejects_a_web_page_and_saves_nothing(session, tmp_path, page):
    session.reply(page)
    with (
        Fetcher(offline=False) as fetcher,
        pytest.raises(FetchError, match=re.escape(f"expected {ZIP!r} at the start, got {page!r}")),
    ):
        fetcher.download(URL, tmp_path / "file.zip", ZIP)
    assert list(tmp_path.iterdir()) == []


def test_failed_download_says_where_to_save_the_file_by_hand(session, tmp_path):
    target = tmp_path / "file.zip"
    session.reply(status=404)
    with (
        Fetcher(offline=False) as fetcher,
        pytest.raises(FetchError, match=re.escape(f"downloaded by hand as {target}")),
    ):
        fetcher.download(URL, target, ZIP)


def test_write_atomic_replaces_an_older_file(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_bytes(b"old")
    write_atomic(path, [b"new"])
    assert [p.name for p in tmp_path.iterdir()] == ["rows.jsonl"]
    assert path.read_bytes() == b"new"


def test_write_atomic_leaves_nothing_when_producing_the_chunks_fails(tmp_path):
    def chunks():
        yield b"first part"
        raise FetchError("second part failed")

    with pytest.raises(FetchError):
        write_atomic(tmp_path / "rows.jsonl", chunks())
    assert list(tmp_path.iterdir()) == []
