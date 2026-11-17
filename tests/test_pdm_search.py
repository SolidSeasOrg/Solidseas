"""Finding a project by part of its name, its customer or its section (pdm.search)."""

import datetime

from solidseas.pdm.search import score, search, words

UTC = datetime.UTC


def when(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 11, day, tzinfo=UTC)


PROJECTS = [
    ("Gearbox", "Projects", "Projects/Gearbox", when(3)),
    ("Bracket Rev2", "Projects", "Projects/Bracket Rev2", when(5)),
    ("Acme Co", "Customers", "Customers/Acme Co", when(1)),
    ("Café Nord", "Customers", "Customers/Café Nord", when(9)),
    ("Old Bracket", "Archive", "Archive/Old Bracket", None),
]


def names(query: str) -> list[str]:
    return [f.entry[0] for f in search(PROJECTS, query, key=lambda e: e)]


def test_words_ignore_case_accents_and_punctuation():
    assert words("Café-Nord_2 (rev.B)") == ["cafe", "nord", "2", "rev", "b"]


def test_an_empty_search_lists_every_project_most_recent_first():
    assert names("") == ["Café Nord", "Bracket Rev2", "Gearbox", "Acme Co", "Old Bracket"]
    assert names("  -- ") == names("")


def test_words_match_in_any_order_and_all_must_match():
    assert names("rev2 bracket") == ["Bracket Rev2"]
    assert names("bracket nothing") == []


def test_a_customer_is_found_by_its_section_too():
    assert names("customer acme") == ["Acme Co"]
    assert names("customers") == ["Café Nord", "Acme Co"]


def test_letters_may_be_left_out():
    assert names("brkt") == ["Bracket Rev2", "Old Bracket"]
    assert names("gbx") == ["Gearbox"]


def test_a_name_match_beats_a_section_match_and_ties_go_to_the_newest():
    assert names("bracket") == ["Bracket Rev2", "Old Bracket"]
    assert score("cafe", "Café Nord") > score("cafe", "Nord", "Café")
    assert score("acmeco", "Acme Co") > 0  # typed without the space


def test_the_limit():
    assert len(search(PROJECTS, "", key=lambda e: e, limit=2)) == 2
