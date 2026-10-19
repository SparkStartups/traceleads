"""HTTP downloads with retries and a check that each response is the file asked for."""

import json
import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Self

from curl_cffi import requests

log = logging.getLogger(__name__)

USER_AGENT = "leads (VMI lead-list research prototype)"
JSON_ACCEPT = {"Accept": "application/json"}  # a browser's Accept gets HTML from data.gov.lt
TIMEOUT_SECONDS = 300
ATTEMPTS = 4
BACKOFF_SECONDS = 2.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
SNIPPET = 80  # bytes of a wrong answer quoted in its error


class FetchError(Exception):
    """Raised when a file cannot be downloaded or is not the file asked for."""


class Fetcher:
    """An HTTP session shared by every source.

    Some sources serve their files only to browser-like clients, so the session uses a browser's
    network settings with the project's own User-Agent. An ``offline`` fetcher only accepts files
    that are already on disk: the sources publish their current state, so an earlier month can
    never be fetched again.
    """

    def __init__(self, *, offline: bool) -> None:
        self.offline = offline
        self._session = requests.Session(
            impersonate="chrome", headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._session.close()

    def get(self, url: str) -> bytes:
        return self._request(url, headers=None)

    def get_json(self, url: str) -> dict:
        return _parse_json(url, self._request(url, headers=JSON_ACCEPT))

    def _request(self, url: str, *, headers: dict[str, str] | None) -> bytes:
        """Return the body of ``url``, retrying rate limits, server errors and lost connections."""
        if self.offline:
            raise FetchError(f"{url}: not downloaded, and only the current month can be fetched")
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self._session.request("GET", url, headers=headers)
            except requests.RequestsError as exc:
                problem = f"{url}: {exc}"
            else:
                if response.status_code == 200:
                    return response.content
                problem = f"{url}: HTTP {response.status_code}"
                if response.status_code not in RETRY_STATUSES:
                    raise FetchError(problem)
            if attempt < ATTEMPTS:
                log.warning("%s; retrying", problem)
                time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
        raise FetchError(f"{problem} after {ATTEMPTS} attempts")

    def download(self, url: str, target: Path, signature: bytes) -> Path:
        """Save ``url`` as ``target`` unless it is already there (fetched earlier or by hand).

        The body, or the file already there, must start with ``signature``, so a web page is never
        taken for the file.
        """
        if target.exists():
            with target.open("rb") as file:
                _require(signature, file.read(SNIPPET), f"{target} (replace it)")
            return target
        try:
            content = self.get(url)
        except FetchError as exc:
            raise FetchError(f"{exc}; it can also be downloaded by hand as {target}") from exc
        _require(signature, content, url)
        write_atomic(target, [content])
        return target


def _require(signature: bytes, content: bytes, source: str) -> None:
    if not content.startswith(signature):
        raise FetchError(
            f"{source}: expected {signature!r} at the start, got {content[:SNIPPET]!r}"
        )


def _parse_json(url: str, content: bytes) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise FetchError(f"{url}: expected JSON, got {content[:SNIPPET]!r}") from exc


def write_atomic(path: Path, chunks: Iterable[bytes]) -> None:
    """Write ``chunks`` to ``path``; if producing them fails, nothing is left on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.part")
    try:
        with partial.open("wb") as file:
            file.writelines(chunks)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(path)
