"""Google Maps: places found by category keyword and Vilnius eldership, rendered by Oxylabs."""

import json
import logging
import os
import re
import tempfile
import unicodedata
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

import duckdb
from selectolax.lexbor import LexborHTMLParser, LexborNode

from leads.collect.fetch import Fetcher, FetchError, write_atomic
from leads.collect.source import RawFile, Source
from leads.config import CATEGORIES, CITY, ELDERSHIPS, RENDER_CAP

log = logging.getLogger(__name__)

OXYLABS_URL = "https://webapi.oxylabs.io/v1/scrape/google"
API_KEY_VARIABLE = "OXYLABS_API_KEY"
SEARCH_URL = "https://www.google.com/maps/search/{query}?hl=lt"
RENDER_ATTEMPTS = 5  # about one render in four comes back unrendered (October 2026)
# Google Maps' main panel: rendered for a results list and for the single place Google opens when
# one place clearly matches, but missing from the bare page a failed render returns.
RENDERED = 'role="main"'
# The snapshot's columns: a card's fields, then where it was found.
COLUMNS = {
    "cid": "UBIGINT",
    "name": "VARCHAR",
    "google_category": "VARCHAR",
    "address": "VARCHAR",
    "latitude": "DOUBLE",
    "longitude": "DOUBLE",
    "review_count": "INTEGER",
    "closed": "BOOLEAN",
    "category": "VARCHAR",
    "query": "VARCHAR",
    "file": "VARCHAR",
    "fetched_on": "DATE",
}
CLOSED = ("Visam laikui uždaryta", "Laikinai uždaryta")  # "uždaryta" alone is only "closed now"
NO_REVIEWS = "Nėra peržiūrų"  # shown instead of the rating when a place has no reviews
SNIPPET_CHARS = 120  # of a card or link, quoted when it fails to parse

_PLACE_ID = re.compile(r"!1s0x[0-9a-f]+:(0x[0-9a-f]+)")  # the second half is the place's CID
_COORDINATES = re.compile(r"!3d(-?[0-9.]+)!4d(-?[0-9.]+)")
_REVIEWS = re.compile(r"Atsiliepimų: ([\d\s]+)")
_ICON = re.compile(r"[\ue000-\uf8ff]")  # icon fonts draw their glyphs from the private-use area
# A house number, a street type ("g.", "pr.", ...) or the bare city: an address, not a category.
_ADDRESS = re.compile(rf"\d|\b(g|pr|al|pl|a|skg|kel|tak)\.(\s|$)|^{CITY}$")


@dataclass(frozen=True)
class Card:
    cid: int
    name: str
    google_category: str | None
    address: str | None
    latitude: float
    longitude: float
    review_count: int
    closed: bool


@dataclass(frozen=True)
class Query:
    category: str
    keyword: str
    eldership: str

    @property
    def text(self) -> str:
        return f"{self.keyword} {self.eldership} {CITY}"

    @property
    def url(self) -> str:
        return SEARCH_URL.format(query=quote(self.text))

    @property
    def file_name(self) -> str:
        ascii_text = unicodedata.normalize("NFKD", self.text).encode("ascii", "ignore").decode()
        return re.sub(r"\W+", "-", ascii_text.lower()) + ".html"


QUERIES = tuple(
    Query(category.key, keyword, eldership)
    for category in CATEGORIES
    for keyword in category.keywords
    for eldership in ELDERSHIPS
)


@dataclass
class Renderer:
    """Renders pages through Oxylabs' Web API, at most ``RENDER_CAP`` times in one run."""

    fetcher: Fetcher
    renders: int = 0

    def render(self, url: str) -> str:
        """Return the page at ``url`` once its JavaScript ran; a render can come back without."""
        key = os.environ.get(API_KEY_VARIABLE)
        if not key and not self.fetcher.offline:  # offline, the fetcher says why it cannot render
            raise FetchError(f"{url}: set {API_KEY_VARIABLE} (see .env.example) to render it")
        payload = {"url": url, "run_js": True, "output": ["html"]}
        headers = {"Authorization": f"Bearer {key}"}
        for attempt in range(1, RENDER_ATTEMPTS + 1):
            if self.renders == RENDER_CAP:
                raise FetchError(f"{url}: the {RENDER_CAP} renders allowed in one run are spent")
            self.renders += 1
            html = self.fetcher.post_json(OXYLABS_URL, payload, headers)["results"][0]["html"]
            if RENDERED in html:
                return html
            log.warning("%s: came back unrendered (attempt %d)", url, attempt)
        raise FetchError(f"{url}: came back unrendered {RENDER_ATTEMPTS} times")


class GoogleMaps(Source):
    name = "google_maps"
    period_column = "fetched_on"

    def fetch(self, fetcher: Fetcher, raw_dir: Path, month: date) -> list[RawFile]:
        """Return one rendered results page per query, saved as HTML unless it is already there."""
        renderer = Renderer(fetcher)
        files = []
        for query in QUERIES:
            path = raw_dir / query.file_name
            if not path.exists():
                write_atomic(path, [renderer.render(query.url).encode()])
            files.append(RawFile(query.url, path))
        return files

    @contextmanager
    def rows(
        self, con: duckdb.DuckDBPyConnection, files: list[RawFile]
    ) -> Generator[duckdb.DuckDBPyRelation]:
        """Yield every page's cards, written to a JSON-lines file and read with explicit types."""
        queries = {query.file_name: query for query in QUERIES}
        with tempfile.TemporaryDirectory() as tmp:
            cards = Path(tmp) / "cards.jsonl"
            with cards.open("w", encoding="utf-8") as out:
                for file in files:
                    query = queries[file.path.name]
                    found = {
                        "category": query.category,
                        "query": query.text,
                        "file": file.path.name,
                        "fetched_on": file.fetched_at.date().isoformat(),
                    }
                    try:
                        page = parse_cards(file.path.read_text(encoding="utf-8"))
                    except ValueError as exc:
                        raise FetchError(f"{file.path}: {exc}") from exc
                    out.writelines(json.dumps(asdict(card) | found) + "\n" for card in page)
            yield con.sql(
                f"SELECT {', '.join(COLUMNS)} FROM read_json(?, format = 'newline_delimited', "
                "columns = ?)",
                params=[str(cards), COLUMNS],
            )


def parse_cards(html: str) -> list[Card]:
    """Return the places in a rendered results list, each once.

    A sponsored card can repeat a place; the place's first card is kept. A single-place page has
    no results list, so it gives no places. Markup the parser does not know raises
    ``ValueError`` rather than giving a half-parsed place.
    """
    cards: dict[int, Card] = {}
    for article in LexborHTMLParser(html).css('div[role="feed"] div[role="article"]'):
        link = article.css_first("a.hfpxzc[href][aria-label]")
        if link is None:
            raise ValueError(f"no place link in card {article.text()[:SNIPPET_CHARS]!r}")
        href = link.attributes["href"]
        cid = int(_find(_PLACE_ID, href)[1], 16)
        if cid in cards:
            continue
        coordinates = _find(_COORDINATES, href)
        google_category, address = _category_and_address(article)
        cards[cid] = Card(
            cid=cid,
            name=link.attributes["aria-label"],
            google_category=google_category,
            address=address,
            latitude=float(coordinates[1]),
            longitude=float(coordinates[2]),
            review_count=_review_count(article),
            closed=any(status in article.text() for status in CLOSED),
        )
    return list(cards.values())


def _find(pattern: re.Pattern[str], text: str) -> re.Match[str]:
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"no {pattern.pattern!r} in {text[:SNIPPET_CHARS]!r}")
    return match


def _review_count(article: LexborNode) -> int:
    rating = article.css_first('span[role="img"][aria-label*="Atsiliepimų"]')
    if rating is None:
        if NO_REVIEWS in article.text():
            return 0
        raise ValueError(
            f"neither a review count nor {NO_REVIEWS!r} in {article.text()[:SNIPPET_CHARS]!r}"
        )
    return int(re.sub(r"\D", "", _find(_REVIEWS, rating.attributes["aria-label"])[1]))


def _category_and_address(article: LexborNode) -> tuple[str | None, str | None]:
    """Return the category and address from the line "category · accessibility icon · address"."""
    line = article.css_first("div.W4Efsd > div.W4Efsd")
    if line is None:
        raise ValueError(f"no detail line in card {article.text()[:SNIPPET_CHARS]!r}")
    parts = [text for node in line.iter() if node.tag == "span" and (text := _visible_text(node))]
    if len(parts) == 1 and _ADDRESS.search(parts[0]):  # a place without a category
        return None, parts[0]
    return parts[0], (parts[-1] if len(parts) > 1 else None)


def _visible_text(node: LexborNode) -> str:
    """Return a part of the detail line without its separator and icon glyphs."""
    return _ICON.sub("", node.text()).strip().lstrip("·").strip()
