from __future__ import annotations

import json
import os
import subprocess
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import PATHS, PROJECT_ROOT, data_root_source, save_data_root
from .folder_picker import FolderPickerUnavailable, choose_directory
from .storage import NOTE_FIELDS, store, utc_now
from .exchange import create_backup, export_library, restore_backup
from .enrichment import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, apply_refresh_preview, import_external_model_text, refresh_paper, refresh_paper_preview, test_llm_connection
from .integrations import (
    DEFAULT_ZOTERO_LOCAL_API,
    DEFAULT_ZOTERO_LIBRARY,
    ZoteroConfig,
    ZoteroIntegrationError,
    export_paper_to_obsidian,
    fetch_zotero_library,
    sync_papers_to_obsidian,
    test_zotero_connection,
)
from .library import (
    active_paper_ids,
    create_paper_record,
    create_paper_record_in_state,
    generate_citation_key,
    get_note,
    get_paper,
    list_papers,
    normalize_doi,
    note_versions,
    refresh_index,
    restore_note_version,
    save_note,
    search_papers,
    empty_trash,
    ensure_search_index,
    list_trash,
    move_paper_to_trash,
    permanently_delete_paper,
    restore_paper_from_trash,
    update_paper,
)
from .models import (
    AssignIds,
    BackupRestore,
    CollectionCreate,
    DataRootUpdate,
    ExcerptCreate,
    ExportRequest,
    ExternalModelImportPayload,
    NotePayload,
    PaperCreate,
    PaperUpdate,
    PaperRefreshRequest,
    PaperRefreshApplyRequest,
    RelationCreate,
    SettingsUpdate,
    TagCreate,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    ensure_search_index()
    yield


app = FastAPI(
    title="PaperNote API",
    version="1.0.0",
    description="气象科研本地文献与笔记库",
    lifespan=lifespan,
)


def not_found(label: str = "记录") -> HTTPException:
    return HTTPException(status_code=404, detail=f"{label}不存在")


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": app.version, "data_root": str(PATHS.root)}


@app.get("/api/v1/papers")
def papers(page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), review_only: bool = False):
    return list_papers(page, page_size, review_only)


@app.post("/api/v1/papers/batch/trash")
def batch_trash_papers(payload: AssignIds):
    paper_ids = list(dict.fromkeys(identifier for identifier in payload.ids if identifier > 0))
    removed = sum(1 for paper_id in paper_ids if move_paper_to_trash(paper_id))
    return {"requested": len(paper_ids), "removed": removed}


@app.post("/api/v1/papers", status_code=201)
def create_paper(payload: PaperCreate):
    try:
        return create_paper_record(
            payload.model_dump(), [author.model_dump() for author in payload.authors], [],
            ["title", "year", "journal", "doi", "authors", "document_type"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="DOI 或引用键已存在") from exc


@app.get("/api/v1/papers/{paper_id}")
def paper(paper_id: int):
    result = get_paper(paper_id)
    if not result:
        raise not_found("文献")
    return result


@app.patch("/api/v1/papers/{paper_id}")
def patch_paper(paper_id: int, payload: PaperUpdate):
    try:
        result = update_paper(paper_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="DOI 或引用键已被其他文献使用") from exc
    if not result:
        raise not_found("文献")
    return result


@app.post("/api/v1/papers/{paper_id}/refresh")
def refresh_paper_metadata(paper_id: int, payload: PaperRefreshRequest):
    try:
        result = refresh_paper(paper_id, payload)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise not_found("文献")
    return result


@app.post("/api/v1/papers/{paper_id}/refresh/preview")
def preview_paper_refresh(paper_id: int, payload: PaperRefreshRequest):
    try:
        result = refresh_paper_preview(paper_id, payload)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise not_found("文献")
    return result


@app.post("/api/v1/papers/{paper_id}/refresh/apply")
def apply_paper_refresh(paper_id: int, payload: PaperRefreshApplyRequest):
    try:
        result = apply_refresh_preview(paper_id, payload.token, payload.accepted)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise not_found("文献")
    return result


@app.post("/api/v1/papers/{paper_id}/external-model-import")
def external_model_import(paper_id: int, payload: ExternalModelImportPayload):
    try:
        result = import_external_model_text(
            paper_id,
            payload.filename,
            payload.content,
            overwrite_existing=payload.overwrite_existing,
        )
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"无法解析外部模型文件：{exc}") from exc
    if result is None:
        raise not_found("文献")
    return result


@app.delete("/api/v1/papers/{paper_id}", status_code=204)
def delete_paper(paper_id: int):
    if not move_paper_to_trash(paper_id):
        raise not_found("recycle paper")
    return Response(status_code=204)


@app.get("/api/v1/trash")
def trash():
    return list_trash()


@app.post("/api/v1/trash/{paper_id}/restore")
def restore_trash(paper_id: int):
    if not restore_paper_from_trash(paper_id):
        raise not_found("recycle paper")
    return get_paper(paper_id)


@app.delete("/api/v1/trash/{paper_id}", status_code=204)
def delete_trash_item(paper_id: int):
    if not permanently_delete_paper(paper_id):
        raise not_found("recycle paper")
    return Response(status_code=204)


@app.delete("/api/v1/trash", status_code=200)
def clear_trash():
    return {"removed": empty_trash()}


@app.post("/api/v1/papers/{paper_id}/open")
def open_paper(paper_id: int):
    paper = get_paper(paper_id)
    if not paper:
        raise not_found("文献")
    external_target = str(
        paper.get("external_open_uri")
        or paper.get("external_item_url")
        or paper.get("attachment_url")
        or ""
    ).strip()
    if external_target:
        try:
            if os.name == "nt" and external_target.lower().startswith(("zotero:", "obsidian:")):
                os.startfile(external_target)  # type: ignore[attr-defined]
            else:
                webbrowser.open(external_target, new=0, autoraise=True)
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"无法打开外部文献链接：{exc}") from exc
        return {"opened": True, "target": external_target, "external": True}
    raise HTTPException(status_code=422, detail="该文献尚未关联外部文献库，请先同步 Zotero。")


@app.get("/api/v1/search")
def search(
    q: str = "", page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
    year_from: int | None = None, year_to: int | None = None, journal: str | None = None,
    reading_status: str | None = None, tag_id: int | None = None, collection_id: int | None = None,
    needs_review: bool | None = None, needs_ocr: bool | None = None,
    search_in: str = "all", note_status: str | None = None, sort_by: str = "favorite_recent",
):
    return search_papers(
        q, page, page_size, year_from, year_to, journal, reading_status, tag_id,
        collection_id, needs_review, needs_ocr, search_in, note_status, sort_by,
    )


@app.get("/api/v1/notes/{paper_id}")
def note(paper_id: int):
    result = get_note(paper_id)
    if result is None:
        raise not_found("文献")
    return result


@app.put("/api/v1/notes/{paper_id}")
def put_note(paper_id: int, payload: NotePayload):
    result = save_note(paper_id, payload)
    if result is None:
        raise not_found("文献")
    # Obsidian is an optional local mirror.  A failed mirror must never block
    # saving the canonical note in the paper's Markdown file.
    vault = store.setting("obsidian_vault_path")
    if vault:
        try:
            paper = get_paper(paper_id)
            if paper:
                export_paper_to_obsidian(paper, vault, store.setting("obsidian_folder", "PaperNote"))
        except (OSError, ValueError) as exc:
            result = {**result, "obsidian_warning": str(exc)}
    return result


def _zotero_config() -> ZoteroConfig:
    return ZoteroConfig(
        base_url=store.setting("zotero_base_url", DEFAULT_ZOTERO_LOCAL_API),
        library_id=store.setting("zotero_library_id", DEFAULT_ZOTERO_LIBRARY),
        api_key=store.setting("zotero_api_key"),
    )


def _sync_zotero_items(items: list[dict[str, Any]], active_library_id: str | None = None) -> dict[str, Any]:
    """Upsert Zotero metadata into the text catalog; attachments stay external."""
    source_total = len(items)
    existing_state = store.snapshot()
    existing_doi_keys = {str(paper.get("doi")): str(paper.get("external_key") or "") for paper in existing_state["papers"].values() if paper.get("doi")}
    grouped: dict[str, list[dict[str, Any]]] = {}
    canonical_items: list[dict[str, Any]] = []
    for item in items:
        item_doi = normalize_doi(item.get("doi"))
        if item_doi:
            grouped.setdefault(item_doi, []).append(item)
        else:
            canonical_items.append(item)
    duplicates_merged = 0
    for item_doi, candidates in grouped.items():
        preferred_key = existing_doi_keys.get(item_doi, "")
        selected = next((candidate for candidate in candidates if str(candidate.get("external_key") or "") == preferred_key), candidates[0])
        canonical_items.append(selected)
        duplicates_merged += len(candidates) - 1
    items = canonical_items
    normalized_library = active_library_id or (str(items[0].get("external_library_id") or DEFAULT_ZOTERO_LIBRARY) if items else "")
    imported = updated = unchanged = removed = 0
    touched: list[int] = []
    paper_fields = ("title", "year", "journal", "volume", "issue", "pages", "doi", "abstract", "language", "document_type")
    visible_ids: list[int] = []

    # The catalog is one atomic JSON document. Perform the whole Zotero refresh
    # in a single edit so a large library does not rewrite that document once
    # per item (which previously made the button appear to do nothing).
    with store.edit() as state:
        by_external = {
            (
                str(paper.get("external_source") or ""),
                str(paper.get("external_library_id") or ""),
                str(paper.get("external_key") or ""),
            ): paper
            for paper in state["papers"].values()
            if not paper.get("deleted_at") and paper.get("external_key")
        }
        by_doi = {
            str(paper.get("doi")): paper
            for paper in state["papers"].values()
            if not paper.get("deleted_at") and paper.get("doi")
        }

        for item in items:
            external_key = str(item.get("external_key") or "").strip()
            if not external_key:
                continue
            external_source = str(item.get("external_source") or "zotero")
            library_id = str(item.get("external_library_id") or DEFAULT_ZOTERO_LIBRARY)
            doi = normalize_doi(item.get("doi"))
            row = by_external.get((external_source, library_id, external_key))
            if row is None and doi:
                row = by_doi.get(doi)
            attachments = item.get("attachments") if isinstance(item.get("attachments"), list) else []
            authors = item.get("authors") if isinstance(item.get("authors"), list) else []
            keywords = item.get("keywords") if isinstance(item.get("keywords"), list) else []
            attachment_url = next((str(value.get("open_uri") or value.get("external_url") or "").strip() for value in attachments if isinstance(value, dict) and (value.get("open_uri") or value.get("external_url"))), "")
            incoming = {field: item.get(field) for field in paper_fields}
            incoming.update({"doi": doi, "metadata_source": "zotero", "external_source": external_source, "external_library_id": library_id, "external_key": external_key, "external_item_url": str(item.get("external_item_url") or ""), "external_open_uri": str(item.get("external_open_uri") or ""), "external_version": item.get("external_version"), "external_modified_at": str(item.get("external_modified_at") or ""), "attachment_url": attachment_url, "external_present": True})

            if row is None:
                target = create_paper_record_in_state(
                    state, incoming, authors, keywords, check_duplicate_doi=False,
                )
                paper_id = int(target["id"])
                by_external[(external_source, library_id, external_key)] = target
                if doi:
                    by_doi[doi] = target
                imported += 1
                touched.append(paper_id)
            else:
                target = row
                paper_id = int(target["id"])
                manual = set(target.get("manual_fields") or [])
                changed = False
                for field, value in incoming.items():
                    if field in paper_fields and field in manual:
                        continue
                    normalized = "" if value is None and field not in {"year", "external_version", "doi"} else value
                    if target.get(field) != normalized:
                        target[field] = normalized
                        changed = True
                if "authors" not in manual and target.get("authors", []) != authors:
                    target["authors"] = authors
                    changed = True
                if "keywords" not in manual and target.get("keywords", []) != keywords:
                    target["keywords"] = keywords
                    changed = True
                if changed:
                    target["updated_at"] = utc_now()
                    updated += 1
                    touched.append(paper_id)
                else:
                    unchanged += 1
            visible_ids.append(paper_id)

        if normalized_library:
            keep = set(visible_ids)
            for paper in state["papers"].values():
                if paper.get("external_source") == "zotero" and paper.get("external_library_id") == normalized_library and not paper.get("deleted_at") and int(paper["id"]) not in keep and paper.get("external_present", True):
                    paper["external_present"] = False
                    removed += 1
            state["settings"]["zotero_connected"] = "1"
    unique_touched = sorted(set(touched))
    return {
        "imported": imported,
        "updated": updated,
        "unchanged": unchanged,
        "total": source_total,
        "duplicates_merged": duplicates_merged,
        "removed": removed,
        "paper_ids": unique_touched,
    }


@app.post("/api/v1/integrations/zotero/test")
def zotero_test():
    try:
        return test_zotero_connection(_zotero_config())
    except (ValueError, ZoteroIntegrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/integrations/zotero/sync")
def zotero_sync():
    try:
        config = _zotero_config()
        result = fetch_zotero_library(config)
        normalized_library = "/".join(config.library_root.rstrip("/").split("/")[-2:])
        synced = _sync_zotero_items(result["items"], normalized_library)
        return {**synced, "connected": True, "library_version": result.get("library_version"), "skipped": result.get("skipped", 0), "attachment_count": result.get("attachment_count", 0)}
    except (ValueError, ZoteroIntegrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/integrations/zotero/disconnect")
def zotero_disconnect():
    library_id = store.setting("zotero_library_id", DEFAULT_ZOTERO_LIBRARY)
    try:
        normalized_id = ZoteroConfig(library_id=library_id).library_root.rsplit("/", 2)[-2:]
        normalized_library = "/".join(normalized_id)
    except ValueError:
        normalized_library = library_id
    retained = sum(1 for paper in store.snapshot()["papers"].values() if paper.get("external_source") == "zotero" and paper.get("external_library_id") == normalized_library and not paper.get("deleted_at"))
    store.set_setting("zotero_connected", "0")
    return {"disconnected": True, "library_id": normalized_library, "retained_notes": retained}


@app.post("/api/v1/integrations/obsidian/sync")
def obsidian_sync():
    vault = store.setting("obsidian_vault_path")
    if not vault:
        raise HTTPException(status_code=422, detail="请先配置 Obsidian vault 目录")
    ids = active_paper_ids()
    papers = [get_paper(paper_id) for paper_id in ids]
    return sync_papers_to_obsidian([paper for paper in papers if paper], vault, store.setting("obsidian_folder", "PaperNote"))


@app.post("/api/v1/integrations/obsidian/sync/{paper_id}")
def obsidian_sync_paper(paper_id: int):
    vault = store.setting("obsidian_vault_path")
    paper = get_paper(paper_id)
    if not paper:
        raise not_found("文献")
    if not vault:
        raise HTTPException(status_code=422, detail="请先配置 Obsidian vault 目录")
    try:
        return export_paper_to_obsidian(paper, vault, store.setting("obsidian_folder", "PaperNote"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/notes/{paper_id}/versions")
def versions(paper_id: int):
    return note_versions(paper_id)


@app.post("/api/v1/notes/{paper_id}/versions/{version_id}/restore")
def restore_version(paper_id: int, version_id: int):
    result = restore_note_version(paper_id, version_id)
    if result is None:
        raise not_found("笔记版本")
    return result


@app.post("/api/v1/excerpts/{paper_id}", status_code=201)
def add_excerpt(paper_id: int, payload: ExcerptCreate):
    now = utc_now()
    with store.edit() as state:
        if str(paper_id) not in state["papers"]:
            raise not_found("文献")
        excerpt_id = store.next_id(state, "excerpt")
        row = {"id": excerpt_id, "paper_id": paper_id, "page": payload.page, "text": payload.text, "comment": payload.comment, "created_at": now, "updated_at": now}
        state["excerpts"][str(excerpt_id)] = row
    return row


@app.delete("/api/v1/excerpts/{excerpt_id}", status_code=204)
def delete_excerpt(excerpt_id: int):
    with store.edit() as state:
        row = state["excerpts"].pop(str(excerpt_id), None)
        if not row:
            raise not_found("摘录")


@app.get("/api/v1/collections")
def collections():
    state = store.snapshot()
    return sorted(({**item, "paper_count": sum(1 for ids in state["paper_collections"].values() if int(key) in ids)} for key, item in state["collections"].items()), key=lambda item: str(item["name"]).lower())


@app.post("/api/v1/collections", status_code=201)
def create_collection(payload: CollectionCreate):
    with store.edit() as state:
        if any(item.get("parent_id") == payload.parent_id and str(item.get("name")).casefold() == payload.name.strip().casefold() for item in state["collections"].values()):
            raise HTTPException(status_code=409, detail="同级专题名称已存在")
        identifier = store.next_id(state, "collection")
        row = {"id": identifier, "name": payload.name.strip(), "description": payload.description, "parent_id": payload.parent_id, "created_at": utc_now()}
        state["collections"][str(identifier)] = row
    return row


@app.delete("/api/v1/collections/{collection_id}", status_code=204)
def delete_collection(collection_id: int):
    with store.edit() as state:
        if not state["collections"].pop(str(collection_id), None):
            raise not_found("专题")
        for paper_id, ids in state["paper_collections"].items():
            state["paper_collections"][paper_id] = [identifier for identifier in ids if identifier != collection_id]


@app.put("/api/v1/papers/{paper_id}/collections")
def assign_collections(paper_id: int, payload: AssignIds):
    with store.edit() as state:
        if str(paper_id) not in state["papers"]:
            raise not_found("文献")
        state["paper_collections"][str(paper_id)] = sorted({identifier for identifier in payload.ids if str(identifier) in state["collections"]})
    return get_paper(paper_id)["collections"]


@app.get("/api/v1/tags")
def tags():
    state = store.snapshot()
    return sorted(({**item, "paper_count": sum(1 for ids in state["paper_tags"].values() if int(key) in ids)} for key, item in state["tags"].items()), key=lambda item: str(item["name"]).lower())


@app.post("/api/v1/tags", status_code=201)
def create_tag(payload: TagCreate):
    with store.edit() as state:
        if any(str(item.get("name")).casefold() == payload.name.strip().casefold() for item in state["tags"].values()):
            raise HTTPException(status_code=409, detail="标签名称已存在")
        identifier = store.next_id(state, "tag")
        row = {"id": identifier, "name": payload.name.strip(), "color": payload.color, "created_at": utc_now()}
        state["tags"][str(identifier)] = row
    return row


@app.delete("/api/v1/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int):
    with store.edit() as state:
        if not state["tags"].pop(str(tag_id), None):
            raise not_found("标签")
        for paper_id, ids in state["paper_tags"].items():
            state["paper_tags"][paper_id] = [identifier for identifier in ids if identifier != tag_id]


@app.put("/api/v1/papers/{paper_id}/tags")
def assign_tags(paper_id: int, payload: AssignIds):
    with store.edit() as state:
        if str(paper_id) not in state["papers"]:
            raise not_found("文献")
        state["paper_tags"][str(paper_id)] = sorted({identifier for identifier in payload.ids if str(identifier) in state["tags"]})
    return get_paper(paper_id)["tags"]


@app.post("/api/v1/relations", status_code=201)
def create_relation(payload: RelationCreate):
    if payload.source_paper_id == payload.target_paper_id:
        raise HTTPException(status_code=422, detail="文献不能关联自身")
    with store.edit() as state:
        if str(payload.source_paper_id) not in state["papers"] or str(payload.target_paper_id) not in state["papers"]:
            raise HTTPException(status_code=409, detail="目标文献无效")
        if any(int(item["source_paper_id"]) == payload.source_paper_id and int(item["target_paper_id"]) == payload.target_paper_id and item["relation_type"] == payload.relation_type for item in state["relations"].values()):
            raise HTTPException(status_code=409, detail="关联已存在")
        identifier = store.next_id(state, "relation")
        row = {"id": identifier, **payload.model_dump(), "created_at": utc_now()}
        state["relations"][str(identifier)] = row
    return row


@app.delete("/api/v1/relations/{relation_id}", status_code=204)
def delete_relation(relation_id: int):
    with store.edit() as state:
        if not state["relations"].pop(str(relation_id), None):
            raise not_found("关联")


@app.post("/api/v1/exports", status_code=201)
def create_export(payload: ExportRequest):
    try:
        path = export_library(payload.format, payload.paper_ids, payload.collection_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"path": str(path), "filename": path.name, "download_url": f"/api/v1/exports/download/{path.name}"}


@app.get("/api/v1/exports/download/{filename}")
def download_export(filename: str):
    path = (PATHS.exports / filename).resolve()
    if PATHS.exports.resolve() not in path.parents or not path.is_file():
        raise not_found("导出文件")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.post("/api/v1/backups", status_code=201)
def backup():
    path, manifest = create_backup()
    return {"path": str(path), "filename": path.name, "manifest": manifest}


@app.get("/api/v1/backups")
def backups():
    PATHS.ensure()
    return [
        {"name": path.name, "path": str(path), "size": path.stat().st_size, "modified_at": path.stat().st_mtime}
        for path in sorted(PATHS.backups.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
    ]


@app.post("/api/v1/backups/restore")
def restore(payload: BackupRestore):
    try:
        return restore_backup(Path(payload.backup_path), Path(payload.destination_path))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/settings")
def settings():
    return {
        "data_root": str(PATHS.root),
        "data_root_source": data_root_source(),
        "data_root_locked": data_root_source() == "environment",
        "crossref_email": store.setting("crossref_email"),
        "llm_base_url": store.setting("llm_base_url", DEFAULT_LLM_BASE_URL),
        "llm_api_key": store.setting("llm_api_key"),
        "llm_model": store.setting("llm_model", DEFAULT_LLM_MODEL),
        "llm_configured": bool(store.setting("llm_base_url") and store.setting("llm_api_key")),
        "zotero_base_url": store.setting("zotero_base_url", DEFAULT_ZOTERO_LOCAL_API),
        "zotero_library_id": store.setting("zotero_library_id", DEFAULT_ZOTERO_LIBRARY),
        "zotero_api_key": store.setting("zotero_api_key"),
        "zotero_configured": store.setting("zotero_connected", "1") == "1" and bool(store.setting("zotero_base_url") or store.setting("zotero_api_key")),
        "obsidian_vault_path": store.setting("obsidian_vault_path"),
        "obsidian_folder": store.setting("obsidian_folder", "PaperNote"),
        "host": "127.0.0.1",
        "port": 8765,
    }


@app.patch("/api/v1/settings")
def update_settings(payload: SettingsUpdate):
    if payload.crossref_email is not None:
        store.set_setting("crossref_email", payload.crossref_email.strip())
    if payload.llm_base_url is not None:
        store.set_setting("llm_base_url", payload.llm_base_url.strip())
    if payload.llm_api_key is not None and payload.llm_api_key.strip():
        store.set_setting("llm_api_key", payload.llm_api_key.strip())
    if payload.llm_model is not None:
        store.set_setting("llm_model", payload.llm_model.strip())
    if payload.zotero_base_url is not None:
        store.set_setting("zotero_base_url", payload.zotero_base_url.strip() or DEFAULT_ZOTERO_LOCAL_API)
    if payload.zotero_library_id is not None:
        store.set_setting("zotero_library_id", payload.zotero_library_id.strip() or DEFAULT_ZOTERO_LIBRARY)
    if payload.zotero_api_key is not None and payload.zotero_api_key.strip():
        store.set_setting("zotero_api_key", payload.zotero_api_key.strip())
    if payload.obsidian_vault_path is not None:
        store.set_setting("obsidian_vault_path", payload.obsidian_vault_path.strip())
    if payload.obsidian_folder is not None:
        store.set_setting("obsidian_folder", payload.obsidian_folder.strip() or "PaperNote")
    return settings()


@app.post("/api/v1/settings/llm-test")
def llm_test():
    return test_llm_connection()


@app.put("/api/v1/settings/data-root")
def update_data_root(payload: DataRootUpdate):
    if os.environ.get("PAPERNOTE_DATA_DIR"):
        raise HTTPException(
            status_code=409,
            detail="笔记库位置当前由 PAPERNOTE_DATA_DIR 环境变量锁定。请删除或修改该环境变量后重启 PaperNote。",
        )
    path = Path(payload.path)
    try:
        resolved = save_data_root(path)
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"无法使用该目录：{exc}") from exc
    return {"data_root": str(resolved), "restart_required": resolved != PATHS.root}


@app.post("/api/v1/settings/data-root/choose")
def choose_data_root():
    try:
        selected = choose_directory(PATHS.root)
    except (FolderPickerUnavailable, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {"path": str(selected.resolve()) if selected else None}


frontend_dist = next(
    (path for path in (PROJECT_ROOT / "frontend" / "dist-portable", PROJECT_ROOT / "frontend" / "dist") if path.exists()),
    PROJECT_ROOT / "frontend" / "dist-portable",
)
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
