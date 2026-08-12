from __future__ import annotations

import json
import re
import shutil
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import PATHS
from .models import NotePayload, PaperUpdate
from .storage import NOTE_FIELDS, parse_note_markdown, render_note_markdown, store, utc_now


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
CJK_RE = re.compile(r"[\u3400-\u9fff]")
NOTE_OVERVIEW_FIELDS = {
    "abstract_zh": "摘要", "research_question": "研究问题", "paper_idea": "论文思路",
    "methods": "研究方法", "key_findings": "主要结论",
}
NOTE_PREVIEW_FIELDS = (
    ("paper_idea", "论文思路"), ("research_question", "研究问题"),
    ("key_findings", "主要结论"), ("abstract_zh", "摘要"), ("markdown", "自由笔记"),
)
PAPER_FIELDS = {
    "title", "year", "journal", "volume", "issue", "pages", "doi", "abstract", "language",
    "reading_status", "favorite", "citation_key", "needs_review", "document_type",
}


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I)
    match = DOI_RE.search(value)
    return match.group(0).rstrip(".,;)]}").lower() if match else None


def parse_authors(raw: str | list[Any] | None) -> list[dict[str, str]]:
    if not raw:
        return []
    if isinstance(raw, list):
        values = []
        for item in raw:
            if hasattr(item, "model_dump"):
                item = item.model_dump()
            if isinstance(item, dict):
                values.append({"family": str(item.get("family") or "").strip(), "given_name": str(item.get("given_name") or item.get("given") or "").strip(), "literal": str(item.get("literal") or item.get("name") or "").strip()})
            else:
                values.append({"family": "", "given_name": "", "literal": str(item).strip()})
        return [value for value in values if any(value.values())]
    return [{"family": "", "given_name": "", "literal": name.strip()} for name in re.split(r"\s*(?:;|\band\b)\s*", str(raw), flags=re.I) if name.strip()]


def author_display(author: dict[str, str]) -> str:
    return str(author.get("literal") or " ".join(part for part in (author.get("given_name", ""), author.get("family", "")) if part)).strip()


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "", ascii_value)


def generate_citation_key(_context: Any, title: str, year: int | None, authors: list[dict[str, str]]) -> str:
    first = authors[0] if authors else {}
    display = author_display(first)
    surname = first.get("family") or (display.split()[-1] if display else "Anon")
    words = [word for word in re.findall(r"[A-Za-z0-9]+", title) if word.lower() not in {"a", "an", "the", "of", "and", "in", "on"}]
    base = ((_slug(str(surname)) or "Anon") + (str(year) if year else "ND") + ("".join(words[:2]) or "Paper"))[:80]
    source = _context if isinstance(_context, dict) and "papers" in _context else store.snapshot()
    used = {str(paper.get("citation_key") or "") for paper in source["papers"].values()}
    candidate, suffix = base, 0
    while candidate in used:
        suffix += 1
        candidate = f"{base}{chr(96 + suffix)}" if suffix <= 26 else f"{base}{suffix}"
    return candidate


def note_overview(note: dict[str, Any], external_modified_at: str | None = None) -> dict[str, Any]:
    filled = [key for key in NOTE_FIELDS if str(note.get(key) or "").strip()]
    missing = [label for key, label in NOTE_OVERVIEW_FIELDS.items() if not str(note.get(key) or "").strip()]
    preview_field = preview_label = preview = ""
    for key, label in NOTE_PREVIEW_FIELDS:
        value = re.sub(r"\s+", " ", str(note.get(key) or "")).strip()
        if value:
            preview_field, preview_label, preview = key, label, value[:180]
            break
    updated = str(note.get("updated_at") or "")
    source_newer = bool(external_modified_at and updated and str(external_modified_at) > updated)
    if not filled:
        status = "暂无科研笔记"
    elif source_newer:
        status = "外部文献有更新"
    elif missing:
        status = "科研笔记待完善"
    else:
        status = "核心笔记已完成"
    return {"completed_fields": len(filled), "total_fields": len(NOTE_FIELDS), "missing_critical": missing, "preview_field": preview_field, "preview_label": preview_label, "preview": preview, "updated_at": updated, "source_is_newer": source_newer, "needs_update": bool(missing or source_newer), "status": status}


def _visible(paper: dict[str, Any], state: dict[str, Any]) -> bool:
    if paper.get("deleted_at"):
        return False
    if paper.get("external_source") != "zotero":
        return True
    settings = state["settings"]
    return settings.get("zotero_connected", "1") == "1" and str(paper.get("external_library_id") or "") == str(settings.get("zotero_library_id") or "users/0") and bool(paper.get("external_present", True))


def _summary(paper: dict[str, Any]) -> dict[str, Any]:
    value = dict(paper)
    value.setdefault("keywords", [])
    value.setdefault("authors", [])
    for key in ("favorite", "needs_review", "needs_ocr", "external_present"):
        value[key] = bool(value.get(key, False))
    value["note_overview"] = note_overview(store.read_note(paper), value.get("external_modified_at"))
    return value


def get_paper(paper_id: int) -> dict[str, Any] | None:
    state = store.snapshot()
    paper = state["papers"].get(str(paper_id))
    if not paper:
        return None
    result = _summary(paper)
    result.setdefault("manual_fields", [])
    result["files"] = []
    result["note"] = store.read_note(paper)
    result["excerpts"] = sorted((dict(item) for item in state["excerpts"].values() if int(item["paper_id"]) == paper_id), key=lambda item: (int(item["page"]), int(item["id"])))
    tag_ids = set(state["paper_tags"].get(str(paper_id), []))
    result["tags"] = sorted((dict(item) for key, item in state["tags"].items() if int(key) in tag_ids), key=lambda item: str(item["name"]).lower())
    collection_ids = set(state["paper_collections"].get(str(paper_id), []))
    result["collections"] = sorted((dict(item) for key, item in state["collections"].items() if int(key) in collection_ids), key=lambda item: str(item["name"]).lower())
    relations = []
    for item in state["relations"].values():
        if int(item["source_paper_id"]) != paper_id:
            continue
        target = state["papers"].get(str(item["target_paper_id"]))
        if target and not target.get("deleted_at"):
            relations.append({**item, "target_title": target.get("title", "")})
    result["relations"] = sorted(relations, key=lambda item: int(item["id"]), reverse=True)
    result["note_path"] = str(store.note_path(paper))
    return result


def list_papers(page: int = 1, page_size: int = 30, review_only: bool = False) -> dict[str, Any]:
    state = store.snapshot()
    values = [paper for paper in state["papers"].values() if _visible(paper, state) and (not review_only or paper.get("needs_review") or paper.get("needs_ocr"))]
    values.sort(key=lambda paper: (bool(paper.get("favorite")), str(paper.get("updated_at") or "")), reverse=True)
    offset = (page - 1) * page_size
    return {"items": [_summary(paper) for paper in values[offset:offset + page_size]], "total": len(values), "page": page, "page_size": page_size}


def create_paper_record_in_state(
    draft: dict[str, Any],
    values: dict[str, Any],
    authors: list[dict[str, str]] | None = None,
    keywords: list[str] | None = None,
    manual_fields: list[str] | None = None,
    *,
    check_duplicate_doi: bool = True,
) -> dict[str, Any]:
    authors = parse_authors(authors)
    doi = normalize_doi(values.get("doi"))
    if check_duplicate_doi and doi and any(paper.get("doi") == doi and not paper.get("deleted_at") for paper in draft["papers"].values()):
        raise ValueError("DOI already exists")
    now = utc_now()
    paper_id = store.next_id(draft, "paper")
    paper = {
        "id": paper_id, "title": str(values.get("title") or ""), "year": values.get("year"),
        "journal": str(values.get("journal") or ""), "volume": str(values.get("volume") or ""),
        "issue": str(values.get("issue") or ""), "pages": str(values.get("pages") or ""), "doi": doi,
        "abstract": str(values.get("abstract") or ""), "keywords": list(keywords or values.get("keywords") or []),
        "language": str(values.get("language") or ""), "reading_status": str(values.get("reading_status") or "unread"),
        "favorite": bool(values.get("favorite", False)), "citation_key": str(values.get("citation_key") or generate_citation_key(draft, str(values.get("title") or ""), values.get("year"), authors)),
        "metadata_source": str(values.get("metadata_source") or "manual"), "manual_fields": list(manual_fields or []),
        "needs_review": bool(values.get("needs_review", False)), "needs_ocr": bool(values.get("needs_ocr", False)),
        "document_type": str(values.get("document_type") or "article"), "authors": authors,
        "external_source": str(values.get("external_source") or ""), "external_library_id": str(values.get("external_library_id") or ""),
        "external_key": str(values.get("external_key") or ""), "external_item_url": str(values.get("external_item_url") or ""),
        "external_open_uri": str(values.get("external_open_uri") or ""), "external_version": values.get("external_version"),
        "external_modified_at": str(values.get("external_modified_at") or ""), "attachment_url": str(values.get("attachment_url") or ""),
        "external_present": bool(values.get("external_present", True)), "created_at": now, "updated_at": now, "deleted_at": None,
    }
    identity = paper["external_key"] or paper["citation_key"] or f"local-{paper_id}"
    paper["note_file"] = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", identity).strip(" .") + ".md"
    draft["papers"][str(paper_id)] = paper
    return paper


def create_paper_record(values: dict[str, Any], authors: list[dict[str, str]] | None = None, keywords: list[str] | None = None, manual_fields: list[str] | None = None) -> dict[str, Any]:
    with store.edit() as draft:
        paper = create_paper_record_in_state(draft, values, authors, keywords, manual_fields)
        paper_id = int(paper["id"])
        now = str(paper["created_at"])
    paper = store.paper(paper_id)
    store.write_note(paper, {"paper_id": paper_id, **{key: "" for key in NOTE_FIELDS}, "updated_at": now})
    return get_paper(paper_id)


def update_paper(paper_id: int, payload: PaperUpdate, *, mark_manual: bool = True) -> dict[str, Any] | None:
    changes = payload.model_dump(exclude_unset=True)
    if "authors" in changes:
        changes["authors"] = parse_authors(changes["authors"])
    if "doi" in changes:
        changes["doi"] = normalize_doi(changes["doi"])
    with store.edit() as state:
        paper = state["papers"].get(str(paper_id))
        if not paper:
            return None
        if changes.get("doi") and any(int(key) != paper_id and item.get("doi") == changes["doi"] and not item.get("deleted_at") for key, item in state["papers"].items()):
            raise ValueError("DOI already exists")
        manual = set(paper.get("manual_fields") or [])
        paper.update(changes)
        if mark_manual:
            manual.update(changes)
        paper["manual_fields"] = sorted(manual)
        paper["updated_at"] = utc_now()
    return get_paper(paper_id)


def move_paper_to_trash(paper_id: int) -> bool:
    with store.edit() as state:
        paper = state["papers"].get(str(paper_id))
        if not paper:
            return False
        paper["deleted_at"] = paper.get("deleted_at") or utc_now()
        paper["updated_at"] = utc_now()
    return True


def list_trash() -> list[dict[str, Any]]:
    values = [paper for paper in store.snapshot()["papers"].values() if paper.get("deleted_at")]
    values.sort(key=lambda paper: str(paper.get("deleted_at") or ""), reverse=True)
    return [{**_summary(paper), "file_count": 0, "size_bytes": 0} for paper in values]


def restore_paper_from_trash(paper_id: int) -> bool:
    with store.edit() as state:
        paper = state["papers"].get(str(paper_id))
        if not paper:
            return False
        paper["deleted_at"] = None
        paper["updated_at"] = utc_now()
    return True


def permanently_delete_paper(paper_id: int) -> bool:
    paper = store.paper(paper_id)
    if not paper or not paper.get("deleted_at"):
        return False
    # A migrated note may still have its former Zotero-key filename. Delete
    # the file actually linked to this paper, not only the newly expected path.
    note_path = (store.find_note_file(paper) or store.note_path(paper)).resolve()
    history_path = (PATHS.note_history / note_path.stem).resolve()
    with store.edit() as state:
        state["papers"].pop(str(paper_id), None)
        state["paper_collections"].pop(str(paper_id), None)
        state["paper_tags"].pop(str(paper_id), None)
        for bucket in ("excerpts", "relations"):
            state[bucket] = {key: item for key, item in state[bucket].items() if int(item.get("paper_id", item.get("source_paper_id", -1))) != paper_id and int(item.get("target_paper_id", -1)) != paper_id}
        state["note_versions"] = {key: item for key, item in state["note_versions"].items() if int(item["paper_id"]) != paper_id}
    if PATHS.notes.resolve() in note_path.parents and note_path.is_file():
        note_path.unlink()
    if PATHS.note_history.resolve() in history_path.parents and history_path.is_dir():
        shutil.rmtree(history_path)
    return True


def empty_trash() -> int:
    return sum(1 for item in list_trash() if permanently_delete_paper(int(item["id"])))


def refresh_index(_paper_id: int) -> None:
    return None


def ensure_search_index() -> None:
    return None


def save_note(paper_id: int, payload: NotePayload) -> dict[str, Any] | None:
    paper = store.paper(paper_id)
    if not paper:
        return None
    previous = store.read_note(paper)
    values = payload.model_dump(exclude={"force_version"})
    changed = any(str(previous.get(key) or "") != str(values.get(key) or "") for key in NOTE_FIELDS)
    now = datetime.now(timezone.utc)
    state = store.snapshot()
    latest = max((item for item in state["note_versions"].values() if int(item["paper_id"]) == paper_id), key=lambda item: int(item["id"]), default=None)
    version_due = bool(payload.force_version)
    if latest:
        try:
            version_due = version_due or now - datetime.fromisoformat(str(latest["created_at"])) >= timedelta(minutes=10)
        except ValueError:
            version_due = True
    else:
        version_due = version_due or any(str(previous.get(key) or "") for key in NOTE_FIELDS)
    if changed and version_due:
        with store.edit() as draft:
            version_id = store.next_id(draft, "note_version")
            history_dir = PATHS.note_history / store.note_path(paper).stem
            history_dir.mkdir(parents=True, exist_ok=True)
            target = history_dir / f"{version_id}.md"
            target.write_text(render_note_markdown(paper, previous), encoding="utf-8")
            draft["note_versions"][str(version_id)] = {"id": version_id, "paper_id": paper_id, "created_at": now.isoformat(timespec="seconds"), "file": str(target.relative_to(PATHS.root)).replace("\\", "/")}
            own = sorted((item for item in draft["note_versions"].values() if int(item["paper_id"]) == paper_id), key=lambda item: int(item["id"]), reverse=True)
            for stale in own[100:]:
                draft["note_versions"].pop(str(stale["id"]), None)
                stale_path = PATHS.root / str(stale["file"])
                if stale_path.is_file():
                    stale_path.unlink()
    note = {"paper_id": paper_id, **{key: str(values.get(key) or "") for key in NOTE_FIELDS}, "updated_at": now.isoformat(timespec="seconds")}
    store.write_note(paper, note)
    with store.edit() as draft:
        if str(paper_id) in draft["papers"]:
            draft["papers"][str(paper_id)]["updated_at"] = utc_now()
    return note


def get_note(paper_id: int) -> dict[str, Any] | None:
    paper = store.paper(paper_id)
    return store.read_note(paper) if paper else None


def note_versions(paper_id: int) -> list[dict[str, Any]]:
    return sorted((dict(item) for item in store.snapshot()["note_versions"].values() if int(item["paper_id"]) == paper_id), key=lambda item: int(item["id"]), reverse=True)


def restore_note_version(paper_id: int, version_id: int) -> dict[str, Any] | None:
    item = store.snapshot()["note_versions"].get(str(version_id))
    if not item or int(item["paper_id"]) != paper_id:
        return None
    path = (PATHS.root / str(item["file"])).resolve()
    if PATHS.note_history.resolve() not in path.parents or not path.is_file():
        return None
    parsed = parse_note_markdown(path.read_text(encoding="utf-8"), paper_id)
    return save_note(paper_id, NotePayload(**{key: parsed.get(key, "") for key in NOTE_FIELDS}, force_version=True))


def search_papers(
    query: str,
    page: int = 1,
    page_size: int = 30,
    year_from: int | None = None,
    year_to: int | None = None,
    journal: str | None = None,
    reading_status: str | None = None,
    tag_id: int | None = None,
    collection_id: int | None = None,
    needs_review: bool | None = None,
    needs_ocr: bool | None = None,
    search_in: str = "all",
    note_status: str | None = None,
    sort_by: str = "favorite_recent",
) -> dict[str, Any]:
    state = store.snapshot()
    needle = query.casefold().strip()
    search_in = search_in if search_in in {"all", "title", "author", "abstract", "journal", "keyword", "note"} else "all"
    note_status = note_status if note_status in {"complete", "incomplete", "empty", "stale"} else None
    tag_members = {int(key) for key, ids in state["paper_tags"].items() if tag_id in ids} if tag_id else None
    collection_members = {int(key) for key, ids in state["paper_collections"].items() if collection_id in ids} if collection_id else None
    results: list[dict[str, Any]] = []
    notes: dict[int, dict[str, Any]] = {}

    def paper_note(paper: dict[str, Any]) -> dict[str, Any]:
        paper_id = int(paper["id"])
        if paper_id not in notes:
            notes[paper_id] = store.read_note(paper)
        return notes[paper_id]

    for paper in state["papers"].values():
        paper_id = int(paper["id"])
        if not _visible(paper, state) or (year_from is not None and (paper.get("year") or 0) < year_from) or (year_to is not None and (paper.get("year") or 9999) > year_to):
            continue
        if journal and journal.casefold() not in str(paper.get("journal") or "").casefold():
            continue
        if reading_status and paper.get("reading_status") != reading_status:
            continue
        if needs_review is not None and bool(paper.get("needs_review")) != needs_review:
            continue
        if needs_ocr is not None and bool(paper.get("needs_ocr")) != needs_ocr:
            continue
        if tag_members is not None and paper_id not in tag_members or collection_members is not None and paper_id not in collection_members:
            continue
        if note_status:
            overview = note_overview(paper_note(paper), paper.get("external_modified_at"))
            if note_status == "complete" and overview["needs_update"]:
                continue
            if note_status == "incomplete" and (overview["completed_fields"] == 0 or not overview["missing_critical"]):
                continue
            if note_status == "empty" and overview["completed_fields"] != 0:
                continue
            if note_status == "stale" and not overview["source_is_newer"]:
                continue
        if needle:
            fields = {
                "title": str(paper.get("title") or ""),
                "author": " ".join(author_display(a) for a in paper.get("authors") or []),
                "abstract": str(paper.get("abstract") or ""),
                "journal": str(paper.get("journal") or ""),
                "keyword": " ".join(paper.get("keywords") or []),
            }
            bibliographic = "\n".join(fields.values()).casefold() if search_in == "all" else fields.get(search_in, "").casefold()
            matched = needle in bibliographic
            if not matched and search_in in {"all", "note"}:
                note = paper_note(paper)
                excerpt_text = " ".join(str(item.get("text") or "") + " " + str(item.get("comment") or "") for item in state["excerpts"].values() if int(item["paper_id"]) == paper_id)
                matched = needle in ("\n".join(str(note.get(key) or "") for key in NOTE_FIELDS) + excerpt_text).casefold()
            if not matched:
                continue
        results.append(paper)

    if sort_by == "year_desc":
        results.sort(key=lambda paper: (paper.get("year") is not None, int(paper.get("year") or 0), str(paper.get("title") or "").casefold()), reverse=True)
    elif sort_by == "year_asc":
        results.sort(key=lambda paper: (paper.get("year") is None, int(paper.get("year") or 9999), str(paper.get("title") or "").casefold()))
    elif sort_by == "title_asc":
        results.sort(key=lambda paper: str(paper.get("title") or "").casefold())
    elif sort_by == "title_desc":
        results.sort(key=lambda paper: str(paper.get("title") or "").casefold(), reverse=True)
    elif sort_by == "author_asc":
        results.sort(key=lambda paper: (author_display((paper.get("authors") or [{}])[0]).casefold(), str(paper.get("title") or "").casefold()))
    elif sort_by == "note_updated_desc":
        results.sort(key=lambda paper: str(paper_note(paper).get("updated_at") or ""), reverse=True)
    else:
        results.sort(key=lambda paper: (bool(paper.get("favorite")), str(paper.get("updated_at") or "")), reverse=True)
    offset = (page - 1) * page_size
    return {"items": [_summary(paper) for paper in results[offset:offset + page_size]], "total": len(results), "page": page, "page_size": page_size}


def active_paper_ids() -> list[int]:
    state = store.snapshot()
    return sorted(int(paper["id"]) for paper in state["papers"].values() if _visible(paper, state))
