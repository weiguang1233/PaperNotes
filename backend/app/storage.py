from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .config import PATHS


NOTE_FIELDS = (
    "abstract_zh", "research_question", "paper_idea", "datasets", "variables", "region",
    "time_range", "methods", "models", "key_findings", "limitations", "reusable_ideas", "markdown",
)

NOTE_HEADINGS = (
    ("abstract_zh", "摘要（原文摘要的中文翻译）"),
    ("research_question", "研究问题"),
    ("paper_idea", "论文思路（写作逻辑）"),
    ("datasets", "数据集"),
    ("variables", "气象变量"),
    ("region", "研究区域"),
    ("time_range", "时间范围"),
    ("methods", "研究方法"),
    ("models", "模式 / 模型"),
    ("key_findings", "主要结论"),
    ("limitations", "局限性"),
    ("reusable_ideas", "可借鉴点"),
    ("markdown", "自由笔记"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_state() -> dict[str, Any]:
    return {
        "format": "papernote-text-store",
        "version": 1,
        "updated_at": utc_now(),
        "next_ids": {"paper": 1, "excerpt": 1, "collection": 1, "tag": 1, "relation": 1, "note_version": 1},
        "settings": {},
        "papers": {},
        "excerpts": {},
        "collections": {},
        "tags": {},
        "relations": {},
        "paper_collections": {},
        "paper_tags": {},
        "refresh_previews": {},
        "note_versions": {},
    }


def _safe_stem(value: str, fallback: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", value.strip())
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return (value[:120] or fallback)


def _yaml_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_note_markdown(paper: dict[str, Any], note: dict[str, Any]) -> str:
    front = {
        "papernote_format": 1,
        "paper_id": int(paper["id"]),
        "zotero_key": str(paper.get("external_key") or ""),
        "citation_key": str(paper.get("citation_key") or ""),
        "title": str(paper.get("title") or ""),
        "doi": str(paper.get("doi") or ""),
        "updated_at": str(note.get("updated_at") or utc_now()),
    }
    lines = ["---", *(f"{key}: {_yaml_value(value)}" for key, value in front.items()), "---", "", f"# {front['title'] or '未命名文献'}", ""]
    for key, heading in NOTE_HEADINGS:
        lines.extend((f"## {heading}", "", str(note.get(key) or "").strip(), ""))
    return "\n".join(lines).rstrip() + "\n"


def parse_note_markdown(text: str, paper_id: int) -> dict[str, Any]:
    note = {"paper_id": paper_id, **{key: "" for key in NOTE_FIELDS}, "updated_at": ""}
    body = text
    if text.startswith("---\n") and "\n---\n" in text[4:]:
        raw_front, body = text[4:].split("\n---\n", 1)
        for line in raw_front.splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            if key.strip() == "updated_at":
                try:
                    note["updated_at"] = str(json.loads(raw.strip()))
                except (TypeError, ValueError):
                    note["updated_at"] = raw.strip().strip('"')
    headings = {heading: key for key, heading in NOTE_HEADINGS}
    matches = list(re.finditer(r"(?m)^## (.+?)\s*$", body))
    for index, match in enumerate(matches):
        key = headings.get(match.group(1).strip())
        if not key:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        note[key] = body[match.end():end].strip()
    note["updated_at"] = note["updated_at"] or utc_now()
    return note


def parse_note_identity(text: str) -> dict[str, str]:
    """Read stable bibliographic identifiers without parsing note content."""
    identity = {"zotero_key": "", "citation_key": "", "doi": "", "title": ""}
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return identity
    raw_front = text[4:].split("\n---\n", 1)[0]
    for line in raw_front.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        if key not in identity:
            continue
        try:
            value = json.loads(raw.strip())
        except (TypeError, ValueError):
            value = raw.strip().strip('"')
        identity[key] = str(value or "").strip()
    return identity


class TextStore:
    """Atomic JSON catalog plus one readable Markdown file per paper."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: dict[str, Any] = _empty_state()

    def initialize(self) -> None:
        PATHS.ensure()
        if PATHS.state.exists():
            self._state = json.loads(PATHS.state.read_text(encoding="utf-8"))
            self._normalize()
            return
        self._write_state(self._state)

    def _normalize(self) -> None:
        template = _empty_state()
        for key, value in template.items():
            self._state.setdefault(key, deepcopy(value))

    def _write_state(self, value: dict[str, Any]) -> None:
        value["updated_at"] = utc_now()
        temp = PATHS.state.with_suffix(".json.tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, PATHS.state)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    @contextmanager
    def edit(self) -> Iterator[dict[str, Any]]:
        with self._lock:
            draft = deepcopy(self._state)
            yield draft
            self._write_state(draft)
            self._state = draft

    def next_id(self, state: dict[str, Any], kind: str) -> int:
        value = int(state["next_ids"].get(kind, 1))
        state["next_ids"][kind] = value + 1
        return value

    def setting(self, key: str, default: str = "") -> str:
        with self._lock:
            return str(self._state["settings"].get(key, default))

    def set_setting(self, key: str, value: str) -> None:
        with self.edit() as state:
            state["settings"][key] = value

    def paper(self, paper_id: int, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
        source = state or self._state
        value = source["papers"].get(str(paper_id))
        return deepcopy(value) if value else None

    def note_path(self, paper: dict[str, Any]) -> Path:
        stored = str(paper.get("note_file") or "")
        if stored:
            return PATHS.notes / stored
        fallback = "local-{}".format(paper["id"])
        identity = str(paper.get("external_key") or paper.get("citation_key") or fallback)
        return PATHS.notes / "{}.md".format(_safe_stem(identity, fallback))

    def find_note_file(self, paper: dict[str, Any]) -> Path | None:
        """Relink a migrated Markdown note to fresh Zotero metadata.

        Zotero keys are stable when the Zotero data directory is copied or
        synced. DOI and citation key are conservative fallbacks for libraries
        that were exported and re-imported, which may produce new item keys.
        """
        expected = self.note_path(paper)
        if expected.is_file():
            return expected
        zotero_key = str(paper.get("external_key") or "").strip()
        citation_key = str(paper.get("citation_key") or "").strip()
        doi = str(paper.get("doi") or "").strip().lower()
        title = re.sub(r"\s+", " ", str(paper.get("title") or "")).strip().casefold()
        matches: list[tuple[int, Path]] = []
        for candidate in PATHS.notes.glob("*.md"):
            try:
                identity = parse_note_identity(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            score = 0
            if zotero_key and identity["zotero_key"] == zotero_key:
                score = 100
            elif doi and identity["doi"].lower() == doi:
                score = 80
            elif citation_key and identity["citation_key"] == citation_key:
                score = 60
            elif title and re.sub(r"\s+", " ", identity["title"]).strip().casefold() == title:
                score = 20
            if score:
                matches.append((score, candidate))
        if not matches:
            return None
        best_score = max(score for score, _ in matches)
        best = [path for score, path in matches if score == best_score]
        return best[0] if len(best) == 1 else None

    def read_note(self, paper: dict[str, Any]) -> dict[str, Any]:
        path = self.find_note_file(paper) or self.note_path(paper)
        if not path.exists():
            return {"paper_id": int(paper["id"]), **{key: "" for key in NOTE_FIELDS}, "updated_at": utc_now()}
        return parse_note_markdown(path.read_text(encoding="utf-8"), int(paper["id"]))

    def write_note(self, paper: dict[str, Any], note: dict[str, Any]) -> Path:
        path = self.find_note_file(paper) or self.note_path(paper)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".md.tmp")
        temp.write_text(render_note_markdown(paper, note), encoding="utf-8")
        os.replace(temp, path)
        if paper.get("note_file") != path.name:
            with self.edit() as state:
                target = state["papers"].get(str(paper["id"]))
                if target is not None:
                    target["note_file"] = path.name
        return path

store = TextStore()
