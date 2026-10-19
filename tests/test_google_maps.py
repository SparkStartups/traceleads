import json
import os
from collections.abc import Callable
from datetime import UTC, datetime

import duckdb
import pytest
from selectolax.lexbor import LexborHTMLParser, LexborNode

from leads.collect import google_maps
from leads.collect.fetch import Fetcher, FetchError
from leads.collect.google_maps import (
    API_KEY_VARIABLE,
    OXYLABS_URL,
    QUERIES,
    RENDER_ATTEMPTS,
    RENDER_CAP,
    Card,
    GoogleMaps,
    Renderer,
    parse_cards,
)

Edits = dict[str, Callable[[LexborNode], None]]


def node(html: str, selector: str) -> LexborNode:
    return LexborHTMLParser(html).css_first(selector)


@pytest.fixture
def edited(list_page: str) -> Callable[[Edits], str]:
    """Return a function giving the results list with the cards of the named places changed."""

    def edit_cards(edits: Edits) -> str:
        page = LexborHTMLParser(list_page)
        for card in page.css('div[role="feed"] div[role="article"]'):
            edit = edits.get(card.css_first("a.hfpxzc").attributes["aria-label"])
            if edit:
                edit(card)
        return page.html

    return edit_cards


def places(html: str) -> dict[str, Card]:
    return {card.name: card for card in parse_cards(html)}


def test_a_results_list_gives_each_place_with_its_details(list_page):
    cards = parse_cards(list_page)
    assert len(cards) == len({card.cid for card in cards}) == 20
    assert places(list_page)["Cozy"] == Card(
        cid=5596741140976187341,
        name="Cozy",
        google_category="Kavinė",
        address="Dominikonų g. 10",
        latitude=54.6813011,
        longitude=25.2852459,
        review_count=1815,
        closed=False,  # "Uždaroma 01" is its closing hour, not a closure
    )
    grey = places(list_page)["Grey"]  # the accessibility icon between them is skipped
    assert (grey.google_category, grey.address) == ("Lietuvių restoranas", "Pilies g. 2")


def test_a_single_place_page_gives_no_places(place_page):
    assert parse_cards(place_page) == []


def test_a_review_count_with_a_thousands_separator(edited):
    def rating(card: LexborNode) -> None:
        card.css_first('span[role="img"]').attrs["aria-label"] = "4,5 žvaigžd. Atsiliepimų: 1 815"

    assert places(edited({"Cozy": rating}))["Cozy"].review_count == 1815


def test_a_place_without_reviews_counts_zero(edited):
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
def test_only_a_closure_marks_a_place_closed(edited, status, closed):
    def hours(card: LexborNode) -> None:
        card.css("div.W4Efsd > div.W4Efsd")[1].replace_with(node(f"<div>{status}</div>", "div"))

    assert places(edited({"Cozy": hours}))["Cozy"].closed is closed


def test_a_repeated_place_keeps_its_first_card(edited):
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
def test_a_detail_line_with_one_part(edited, only, category, address):
    def one_part(card: LexborNode) -> None:
        first, *others = detail_spans(card)[:2]
        first.replace_with(node(f"<span>{only}</span>", "span"))
        for other in others:
            other.decompose()

    moss = places(edited({"Moss": one_part}))["Moss"]
    assert (moss.google_category, moss.address) == (category, address)


def test_a_category_with_a_digit_stays_a_category_beside_an_address(edited):
    def category(card: LexborNode) -> None:
        detail_spans(card)[0].replace_with(node("<span>3D spausdinimo paslauga</span>", "span"))

    moss = places(edited({"Moss": category}))["Moss"]
    assert (moss.google_category, moss.address) == ("3D spausdinimo paslauga", "Pylimo g. 47")


def test_the_accessibility_icon_is_neither_category_nor_address(edited):
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
def test_unknown_markup_stops_the_parse(edited, edit, message):
    with pytest.raises(ValueError, match=message):
        parse_cards(edited({"Cozy": edit}))


# Rendering and the snapshot

UNRENDERED = "<html><body>Įgalinkite „JavaScript“.</body></html>"  # no main panel


def rendered(html: str) -> bytes:
    return json.dumps({"results": [{"html": html}]}).encode()


def test_queries_cover_every_keyword_in_every_eldership():
    assert len(QUERIES) == 4 * 21
    assert len({query.file_name for query in QUERIES}) == len(QUERIES)
    first = QUERIES[0]
    assert (first.category, first.text) == ("cafes_bakeries", "kavinė Antakalnis Vilnius")
    assert (
        first.url == "https://www.google.com/maps/search/kavin%C4%97%20Antakalnis%20Vilnius?hl=lt"
    )
    assert first.file_name == "kavine-antakalnis-vilnius.html"


def test_each_query_is_rendered_through_oxylabs(session, api_key, list_page, tmp_path, month):
    for _ in QUERIES:
        session.reply(rendered(list_page))
    with Fetcher(offline=False) as fetcher:
        files = GoogleMaps().fetch(fetcher, tmp_path, month)
    first = session.requests[0]
    assert (first.method, first.url) == ("POST", OXYLABS_URL)
    assert first.json == {"url": QUERIES[0].url, "run_js": True, "output": ["html"]}
    assert first.headers["Authorization"] == f"Bearer {api_key}"
    assert [file.url for file in files] == [query.url for query in QUERIES]
    assert files[0].path.read_text(encoding="utf-8") == list_page


def test_saved_pages_are_not_rendered_again(session, tmp_path, month):
    for query in QUERIES:
        (tmp_path / query.file_name).write_text("saved", encoding="utf-8")
    with Fetcher(offline=True) as fetcher:
        GoogleMaps().fetch(fetcher, tmp_path, month)
    assert session.requests == []


def test_an_unrendered_page_is_rendered_again(session, api_key, place_page, caplog):
    session.reply(rendered(UNRENDERED))
    session.reply(rendered(place_page))
    with Fetcher(offline=False) as fetcher:
        assert Renderer(fetcher).render(QUERIES[0].url) == place_page
    assert len(session.requests) == 2
    assert caplog.messages == [f"{QUERIES[0].url}: came back unrendered (attempt 1)"]


def test_rendering_gives_up_and_saves_nothing(session, api_key, tmp_path, month):
    for _ in range(RENDER_ATTEMPTS):
        session.reply(rendered(UNRENDERED))
    with (
        Fetcher(offline=False) as fetcher,
        pytest.raises(FetchError, match=f"came back unrendered {RENDER_ATTEMPTS} times"),
    ):
        GoogleMaps().fetch(fetcher, tmp_path, month)
    assert len(session.requests) == RENDER_ATTEMPTS
    assert list(tmp_path.iterdir()) == []


def test_the_cap_leaves_room_for_every_query_and_some_retries():
    assert len(QUERIES) < RENDER_CAP


def test_the_cap_counts_every_render_of_a_run(
    session, api_key, place_page, tmp_path, month, monkeypatch
):
    monkeypatch.setattr(google_maps, "RENDER_CAP", 3)
    session.reply(rendered(UNRENDERED))  # the first query takes two renders
    for _ in range(2):
        session.reply(rendered(place_page))
    with (
        Fetcher(offline=False) as fetcher,
        pytest.raises(FetchError, match="the 3 renders allowed in one run are spent"),
    ):
        GoogleMaps().fetch(fetcher, tmp_path, month)
    assert len(session.requests) == 3
    assert len(list(tmp_path.iterdir())) == 2


def test_rendering_needs_the_api_key(session, tmp_path, month):
    with Fetcher(offline=False) as fetcher, pytest.raises(FetchError, match=API_KEY_VARIABLE):
        GoogleMaps().fetch(fetcher, tmp_path, month)
    assert session.requests == []


def snapshot_of(pages: dict[str, str], tmp_path, month, saved_at: datetime | None = None) -> int:
    """Snapshot saved pages, given by query file name; return the row count."""
    for query in QUERIES:
        path = tmp_path / query.file_name
        path.write_text(pages[query.file_name], encoding="utf-8")
        if saved_at:
            os.utime(path, (saved_at.timestamp(), saved_at.timestamp()))
    source = GoogleMaps()
    with Fetcher(offline=True) as fetcher, duckdb.connect() as con:
        return source.snapshot(con, source.fetch(fetcher, tmp_path, month), tmp_path)


def test_the_snapshot_has_a_row_per_place_and_query(list_page, place_page, tmp_path, month):
    last = QUERIES[-1]
    pages = {query.file_name: place_page for query in QUERIES} | {last.file_name: list_page}
    assert snapshot_of(pages, tmp_path, month) == 20
    cozy = duckdb.sql(
        f"SELECT * FROM '{tmp_path / 'google_maps.parquet'}' WHERE name = 'Cozy'"
    ).fetchall()
    assert [row[:2] + row[6:11] for row in cozy] == [
        (5596741140976187341, "Cozy", 1815, False, "dental_clinics", last.text, last.file_name)
    ]
    manifest = json.loads((tmp_path / "google_maps.json").read_text(encoding="utf-8"))
    assert manifest["period"] == str(datetime.now(UTC).date())  # the day the pages were saved
    assert len(manifest["files"]) == len(QUERIES)


def test_a_month_without_any_list_of_places_gives_no_rows(place_page, tmp_path, month):
    assert snapshot_of({query.file_name: place_page for query in QUERIES}, tmp_path, month) == 0


def test_a_place_is_dated_by_the_day_its_page_was_saved(list_page, place_page, tmp_path, month):
    pages = {query.file_name: place_page for query in QUERIES} | {QUERIES[0].file_name: list_page}
    snapshot_of(pages, tmp_path, month, saved_at=datetime(2026, 10, 17, 12, tzinfo=UTC))
    dates = duckdb.sql(f"SELECT DISTINCT fetched_on FROM '{tmp_path / 'google_maps.parquet'}'")
    assert dates.fetchall() == [(datetime(2026, 10, 17).date(),)]


def test_a_page_that_no_longer_parses_is_named(list_page, tmp_path, month):
    broken = QUERIES[5].file_name
    pages = {query.file_name: list_page for query in QUERIES}
    pages[broken] = list_page.replace("!1s0x", "!1sXX", 1)
    with pytest.raises(FetchError, match=broken):
        snapshot_of(pages, tmp_path, month)
