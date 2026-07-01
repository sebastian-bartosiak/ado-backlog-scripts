"""Unit tests for the pure (non-network) helpers in ado_lib.py.

Run with: uv run pytest
"""

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import ado_lib as lib


# ── html_to_md ────────────────────────────────────────────────────────────────
def test_html_to_md_empty():
    assert lib.html_to_md("") == ""
    assert lib.html_to_md(None) == ""


def test_html_to_md_plain_text_unescapes_entities():
    assert lib.html_to_md("A &amp; B") == "A & B"


def test_html_to_md_converts_html():
    assert lib.html_to_md("<p>hello <b>world</b></p>") == "hello **world**"


def test_html_to_md_collapses_blank_lines():
    raw = "<p>one</p><p></p><p></p><p></p><p>two</p>"
    result = lib.html_to_md(raw)
    assert "\n\n\n" not in result


# ── tags ────────────────────────────────────────────────────────────────────
def test_parse_tags_empty():
    assert lib.parse_tags("") == []
    assert lib.parse_tags(None) == []


def test_parse_tags_splits_and_strips():
    assert lib.parse_tags("foo; bar ;  baz") == ["foo", "bar", "baz"]


def test_format_tags_roundtrip():
    tags = ["foo", "bar"]
    assert lib.format_tags(tags) == "foo; bar"
    assert lib.parse_tags(lib.format_tags(tags)) == tags


# ── identity_display_name ─────────────────────────────────────────────────────
def test_identity_display_name_string():
    assert lib.identity_display_name("Jane Doe") == "Jane Doe"


def test_identity_display_name_empty():
    assert lib.identity_display_name(None) == ""
    assert lib.identity_display_name("") == ""


def test_identity_display_name_object():
    @dataclass
    class FakeIdentity:
        display_name: str

    assert lib.identity_display_name(FakeIdentity(display_name="Jane Doe")) == "Jane Doe"


# ── patch ops ─────────────────────────────────────────────────────────────────
def test_op_without_value():
    assert lib.op("remove", "/fields/System.AssignedTo") == {
        "op": "remove", "path": "/fields/System.AssignedTo"
    }


def test_op_with_value():
    assert lib.op("add", "/fields/System.Title", "Hello") == {
        "op": "add", "path": "/fields/System.Title", "value": "Hello"
    }


def test_markdown_field_ops_sets_format():
    ops = lib.markdown_field_ops("System.Description", "hello")
    assert ops[0] == {"op": "add", "path": "/fields/System.Description", "value": "hello"}
    assert ops[1] == {
        "op": "replace",
        "path": "/multilineFieldsFormat/System.Description",
        "value": "markdown",
    }


def test_markdown_field_ops_value_op_override():
    ops = lib.markdown_field_ops("System.Description", "hello", value_op="replace")
    assert ops[0]["op"] == "replace"


def test_relation_value():
    v = lib.relation_value("https://dev.azure.com/acme", 123)
    assert v == {
        "rel": lib.HIERARCHY_REVERSE,
        "url": "https://dev.azure.com/acme/_apis/wit/workItems/123",
    }


# ── WIQL ──────────────────────────────────────────────────────────────────────
def test_wiql_escape():
    assert lib.wiql_escape("O'Brien") == "O''Brien"
    assert lib.wiql_escape(123) == "123"


# ── iteration / sprint helpers ────────────────────────────────────────────────
def test_as_date_handles_none():
    assert lib._as_date(None) is None


def test_as_date_handles_iso_string():
    assert lib._as_date("2026-01-14T00:00:00Z") == date(2026, 1, 14)


def test_as_date_handles_date():
    d = date(2026, 1, 14)
    assert lib._as_date(d) is d


def test_normalize_iter_path_strips_iteration_segment():
    assert lib._normalize_iter_path("\\MyProject\\Iteration\\Sprint 104") == "MyProject\\Sprint 104"


def test_normalize_iter_path_no_iteration_segment():
    assert lib._normalize_iter_path("MyProject\\Sprint 104") == "MyProject\\Sprint 104"


def test_sprint_number_extracts_trailing_digits():
    assert lib.sprint_number("MyProject\\Sprint 104") == "104"


def test_sprint_number_falls_back_to_dashed_name():
    assert lib.sprint_number("MyProject\\Sprint Alpha") == "Sprint-Alpha"


def test_sprint_number_unknown_when_empty():
    assert lib.sprint_number(None) == "unknown"
    assert lib.sprint_number("") == "unknown"


@dataclass
class FakeNode:
    path: str
    name: str
    attributes: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


def test_walk_nodes_finds_node_containing_today():
    today = date(2026, 7, 1)
    root = FakeNode(
        path="\\MyProject\\Iteration",
        name="Iteration",
        children=[
            FakeNode(
                path="\\MyProject\\Iteration\\Sprint 103",
                name="Sprint 103",
                attributes={"startDate": date(2026, 6, 1), "finishDate": date(2026, 6, 14)},
            ),
            FakeNode(
                path="\\MyProject\\Iteration\\Sprint 104",
                name="Sprint 104",
                attributes={"startDate": date(2026, 6, 15), "finishDate": date(2026, 7, 5)},
            ),
        ],
    )
    result = lib._walk_nodes(root, today)
    assert result == ("\\MyProject\\Iteration\\Sprint 104", "Sprint 104")


def test_walk_nodes_no_match_returns_none():
    today = date(2020, 1, 1)
    root = FakeNode(path="\\MyProject\\Iteration", name="Iteration", children=[
        FakeNode(
            path="\\MyProject\\Iteration\\Sprint 103",
            name="Sprint 103",
            attributes={"startDate": date(2026, 6, 1), "finishDate": date(2026, 6, 14)},
        ),
    ])
    assert lib._walk_nodes(root, today) is None
