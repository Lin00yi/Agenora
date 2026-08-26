"""Knowledge-domain chunking strategies.

Sizes are in characters, not tokens. Rationale:
  - BGE-M3 tokenizer-aware sizing requires loading the tokenizer in-process
    (~heavy). Chars are a decent proxy: Chinese ~1.5 char/token, English
    ~4 char/token, mixed ~2-3 char/token. With target=1500 chars we land in
    the 500-1000 token band most of the time.
  - Adjust per KB/document if you need to be precise.

Public API:
    chunk_text(text, target=1500, max_size=1800, overlap=150) -> list[str]
    chunk_text_by_strategy(text, strategy="recursive", ...) -> list[str]
"""
from __future__ import annotations

import re
from typing import Literal


# Chinese sentences conventionally continue immediately after punctuation
# (``。下一句``), unlike most English prose.  Keep that boundary while retaining
# the whitespace/end guard for ASCII punctuation so values like ``1.6`` are
# never treated as two sentences.
_SENT_RE = re.compile(r"(?<=[。！？])|(?<=[.!?])(?=\s|$)")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_CODE_SYMBOL_RE = re.compile(
    r"^\s*(async\s+def|def|class|function|const|let|var|export\s+function|"
    r"export\s+class|interface|type)\s+[\w$]+",
    re.MULTILINE,
)
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")

ChunkStrategy = Literal[
    "auto",
    "markdown_heading",
    "table_aware",
    "code",
]
SUPPORTED_CHUNK_STRATEGIES: set[str] = {
    "auto",
    "markdown_heading",
    "table_aware",
    "code",
}

# Values accepted by earlier releases.  Keep them readable so old rows remain
# safe to re-ingest, but do not offer or accept them as current product modes.
LEGACY_CHUNK_STRATEGY_MAP: dict[str, ChunkStrategy] = {
    "recursive": "auto",
    "semantic": "auto",
    "parent_child": "markdown_heading",
}
_CODE_SUFFIXES = frozenset({
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".java", ".js", ".jsx",
    ".kt", ".kts", ".m", ".mm", ".php", ".py", ".rb", ".rs", ".sh",
    ".sql", ".swift", ".ts", ".tsx", ".vue", ".yaml", ".yml",
})


def chunk_text(
    text: str,
    *,
    target: int = 1500,
    max_size: int = 1800,
    overlap: int = 150,
) -> list[str]:
    """Backward-compatible recursive chunker entry point."""
    return _recursive_chunk_text(text, target=target, max_size=max_size, overlap=overlap)


def chunk_text_by_strategy(
    text: str,
    *,
    strategy: str = "auto",
    target: int = 1500,
    max_size: int = 1800,
    overlap: int = 150,
) -> list[str]:
    """Split text with a named strategy.

    ``auto`` is the safe generic fallback.  Source-aware callers should use
    :func:`infer_auto_chunk_strategy` before entering this text-only boundary.
    """
    strategy = normalize_chunk_strategy(strategy)
    if strategy == "markdown_heading":
        return _markdown_heading_chunk_text(text, target=target, max_size=max_size, overlap=overlap)
    if strategy == "table_aware":
        return _table_aware_chunk_text(text, target=target, max_size=max_size, overlap=overlap)
    if strategy == "code":
        return _code_chunk_text(text, target=target, max_size=max_size, overlap=overlap)
    return _recursive_chunk_text(text, target=target, max_size=max_size, overlap=overlap)


def normalize_chunk_strategy(value: str | None) -> ChunkStrategy:
    raw = (value or "recursive").strip().lower().replace("-", "_")
    if raw in LEGACY_CHUNK_STRATEGY_MAP:
        return LEGACY_CHUNK_STRATEGY_MAP[raw]
    if raw not in SUPPORTED_CHUNK_STRATEGIES:
        return "auto"
    return raw  # type: ignore[return-value]


def infer_auto_chunk_strategy(*, filename: str, text: str) -> str:
    """Choose a real structural splitter for an ``auto`` document.

    Tables take precedence for Markdown containing table rows; a heading-only
    splitter would otherwise break the header-to-row relationship.  Ordinary
    URL/PDF/DOCX text deliberately falls back to the corrected recursive
    splitter instead of pretending to be semantic or parent/child retrieval.
    """
    lower_name = (filename or "").lower().rsplit("/", 1)[-1]
    suffix = "." + lower_name.rsplit(".", 1)[-1] if "." in lower_name else ""
    if suffix in _CODE_SUFFIXES:
        return "code"
    if any(kind == "table" for kind, _ in _split_table_blocks(text)):
        return "table_aware"
    if suffix in {".md", ".markdown", ".mdx"}:
        return "markdown_heading"
    return "recursive"


def _recursive_chunk_text(
    text: str,
    *,
    target: int,
    max_size: int,
    overlap: int,
) -> list[str]:
    """Paragraph -> sentence -> char fallback with trailing overlap."""
    if not text or not text.strip():
        return []

    atoms = _atomize(text, max_size=max_size)
    if not atoms:
        return []

    target = min(target, max_size)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    sep = "\n\n"
    sep_len = len(sep)

    for atom in atoms:
        atom_len = len(atom)
        join_cost = sep_len if current else 0

        if current and current_len + join_cost + atom_len > target:
            chunks.append(sep.join(current))
            tail: list[str] = []
            tail_len = 0
            for a in reversed(current):
                append_cost = len(a) + (sep_len if tail else 0)
                if tail_len + append_cost > overlap:
                    break
                tail.insert(0, a)
                tail_len += append_cost
            # Never let overlap push a chunk past its explicit maximum.  This
            # used to yield live chunks larger than ``max_size`` whenever a
            # retained tail preceded a near-max-size atom.
            max_tail_len = max(0, max_size - atom_len - (sep_len if tail else 0))
            while tail and tail_len > max_tail_len:
                removed = tail.pop(0)
                tail_len -= len(removed) + (sep_len if tail else 0)
            current = tail + [atom]
            current_len = sum(len(a) for a in current) + sep_len * (len(current) - 1)
        else:
            current.append(atom)
            current_len += join_cost + atom_len

    if current:
        chunks.append(sep.join(current))

    return chunks


def _atomize(text: str, *, max_size: int) -> list[str]:
    """Break text into <= max_size atoms: paragraphs, sentences, or char slices."""
    atoms: list[str] = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_size:
            atoms.append(para)
            continue
        for sent in _SENT_RE.split(para):
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) <= max_size:
                atoms.append(sent)
                continue
            for i in range(0, len(sent), max_size):
                atoms.append(sent[i : i + max_size])
    return atoms


def _markdown_heading_chunk_text(
    text: str,
    *,
    target: int,
    max_size: int,
    overlap: int,
) -> list[str]:
    sections = _markdown_sections(text)
    if len(sections) <= 1 and not sections[0][0]:
        return _recursive_chunk_text(text, target=target, max_size=max_size, overlap=overlap)

    chunks: list[str] = []
    for heading_path, body in sections:
        prefix = f"Section: {' > '.join(heading_path)}" if heading_path else ""
        chunks.extend(
            _split_with_prefix(
                prefix,
                body,
                target=target,
                max_size=max_size,
                overlap=overlap,
            )
        )
    return chunks


def _table_aware_chunk_text(
    text: str,
    *,
    target: int,
    max_size: int,
    overlap: int,
) -> list[str]:
    blocks = _split_table_blocks(text)
    if not any(kind == "table" for kind, _ in blocks):
        return _recursive_chunk_text(text, target=target, max_size=max_size, overlap=overlap)

    chunks: list[str] = []
    for kind, block in blocks:
        if kind != "table":
            chunks.extend(
                _recursive_chunk_text(block, target=target, max_size=max_size, overlap=overlap)
            )
            continue
        chunks.extend(_chunk_markdown_table(block, target=target, max_size=max_size))
    return chunks


def _code_chunk_text(
    text: str,
    *,
    target: int,
    max_size: int,
    overlap: int,
) -> list[str]:
    blocks = _split_code_blocks(text)
    if len(blocks) == 1 and blocks[0][0] == "text" and not _CODE_SYMBOL_RE.search(text):
        return _recursive_chunk_text(text, target=target, max_size=max_size, overlap=overlap)

    chunks: list[str] = []
    for kind, block in blocks:
        if kind == "code":
            chunks.extend(_chunk_by_lines(block, target=target, max_size=max_size))
        else:
            chunks.extend(_chunk_code_symbols(block, target=target, max_size=max_size, overlap=overlap))
    return chunks


def _markdown_sections(text: str) -> list[tuple[list[str], str]]:
    sections: list[tuple[list[str], str]] = []
    heading_stack: list[str] = []
    current: list[str] = []
    current_path: list[str] = []

    def flush() -> None:
        body = "\n".join(current).strip()
        if body:
            sections.append((list(current_path), body))

    for line in text.splitlines():
        m = _MD_HEADING_RE.match(line)
        if not m:
            current.append(line)
            continue
        flush()
        current = []
        level = len(m.group(1))
        title = m.group(2).strip()
        heading_stack[:] = heading_stack[: level - 1]
        heading_stack.append(title)
        current_path = list(heading_stack)

    flush()
    if not sections:
        return [([], text.strip())]
    return sections


def _split_with_prefix(
    prefix: str,
    body: str,
    *,
    target: int,
    max_size: int,
    overlap: int,
) -> list[str]:
    body = body.strip()
    if not prefix:
        return _recursive_chunk_text(body, target=target, max_size=max_size, overlap=overlap)

    prefix = prefix.strip()
    if len(prefix) + 2 >= max_size:
        prefix = prefix[: max(0, max_size // 3)].rstrip()
    budget_max = max(1, max_size - len(prefix) - 2)
    budget_target = max(1, min(target - len(prefix) - 2, budget_max))
    parts = _recursive_chunk_text(
        body,
        target=budget_target,
        max_size=budget_max,
        overlap=min(overlap, max(0, budget_target // 3)),
    )
    return [f"{prefix}\n\n{part}".strip() for part in parts]


def _split_table_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    buf: list[str] = []
    i = 0

    def flush_text() -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            blocks.append(("text", body))
        buf = []

    while i < len(lines):
        if i + 1 < len(lines) and "|" in lines[i] and _TABLE_SEPARATOR_RE.match(lines[i + 1]):
            flush_text()
            table = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                table.append(lines[i])
                i += 1
            blocks.append(("table", "\n".join(table)))
            continue
        buf.append(lines[i])
        i += 1
    flush_text()
    return blocks


def _chunk_markdown_table(block: str, *, target: int, max_size: int) -> list[str]:
    lines = [line.rstrip() for line in block.splitlines() if line.strip()]
    if len(lines) <= 2:
        return _chunk_by_lines(block, target=target, max_size=max_size)
    header = lines[:2]
    rows = lines[2:]
    chunks: list[str] = []
    current = list(header)
    current_len = len("\n".join(current))
    target = min(target, max_size)
    for row in rows:
        row_len = len(row) + 1
        if len(current) > 2 and current_len + row_len > target:
            chunks.append("\n".join(current))
            current = list(header)
            current_len = len("\n".join(current))
        if len("\n".join(header + [row])) > max_size:
            chunks.extend(_chunk_by_lines(row, target=target, max_size=max_size))
        else:
            current.append(row)
            current_len += row_len
    if len(current) > 2:
        chunks.append("\n".join(current))
    return chunks


def _split_code_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    buf: list[str] = []
    in_fence = False
    fence_buf: list[str] = []
    fence_marker = ""

    def flush_text() -> None:
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            blocks.append(("text", body))
        buf = []

    for line in lines:
        m = _FENCE_RE.match(line)
        if m and not in_fence:
            flush_text()
            in_fence = True
            fence_marker = m.group(1)[:3]
            fence_buf = [line]
            continue
        if in_fence:
            fence_buf.append(line)
            if line.strip().startswith(fence_marker):
                blocks.append(("code", "\n".join(fence_buf).strip()))
                in_fence = False
                fence_buf = []
            continue
        buf.append(line)

    if fence_buf:
        blocks.append(("code", "\n".join(fence_buf).strip()))
    flush_text()
    return blocks or [("text", text.strip())]


def _chunk_code_symbols(
    text: str,
    *,
    target: int,
    max_size: int,
    overlap: int,
) -> list[str]:
    matches = list(_CODE_SYMBOL_RE.finditer(text))
    if len(matches) < 2:
        return _recursive_chunk_text(text, target=target, max_size=max_size, overlap=overlap)

    chunks: list[str] = []
    starts = [m.start() for m in matches] + [len(text)]
    preamble = text[: starts[0]].strip()
    if preamble:
        chunks.extend(_recursive_chunk_text(preamble, target=target, max_size=max_size, overlap=overlap))
    for start, end in zip(starts, starts[1:], strict=False):
        block = text[start:end].strip()
        if block:
            chunks.extend(_chunk_by_lines(block, target=target, max_size=max_size))
    return chunks


def _chunk_by_lines(text: str, *, target: int, max_size: int) -> list[str]:
    target = min(target, max_size)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        if len(line) > max_size:
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            chunks.extend(line[i : i + max_size] for i in range(0, len(line), max_size))
            continue
        join_cost = 1 if current else 0
        if current and current_len + join_cost + len(line) > target:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += join_cost + len(line)
    if current:
        chunks.append("\n".join(current))
    return [chunk for chunk in chunks if chunk.strip()]
