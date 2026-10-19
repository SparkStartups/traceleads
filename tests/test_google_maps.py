from collections.abc import Callable
from pathlib import Path

import pytest
from selectolax.lexbor import LexborHTMLParser, LexborNode

from leads.collect.google_maps import Card, parse_cards

FIXTURES = Path(__file__).parent / "fixtures"
LIST_PAGE = (FIXTURES / "maps_list.html").read_text(encoding="utf-8")  # a real render, trimmed
PLACE_PAGE = (FIXTURES / "maps_place.html").read_text(encoding="utf-8")  # one place, no list


def node(html: str, selector: str) -> LexborNode:
    return LexborHTMLParser(html).css_first(selector)


def edited(edits: dict[str, Callable[[LexborNode], None]]) -> str:
    """Return the results list with the cards of the named places changed."""
    page = LexborHTMLParser(LIST_PAGE)
    for card in page.css('div[role="feed"] div[role="article"]'):
        edit = edits.get(card.css_first("a.hfpxzc").attributes["aria-label"])
        if edit:
            edit(card)
    return page.html


def places(html: str) -> dict[str, Card]:
    return {card.name: card for card in parse_cards(html)}


def test_a_results_list_gives_each_place_with_its_details():
    cards = parse_cards(LIST_PAGE)
    assert len(cards) == len({card.cid for card in cards}) == 20
    assert places(LIST_PAGE)["Cozy"] == Card(
        cid=5596741140976187341,
        name="Cozy",
        google_category="Kavinė",
        address="Dominikonų g. 10",
        latitude=54.6813011,
        longitude=25.2852459,
        review_count=1815,
        closed=False,  # "Uždaroma 01" is its closing hour, not a closure
    )
    grey = places(LIST_PAGE)["Grey"]  # the accessibility icon between them is skipped
    assert (grey.google_category, grey.address) == ("Lietuvių restoranas", "Pilies g. 2")


def test_a_single_place_page_gives_no_places():
    assert parse_cards(PLACE_PAGE) == []


def test_a_review_count_with_a_thousands_separator():
    def rating(card: LexborNode) -> None:
        card.css_first('span[role="img"]').attrs["aria-label"] = "4,5 žvaigžd. Atsiliepimų: 1 815"

    assert places(edited({"Cozy": rating}))["Cozy"].review_count == 1815


def test_a_place_without_reviews_counts_zero():
    def no_reviews(card: LexborNode) -> None:
        card.css_first('span[role="img"]').replace_with(node("<span>Nėra peržiūrų</span>", "span"))

    assert places(edited({"Cozy": no_reviews}))["Cozy"].review_count == 0


@pytest.mark.parametrize(
    ("status", "closed"),
    [
        ("Laikinai uždaryta", True),  # temporarily
        ("Visam laikui uždaryta", True),  # for good
        ("Uždaryta ⋅ Atidaroma 09", False),  # only now
        ("Netrukus bus uždaryta", False),  # closing soon
    ],
)
def test_only_a_closure_marks_a_place_closed(status, closed):
    def hours(card: LexborNode) -> None:
        card.css("div.W4Efsd > div.W4Efsd")[1].replace_with(node(f"<div>{status}</div>", "div"))

    assert places(edited({"Cozy": hours}))["Cozy"].closed is closed


def test_a_repeated_place_keeps_its_first_card():
    def repeat_before(card: LexborNode) -> None:
        first = node(card.html, 'div[role="article"]')
        first.css_first('span[role="img"]').attrs["aria-label"] = "4,8 žvaigžd. Atsiliepimų: 9"
        card.insert_before(first)

    html = edited({"Moss": repeat_before})
    assert len(parse_cards(html)) == 20
    assert places(html)["Moss"].review_count == 9


def detail_spans(card: LexborNode) -> list[LexborNode]:
    """Return the parts of a card's detail line: category, accessibility icon, address."""
    return card.css("div.W4Efsd > div.W4Efsd > span")


@pytest.mark.parametrize(
    ("only", "category", "address"),
    [
        ("Pilies g. 2", None, "Pilies g. 2"),
        ("Vokiečių 2", None, "Vokiečių 2"),  # a number but no street type
        ("Didžioji g.", None, "Didžioji g."),  # a street type but no number
        ("Vilnius", None, "Vilnius"),  # only the city
        ("Kavinė", "Kavinė", None),  # only the category
    ],
)
def test_a_detail_line_with_one_part(only, category, address):
    def one_part(card: LexborNode) -> None:
        first, *others = detail_spans(card)[:2]
        first.replace_with(node(f"<span>{only}</span>", "span"))
        for other in others:
            other.decompose()

    moss = places(edited({"Moss": one_part}))["Moss"]
    assert (moss.google_category, moss.address) == (category, address)


def test_the_accessibility_icon_is_neither_category_nor_address():
    def drop(index: int) -> Callable[[LexborNode], None]:
        return lambda card: detail_spans(card)[index].decompose()

    found = places(edited({"Grey": drop(0), "Amandus": drop(2)}))
    assert (found["Grey"].google_category, found["Grey"].address) == (None, "Pilies g. 2")
    assert (found["Amandus"].google_category, found["Amandus"].address) == ("Restoranas", None)


def without_link(card: LexborNode) -> None:
    card.css_first("a.hfpxzc").decompose()


def without_place_id(card: LexborNode) -> None:
    card.css_first("a.hfpxzc").attrs["href"] = "/maps/place/Cozy"


def without_rating(card: LexborNode) -> None:
    card.css_first('span[role="img"]').decompose()


def without_detail_lines(card: LexborNode) -> None:
    for line in card.css("div.W4Efsd > div.W4Efsd"):
        line.decompose()


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (without_link, "no place link"),
        (without_place_id, "no '!1s0x"),
        (without_rating, "neither a review count"),
        (without_detail_lines, "no detail line"),
    ],
)
def test_unknown_markup_stops_the_parse(edit, message):
    with pytest.raises(ValueError, match=message):
        parse_cards(edited({"Cozy": edit}))
