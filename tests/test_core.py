from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

from backend.app.enrichment import _chat_completions_endpoint, _parse_llm_json_object
from backend.app.integrations import ZoteroConfig, load_zotero_paper_context, map_zotero_item
from backend.app.library import _criteria_match, _parse_search_criteria, _query_matches, _selected_options, note_overview
from backend.app.metadata import clean_keywords, format_note_value
from backend.app import storage
from backend.app import config
from backend.app.config import AppPaths
from backend.app import folder_picker
from backend.app.storage import NOTE_FIELDS, parse_note_identity, parse_note_markdown, render_note_markdown
from scripts.launcher import missing_runtime_dependencies


class JsonResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_launcher_reports_incomplete_first_run_before_starting(monkeypatch):
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str):
        if name == "uvicorn":
            return None
        return real_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    assert missing_runtime_dependencies() == ["uvicorn"]


def test_note_library_location_is_saved_without_discarding_other_config(tmp_path, monkeypatch):
    config_file = tmp_path / "app-config.json"
    config_file.write_text(json.dumps({"window": "keep"}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)
    selected = tmp_path / "portable-notes"

    resolved = config.save_data_root(selected)

    assert resolved == selected.resolve()
    assert selected.is_dir()
    assert json.loads(config_file.read_text(encoding="utf-8")) == {
        "window": "keep",
        "data_root": str(selected.resolve()),
    }
    assert config.data_root_source() == "config"


def test_environment_variable_marks_note_library_location_as_locked(monkeypatch):
    monkeypatch.setenv("PAPERNOTE_DATA_DIR", "D:/External/PaperNoteNotes")
    assert config.data_root_source() == "environment"


def test_windows_folder_picker_uses_initial_path_without_restricting_navigation(monkeypatch):
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="E:\\Research\\PaperNotes\n", stderr="")

    monkeypatch.setattr(folder_picker.platform, "system", lambda: "Windows")
    monkeypatch.setattr(folder_picker.shutil, "which", lambda _: "powershell.exe")
    monkeypatch.setattr(folder_picker.subprocess, "run", fake_run)

    selected = folder_picker.choose_directory(Path("D:/MyCodex/PaperNote/library-data"))

    script = observed["command"][-1]
    assert "FolderBrowserDialog" in script
    assert "RootFolder=[Environment+SpecialFolder]::Desktop" in script
    assert "SelectedPath=$env:PAPERNOTE_PICKER_INITIAL" in script
    assert "BrowseForFolder" not in script
    assert selected == Path("E:/Research/PaperNotes")


def test_markdown_note_round_trip_is_readable_and_complete():
    paper = {"id": 42, "external_key": "ABCD1234", "citation_key": "Xu2024", "title": "Weather paper", "doi": "10.1000/test"}
    note = {"paper_id": 42, **{key: "" for key in NOTE_FIELDS}, "updated_at": "2026-01-01T00:00:00+00:00"}
    note.update({"abstract_zh": "中文摘要", "paper_idea": "背景→问题→方法→结论", "markdown": "### 待办\n\n- 复现实验"})
    content = render_note_markdown(paper, note)
    assert "## 摘要（原文摘要的中文翻译）" in content
    assert "## 论文思路（写作逻辑）" in content
    assert "## 自由笔记" in content
    restored = parse_note_markdown(content, 42)
    assert restored["abstract_zh"] == "中文摘要"
    assert restored["paper_idea"] == "背景→问题→方法→结论"
    assert restored["markdown"].endswith("- 复现实验")


def test_markdown_note_identity_uses_portable_zotero_fields():
    paper = {"id": 42, "external_key": "ABCD1234", "citation_key": "Xu2024", "title": "Weather paper", "doi": "10.1000/test"}
    note = {"paper_id": 42, **{key: "" for key in NOTE_FIELDS}, "updated_at": "2026-01-01T00:00:00+00:00"}
    identity = parse_note_identity(render_note_markdown(paper, note))
    assert identity == {
        "zotero_key": "ABCD1234",
        "citation_key": "Xu2024",
        "doi": "10.1000/test",
        "title": "Weather paper",
    }


def test_copied_note_relinks_after_zotero_item_key_changes(tmp_path, monkeypatch):
    paths = AppPaths.from_root(tmp_path / "portable-data")
    monkeypatch.setattr(storage, "PATHS", paths)
    text_store = storage.TextStore()
    text_store.initialize()

    old_paper = {
        "id": 1, "external_key": "OLDKEY", "citation_key": "Xu2024",
        "title": "Weather paper", "doi": "10.1000/test",
    }
    note = {"paper_id": 1, **{key: "" for key in NOTE_FIELDS}, "updated_at": "2026-01-01T00:00:00+00:00"}
    note["research_question"] = "跨电脑后仍应找到这条科研笔记"
    old_path = paths.notes / "OLDKEY.md"
    old_path.write_text(render_note_markdown(old_paper, note), encoding="utf-8")

    new_paper = {
        "id": 9, "external_key": "NEWKEY", "citation_key": "Xu2024-New",
        "title": "Weather paper", "doi": "10.1000/test", "note_file": "NEWKEY.md",
    }
    assert text_store.find_note_file(new_paper) == old_path
    assert text_store.read_note(new_paper)["research_question"] == "跨电脑后仍应找到这条科研笔记"


def test_zotero_context_reads_indexed_pdf_text_without_downloading_pdf():
    config = ZoteroConfig(base_url="http://127.0.0.1:23119/api", library_id="users/0")
    requests: list[str] = []

    def opener(request: Request, timeout: float):
        url = request.full_url
        requests.append(url)
        if url.endswith("/items/ITEM1"):
            return JsonResponse({
                "key": "ITEM1",
                "data": {
                    "key": "ITEM1", "itemType": "journalArticle", "title": "Weather paper",
                    "abstractNote": "Abstract", "date": "2024", "creators": [],
                },
            })
        if "/items/ITEM1/children" in url:
            return JsonResponse([{
                "key": "PDF1",
                "data": {
                    "key": "PDF1", "parentItem": "ITEM1", "itemType": "attachment",
                    "contentType": "application/pdf", "filename": "paper.pdf",
                },
            }])
        if url.endswith("/items/PDF1/fulltext"):
            return JsonResponse({"content": "Introduction. Observations and numerical experiments."})
        raise AssertionError(url)

    result = load_zotero_paper_context(
        {"external_key": "ITEM1", "external_library_id": "users/0", "abstract": ""},
        config,
        opener=opener,
    )
    assert result["full_text"].startswith("Introduction")
    assert any(url.endswith("/items/PDF1/fulltext") for url in requests)
    assert not any("file" in url.lower() or "download" in url.lower() for url in requests)


def test_zotero_metadata_maps_external_attachment_reference():
    config = ZoteroConfig(library_id="users/0")
    item = {
        "key": "ITEM1",
        "data": {"itemType": "journalArticle", "title": "A paper", "date": "2023"},
    }
    attachment = {
        "key": "PDF1",
        "data": {"itemType": "attachment", "contentType": "application/pdf", "parentItem": "ITEM1"},
    }
    mapped = map_zotero_item(item, config, [attachment])
    assert mapped is not None
    assert mapped["external_source"] == "zotero"
    assert mapped["attachments"][0]["open_uri"].startswith("zotero://open-pdf/")


def test_note_formatting_and_keywords_remain_lightweight():
    assert format_note_value(["ERA5", "站点观测"], "datasets") == "- ERA5\n- 站点观测"
    assert clean_keywords(["rainfall", "doi:10.1000/xyz", "RAINfall"], "10.1000/xyz") == ["rainfall"]


def test_note_overview_marks_missing_and_stale_notes():
    note = {
        "paper_idea": "背景→问题→方法→结论",
        "research_question": "核心科学问题",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    overview = note_overview(note, "2026-02-01T00:00:00+00:00")
    assert overview["completed_fields"] == 2
    assert overview["source_is_newer"] is True
    assert overview["needs_update"] is True
    assert overview["preview_label"] == "论文思路"
    assert "摘要" in overview["missing_critical"]


def test_note_overview_recognises_complete_core_notes():
    note = {
        "abstract_zh": "摘要", "research_question": "问题", "paper_idea": "思路",
        "methods": "方法", "key_findings": "结论", "updated_at": "2026-02-01T00:00:00+00:00",
    }
    overview = note_overview(note, "2026-01-01T00:00:00+00:00")
    assert overview["missing_critical"] == []
    assert overview["needs_update"] is False
    assert overview["status"] == "核心笔记已完成"


def test_multi_filter_options_ignore_unknown_values():
    assert _selected_options("unread,read,unknown", {"unread", "reading", "read"}) == {"unread", "read"}


def test_keyword_matching_supports_and_or_and_phrase_modes():
    searchable = "physics based weather forecast for record breaking extremes".casefold()
    assert _query_matches(searchable, "weather extremes", "all") is True
    assert _query_matches(searchable, "rainfall extremes", "all") is False
    assert _query_matches(searchable, "rainfall extremes", "any") is True
    assert _query_matches(searchable, "weather forecast", "phrase") is True
    assert _query_matches(searchable, "weather extremes", "phrase") is False


def test_structured_search_combines_fields_with_and_logic():
    criteria = _parse_search_criteria(json.dumps([
        {"field": "year", "value": "2025"},
        {"field": "all", "value": "wrf"},
        {"field": "all", "value": "land"},
    ]))
    fields = {
        "year": "2025",
        "title": "WRF-ELM v1.0: a regional climate model",
        "abstract": "land-atmosphere interactions over heterogeneous land use regions",
        "author": "", "journal": "", "keyword": "", "note": "",
    }
    assert _criteria_match(fields, criteria) is True
    assert _criteria_match({**fields, "year": "2024"}, criteria) is False


def test_structured_search_ignores_invalid_and_empty_rows():
    criteria = _parse_search_criteria('[{"field":"title","value":"WRF"},{"field":"bad","value":"x"},{"field":"year","value":""}]')
    assert criteria == [{"field": "title", "value": "WRF"}]


def test_deepseek_endpoint_shape():
    assert _chat_completions_endpoint("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"
    assert _chat_completions_endpoint("https://example.com/v1") == "https://example.com/v1/chat/completions"


def test_llm_json_parser_accepts_strict_fenced_and_explained_objects():
    expected = {"research_question": "核心问题", "datasets": "ERA5"}
    serialized = json.dumps(expected, ensure_ascii=False)
    assert _parse_llm_json_object(serialized) == expected
    assert _parse_llm_json_object(f"```json\n{serialized}\n```") == expected
    assert _parse_llm_json_object(f"以下是 json 结果：\n{serialized}\n请查收") == expected
    assert _parse_llm_json_object([{"type": "text", "text": serialized}]) == expected
