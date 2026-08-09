"""Unit tests for LightRAG Server client helpers."""
from src.kg.lightrag_client import file_source_for_doc, workspace_for_kb


def test_workspace_for_kb_sanitizes_uuid():
    assert workspace_for_kb("a1b2c3d4-e5f6-7890-abcd-ef1234567890") == (
        "a1b2c3d4_e5f6_7890_abcd_ef1234567890"
    )


def test_workspace_for_kb_empty_fallback():
    assert workspace_for_kb("") == "default"
    assert workspace_for_kb("   ") == "default"


def test_file_source_for_doc_stable():
    src = file_source_for_doc("kb1", "doc2", "notes/hello.md")
    assert src == "agenora/kb1/doc2/notes_hello.md"
