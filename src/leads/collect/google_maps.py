"""Google Maps: the places on a rendered search results page."""

import re
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser, LexborNode

CLOSED = ("Visam laikui uždaryta", "Laikinai uždaryta")  # "uždaryta" alone is only "closed now"
NO_REVIEWS = "Nėra peržiūrų"  # shown instead of the rating when a place has no reviews
SNIPPET = 120  # characters of a card or link quoted when it fails to parse

_PLACE_ID = re.compile(r"!1s0x[0-9a-f]+:(0x[0-9a-f]+)")  # the second half is the place's CID
_COORDINATES = re.compile(r"!3d(-?[0-9.]+)!4d(-?[0-9.]+)")
_REVIEWS = re.compile(r"Atsiliepimų: ([\d\s]+)")
_ICON = re.compile(r"[\ue000-\uf8ff]")  # icon fonts draw their glyphs from the private-use area
# A house number, a street type ("g.", "pr.", ...) or the bare city: an address, not a category.
_ADDRESS = re.compile(r"\d|\b(g|pr|al|pl|a|skg|kel|tak)\.(\s|$)|^Vilnius$")


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
            raise ValueError(f"no place link in card {article.text()[:SNIPPET]!r}")
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
        raise ValueError(f"no {pattern.pattern!r} in {text[:SNIPPET]!r}")
    return match


def _review_count(article: LexborNode) -> int:
    rating = article.css_first('span[role="img"][aria-label*="Atsiliepimų"]')
    if rating is None:
        if NO_REVIEWS in article.text():
            return 0
        raise ValueError(
            f"neither a review count nor {NO_REVIEWS!r} in {article.text()[:SNIPPET]!r}"
        )
    return int(re.sub(r"\D", "", _find(_REVIEWS, rating.attributes["aria-label"])[1]))


def _category_and_address(article: LexborNode) -> tuple[str | None, str | None]:
    """Return the category and address from the line "category · accessibility icon · address"."""
    line = article.css_first("div.W4Efsd > div.W4Efsd")
    if line is None:
        raise ValueError(f"no detail line in card {article.text()[:SNIPPET]!r}")
    parts = [text for node in line.iter() if node.tag == "span" and (text := _visible_text(node))]
    if len(parts) == 1 and _ADDRESS.search(parts[0]):  # a place without a category
        return None, parts[0]
    return parts[0], (parts[-1] if len(parts) > 1 else None)


def _visible_text(node: LexborNode) -> str:
    """Return a part of the detail line without its separator and icon glyphs."""
    return _ICON.sub("", node.text()).strip().lstrip("·").strip()
