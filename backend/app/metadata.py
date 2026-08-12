"""Dependency-free reader for a note returned by an external model.

PaperNote's bibliography comes from Zotero.  This module only maps a JSON,
Markdown, or plain-text answer onto an existing paper's editable metadata and
research-note fields.
"""

from __future__ import annotations

import json
import ast
import re
from pathlib import Path
from typing import Any

from .library import CJK_RE, normalize_doi, parse_authors


FIELD_ALIASES = {
    "title": "title", "题名": "title", "name": "title",
    "author": "authors", "authors": "authors", "作者": "authors",
    "year": "year", "date": "year", "published": "year", "年份": "year",
    "journal": "journal", "container-title": "journal", "刊物": "journal",
    "期刊": "journal", "来源": "journal", "期刊/来源": "journal",
    "volume": "volume", "卷": "volume", "issue": "issue", "期": "issue",
    "pages": "pages", "page": "pages", "页码": "pages",
    "doi": "doi", "abstract": "abstract", "摘要": "abstract",
    "keywords": "keywords", "keyword": "keywords", "关键词": "keywords",
    "language": "language", "citation_key": "citation_key", "citekey": "citation_key",
    "document_type": "document_type", "type": "document_type", "文献类型": "document_type",
    "note": "markdown", "markdown": "markdown", "free_note": "markdown",
    "中文摘要": "abstract_zh", "摘要（中文）": "abstract_zh", "摘要（中文译文）": "abstract_zh",
    "abstract_zh": "abstract_zh", "translated abstract": "abstract_zh",
    "研究问题": "research_question", "论文思路": "paper_idea", "写作逻辑": "paper_idea",
    "论文写作逻辑": "paper_idea", "数据集": "datasets", "气象变量": "variables", "研究区域": "region",
    "时间范围": "time_range", "研究方法": "methods", "方法": "methods",
    "模式/模型": "models", "模式 / 模型": "models", "模式与模型": "models", "主要结论": "key_findings",
    "局限性": "limitations", "可借鉴点": "reusable_ideas", "自由笔记": "markdown",
    "research_question": "research_question", "paper_idea": "paper_idea", "datasets": "datasets", "variables": "variables",
    "region": "region", "time_range": "time_range", "methods": "methods", "models": "models",
    "key_findings": "key_findings", "limitations": "limitations", "reusable_ideas": "reusable_ideas",
    "research question": "research_question", "paper idea": "paper_idea", "writing logic": "paper_idea",
    "argument flow": "paper_idea", "data set": "datasets", "weather variables": "variables",
    "study area": "region", "time range": "time_range", "research methods": "methods",
    "model": "models", "models": "models", "key findings": "key_findings",
    "reusable ideas": "reusable_ideas", "free note": "markdown", "free notes": "markdown",
}

NOTE_FIELDS_ORDER = (
    "abstract_zh", "research_question", "paper_idea", "datasets", "variables", "region", "time_range", "methods",
    "models", "key_findings", "limitations", "reusable_ideas", "markdown",
)
NOTE_FIELDS = set(NOTE_FIELDS_ORDER)


def clean_keywords(values: Any, doi: str | None = None) -> list[str]:
    """Return researcher-facing keywords without DOI/URL metadata noise."""
    if isinstance(values, str):
        raw_values = re.split(r"[,;；、\n]", values)
    elif isinstance(values, (list, tuple, set)):
        raw_values = list(values)
    else:
        raw_values = []
    normalized_doi = normalize_doi(doi or "") or ""
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        item = _text(raw).strip(" \t\r\n[]{}'\"")
        if not item or len(item) > 100:
            continue
        lower = item.lower()
        candidate_doi = normalize_doi(item)
        if candidate_doi or "doi.org/" in lower or lower.startswith("http://") or lower.startswith("https://"):
            continue
        if normalized_doi and candidate_doi == normalized_doi:
            continue
        key = lower.casefold()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(stripped)
                except (ValueError, SyntaxError):
                    parsed = None
            if isinstance(parsed, list):
                return _text(parsed)
        return value.strip()
    if isinstance(value, list):
        # External model responses often use JSON arrays for note fields.
        # Keep that structure readable in the editor instead of exposing the
        # Python/JSON representation ("['a', 'b']") to researchers.
        items = [_text(item) for item in value]
        items = [item for item in items if item]
        return "\n".join(f"- {item}" for item in items)
    if isinstance(value, dict):
        rows = []
        for key, item in value.items():
            rendered = _text(item)
            if rendered:
                rows.append(f"{key}：{rendered}")
        return "\n".join(rows)
    return str(value).strip()


def format_note_value(value: Any, field: str = "") -> str:
    """Make structured note values readable while preserving free Markdown."""
    rendered = _text(value)
    if field == "markdown" and rendered:
        rendered = re.sub(r"\s+(?=#{1,6}\s)", "\n\n", rendered)
        rendered = re.sub(r"\s+(-\s+)", r"\n\1", rendered)
        rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered


def _year(value: Any) -> int | None:
    match = re.search(r"\b(?:17|18|19|20|21)\d{2}\b", _text(value))
    return int(match.group(0)) if match else None


def _authors(value: Any) -> list[dict[str, str]]:
    if isinstance(value, list):
        return parse_authors(value)
    raw = _text(value)
    if not raw:
        return []
    # BibTeX uses "and"; Chinese references commonly use 、 or ；.
    return parse_authors(re.sub(r"\s+and\s+", ";", raw, flags=re.I).replace("、", ";").replace("；", ";"))


def _document_type(value: Any, title: str = "") -> str:
    raw = _text(value).lower()
    probe = f"{raw} {title.lower()}"
    if any(token in probe for token in ("thesis", "dissertation", "学位", "硕士", "博士")):
        return "thesis"
    if any(token in probe for token in ("report", "technical report", "报告")):
        return "report"
    if any(token in probe for token in ("book", "chapter", "专著", "图书")):
        return "book"
    if any(token in probe for token in ("conference", "proceedings", "会议")):
        return "conference"
    if any(token in probe for token in ("preprint", "预印本")):
        return "preprint"
    if any(token in probe for token in ("dataset", "data set", "数据集")):
        return "dataset"
    return "article"


def _normalise(record: dict[str, Any], filename: str = "") -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for key, value in record.items():
        if str(key).strip().lower() == "note" and isinstance(value, dict):
            mapped.setdefault("note", {}).update(value)
            continue
        target = FIELD_ALIASES.get(str(key).strip().lower(), str(key).strip().lower())
        if target in NOTE_FIELDS:
            mapped.setdefault("note", {})[target] = _text(value)
        else:
            mapped[target] = value
    title = _text(mapped.get("title")) or Path(filename or "reference").stem
    keywords = clean_keywords(mapped.get("keywords", []), _text(mapped.get("doi")))
    authors = _authors(mapped.get("authors", []))
    doi = normalize_doi(_text(mapped.get("doi")))
    note = dict(mapped.get("note") or {})
    result = {
        "title": title,
        "authors": authors,
        "year": _year(mapped.get("year")),
        "journal": _text(mapped.get("journal")),
        "volume": _text(mapped.get("volume")),
        "issue": _text(mapped.get("issue")),
        "pages": _text(mapped.get("pages")),
        "doi": doi,
        "abstract": _text(mapped.get("abstract")),
        "keywords": keywords,
        "language": _text(mapped.get("language")) or ("zh" if CJK_RE.search(title) else "en"),
        "citation_key": _text(mapped.get("citation_key")),
        "document_type": _document_type(mapped.get("document_type"), title),
        "note": {key: format_note_value(note.get(key), key) for key in NOTE_FIELDS_ORDER},
        "metadata_source": "imported",
    }
    return result


def _json_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("papers", "items", "records", "references"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
        # PaperNote's exported detail has metadata and note nested objects.
        record = dict(value)
        if isinstance(record.get("note"), dict):
            record.update(record.pop("note"))
        return [record]
    return []


def _external_text_record(content: str, filename: str) -> dict[str, Any]:
    """Parse a model-produced Markdown/TXT response into metadata and notes.

    External models do not always follow one exact export format.  Accept both
    ``## 研究问题`` sections and ``研究问题：...`` lines, while ignoring
    unrecognised prose instead of guessing bibliographic fields.
    """
    record: dict[str, Any] = {}
    body = content.replace("\r\n", "\n").replace("\r", "\n")
    # Reuse the front-matter reader when the file is a PaperNote Markdown
    # export, then parse any additional sections below it.
    if body.lstrip().startswith("---"):
        lines = body.lstrip().splitlines()
        end = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
        if end is not None:
            for line in lines[1:end]:
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                try:
                    value: Any = json.loads(raw.strip())
                except json.JSONDecodeError:
                    value = raw.strip().strip("'\"")
                record[key.strip()] = value
            body = "\n".join(lines[end + 1:])

    lines = body.splitlines()
    recognised = bool(record)
    section_starts: list[tuple[int, str | None]] = []
    container_labels = {"题录信息", "科研笔记", "原文摘录", "原文摘录（手工补充）"}

    # Old PaperNote exports may contain a removed full-translation section.
    # Ignore that entire legacy block so headings inside it (for example
    # “研究方法”) cannot be mistaken for current research-note fields.
    legacy_translation_range: tuple[int, int] | None = None
    for index, line in enumerate(lines):
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if not heading or heading.group(1).strip() not in {"正文全文翻译", "全文翻译"}:
            continue
        end = len(lines)
        for candidate_index in range(index + 1, len(lines)):
            candidate = re.match(r"^\s*##\s+(.+?)\s*$", lines[candidate_index])
            if candidate and candidate.group(1).strip() in {"原文摘录", "原文摘录（手工补充）"}:
                end = candidate_index
                break
        legacy_translation_range = (index, end)
        break

    def inside_legacy_translation(index: int) -> bool:
        return bool(legacy_translation_range and legacy_translation_range[0] <= index < legacy_translation_range[1])

    for index, line in enumerate(lines):
        if legacy_translation_range and index == legacy_translation_range[0]:
            section_starts.append((index, None))
            continue
        if inside_legacy_translation(index):
            continue
        stripped = line.strip()
        if not stripped:
            continue
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", stripped)
        if heading:
            label = re.sub(r"[*_`]", "", heading.group(1)).rstrip(":：").strip()
            key = FIELD_ALIASES.get(label.lower())
            if key:
                recognised = True
                section_starts.append((index, key))
            elif label in container_labels:
                section_starts.append((index, None))
            continue

        # Reader exports use bold list labels (for example
        # ``- **作者**：...``); external model answers usually use plain labels.
        candidate = re.sub(r"^(?:[-*+]\s*)", "", stripped)
        inline = re.match(r"^([^:：\n]{1,60})\s*[:：]\s*(.*)$", candidate)
        if inline:
            label = re.sub(r"[*_`]", "", inline.group(1)).strip()
            value = inline.group(2).strip()
            key = FIELD_ALIASES.get(label.lower())
            if key:
                recognised = True
                record.setdefault(key, value)

    # Recognised headings use all text until the next PaperNote field or
    # container heading.  Unrecognised headings inside free notes remain part
    # of the note instead of truncating it.
    for position, (start, key) in enumerate(section_starts):
        if key is None:
            continue
        end = section_starts[position + 1][0] if position + 1 < len(section_starts) else len(lines)
        value = "\n".join(lines[start + 1:end]).strip()
        if value and not record.get(key):
            record[key] = value

    title_match = re.search(r"^[ \t]*#[ \t]+([^\r\n]+)$", body, flags=re.M)
    if title_match:
        record.setdefault("title", title_match.group(1).strip())
    if not recognised and not record:
        # A free-form model answer is still useful as a reversible Markdown
        # note, but it must not be mistaken for title/author metadata.
        record["markdown"] = content.strip()
    normalised = _normalise(record, filename)
    provided = {FIELD_ALIASES.get(str(key).strip().lower(), str(key).strip().lower()) for key in record}
    if isinstance(record.get("note"), dict):
        provided.update(FIELD_ALIASES.get(str(key).strip().lower(), str(key).strip().lower()) for key in record["note"])
    normalised["_provided_fields"] = provided
    if "title" not in record:
        normalised["title"] = ""
    return normalised


def parse_external_model_file(filename: str, content: str) -> dict[str, Any]:
    """Parse one external LLM response for import into an existing paper."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        raw = json.loads(content)
        records = _json_records(raw)
        if not records:
            raise ValueError("JSON 中没有可导入的对象")
        record = dict(records[0])
        metadata = record.pop("metadata", None)
        note = record.pop("note", None) or record.pop("notes", None)
        if isinstance(metadata, dict):
            merged = {**metadata, **record}
        else:
            merged = record
        if isinstance(note, dict):
            merged["note"] = note
        normalised = _normalise(merged, filename)
        provided = {FIELD_ALIASES.get(str(key).strip().lower(), str(key).strip().lower()) for key in merged}
        if isinstance(merged.get("note"), dict):
            provided.update(FIELD_ALIASES.get(str(key).strip().lower(), str(key).strip().lower()) for key in merged["note"])
        normalised["_provided_fields"] = provided
        if "title" not in merged:
            normalised["title"] = ""
        return normalised
    return _external_text_record(content, filename)
