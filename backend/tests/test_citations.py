"""Tests for structured citation helpers used by chat source cards."""
from __future__ import annotations

from src.tools.citations import citations_from_tool_raw, merge_citations


def test_citations_from_kb_raw():
    cites = citations_from_tool_raw(
        "search_kb",
        {
            "kb_id": "kb-1",
            "results": [
                {
                    "filename": "notes.md",
                    "score": 0.812,
                    "doc_id": "d1",
                    "text_preview": "hello world",
                }
            ],
        },
    )
    assert len(cites) == 1
    assert cites[0]["channel"] == "kb"
    assert cites[0]["title"] == "notes.md"
    assert cites[0]["score"] == 0.812
    assert cites[0]["url"] is None


def test_kb_filename_url_becomes_clickable():
    cites = citations_from_tool_raw(
        "search_kb",
        {
            "kb_id": "kb-1",
            "results": [
                {
                    "filename": "https://help.roogoo.com/zh-CN/articles/14086084",
                    "score": 0.63,
                    "doc_id": "d1",
                    "text_preview": "card info",
                }
            ],
        },
    )
    assert cites[0]["url"] == "https://help.roogoo.com/zh-CN/articles/14086084"
    assert cites[0]["source"] == "help.roogoo.com"


def test_citations_from_web_raw():
    cites = citations_from_tool_raw(
        "web_search",
        {
            "results": [
                {
                    "title": "Example Article",
                    "url": "https://www.example.com/a",
                    "body": "snippet text",
                }
            ],
        },
    )
    assert len(cites) == 1
    assert cites[0]["channel"] == "web"
    assert cites[0]["source"] == "example.com"
    assert cites[0]["url"] == "https://www.example.com/a"
    assert cites[0]["score"] is None


def test_merge_citations_keeps_higher_kb_score():
    a = [
        {
            "channel": "kb",
            "title": "a.md",
            "source": "a.md",
            "score": 0.4,
            "kb_id": "k",
            "doc_id": "d",
        }
    ]
    b = [
        {
            "channel": "kb",
            "title": "a.md",
            "source": "a.md",
            "score": 0.9,
            "kb_id": "k",
            "doc_id": "d",
        }
    ]
    merged = merge_citations(a, b)
    assert len(merged) == 1
    assert merged[0]["score"] == 0.9
