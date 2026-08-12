from __future__ import annotations

import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from .storage import store, utc_now
from .integrations import ZoteroConfig, ZoteroIntegrationError, load_zotero_paper_context
from .library import generate_citation_key, get_paper, save_note, update_paper
from .metadata import NOTE_FIELDS_ORDER, clean_keywords, format_note_value, parse_external_model_file
from .models import NotePayload, PaperRefreshRequest, PaperUpdate


DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"

REFRESH_LABELS = {
    "title": "题名", "authors": "作者", "year": "年份", "journal": "期刊/来源",
    "volume": "卷", "issue": "期", "pages": "页码", "doi": "DOI", "language": "语言",
    "document_type": "文献类型", "abstract": "摘要", "keywords": "关键词",
    "abstract_zh": "摘要（中文译文）", "research_question": "研究问题", "paper_idea": "论文思路（写作逻辑）", "datasets": "数据集",
    "variables": "气象变量", "region": "研究区域", "time_range": "时间范围",
    "methods": "研究方法", "models": "模式/模型", "key_findings": "主要结论",
    "limitations": "局限性", "reusable_ideas": "可借鉴点", "markdown": "自由笔记",
}


def _chat_completions_endpoint(base_url: str) -> str:
    endpoint = base_url.strip().rstrip("/")
    if endpoint.endswith("/chat/completions"):
        return endpoint
    host = urllib.parse.urlparse(endpoint).netloc.lower()
    if host == "api.deepseek.com" or host.endswith(".deepseek.com"):
        return f"{endpoint}/chat/completions"
    if endpoint.endswith("/v1"):
        return f"{endpoint}/chat/completions"
    return f"{endpoint}/v1/chat/completions"


def _parse_llm_json_object(content: Any) -> dict[str, Any]:
    """Accept strict JSON output and recover an object from common wrappers."""
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                value = block.get("text", block.get("content", ""))
                if value:
                    parts.append(str(value))
            elif block:
                parts.append(str(block))
        content = "\n".join(parts)

    raw = str(content or "").lstrip("\ufeff").strip()
    if not raw:
        raise ValueError("empty model response")

    candidates = [raw]
    candidates.extend(
        value.strip()
        for value in re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.I)
        if value.strip()
    )
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        for match in re.finditer(r"\{", candidate):
            try:
                parsed, _ = decoder.raw_decode(candidate[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise ValueError("model response does not contain a JSON object")


def _llm_suggestions(text: str, paper: dict[str, Any], diagnostics: list[str]) -> dict[str, str] | None:
    base_url = store.setting("llm_base_url", DEFAULT_LLM_BASE_URL).strip()
    api_key = store.setting("llm_api_key").strip()
    model = store.setting("llm_model", DEFAULT_LLM_MODEL).strip()
    if not base_url or not api_key or not model:
        diagnostics.append("尚未完整配置大模型接口、模型名称和 API Key。")
        return None
    if not text.strip():
        diagnostics.append("Zotero 没有提供可读的 PDF 索引文本或摘要。")
        return None

    fields = ", ".join(NOTE_FIELDS_ORDER)
    json_example = json.dumps({key: "" for key in NOTE_FIELDS_ORDER}, ensure_ascii=False)
    system_prompt = (
        "你是严谨的气象科研文献助理。只能依据给定论文文本填写结构化科研笔记，不得猜测。"
        "所有说明使用简体中文，数据集、模式名和通用缩写可保留原文。证据不足的字段返回空字符串。"
        "不要抄录参考文献、作者单位、版权、页眉页脚或整段原文。只返回一个 JSON 对象。"
    )
    user_prompt = (
        f"Return one JSON object using exactly this complete template: {json_example}\n"
        "Every value must be a string. Use an empty string when evidence is unavailable. "
        "Do not add Markdown fences or explanations before or after the JSON.\n"
        f"JSON 字段：{fields}\n"
        "abstract_zh 必须忠实翻译下面单独提供的原文摘要，不得改写成摘要总结；若原文摘要已是中文则原样整理，"
        "若原文摘要为空则返回空字符串；research_question 概括核心科学问题；paper_idea 按‘背景与缺口→问题/假设→数据与方法→"
        "结果组织→机制解释→结论与边界’列出论文写作逻辑；datasets 只列实际数据；variables 只列研究变量；"
        "methods 与 models 分开；key_findings 只写有证据的结论；limitations 写明确边界；"
        "reusable_ideas 写可复用的试验或论证设计；markdown 写简洁中文阅读笔记。\n"
        f"题名：{paper.get('title') or ''}\n\n原文摘要：\n{paper.get('source_abstract') or paper.get('abstract') or ''}"
        f"\n\n论文文本：\n{text[:55_000]}"
    )
    request_payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    host = urllib.parse.urlparse(base_url.strip()).netloc.lower()
    if host == "api.deepseek.com" or host.endswith(".deepseek.com"):
        request_payload["thinking"] = {"type": "disabled"}
    request = urllib.request.Request(
        _chat_completions_endpoint(base_url),
        data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        choices = payload.get("choices") or []
        choice = choices[0] if choices else {}
        content = (choice.get("message") or {}).get("content")
        finish_reason = str(choice.get("finish_reason") or "")
        if not content:
            diagnostics.append("大模型返回了空内容，请重新读取；若持续出现，请检查模型名称和账户状态。")
            return None
        try:
            result = _parse_llm_json_object(content)
        except ValueError:
            if finish_reason == "length":
                diagnostics.append("大模型输出达到长度上限而被截断，未能形成完整科研笔记；请重新读取。")
                return None
            raise
        normalized = {key: format_note_value(result.get(key), key)[:12_000] for key in NOTE_FIELDS_ORDER}
        prose = "".join(value for value in normalized.values() if value)
        if prose and len(re.findall(r"[\u3400-\u9fff]", prose)) < max(8, len(prose) // 35):
            diagnostics.append("模型已响应，但没有返回合格的中文结构化科研笔记。")
            return None
        return normalized
    except urllib.error.HTTPError as exc:
        hints = {
            401: "API Key 无效或无权限", 402: "账户余额不足或服务未开通",
            404: "接口地址或模型名称不存在", 429: "请求过于频繁，请稍后重试",
        }
        diagnostics.append(f"大模型 API 返回 HTTP {exc.code}：{hints.get(exc.code, '服务端请求失败')}。")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = str(getattr(exc, "reason", exc)).strip()
        diagnostics.append(f"无法连接大模型 API{f'（{reason[:160]}）' if reason else ''}，请检查网络、代理和接口地址。")
    except (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError):
        diagnostics.append("大模型返回内容不是可解析的结构化 JSON。")
    return None


def test_llm_connection() -> dict[str, Any]:
    diagnostics: list[str] = []
    result = _llm_suggestions(
        "这是一段接口连通性测试文本，不包含真实文献内容。",
        {"title": "接口连通性测试"},
        diagnostics,
    )
    return {
        "ok": bool(result),
        "base_url": store.setting("llm_base_url", DEFAULT_LLM_BASE_URL).strip(),
        "model": store.setting("llm_model", DEFAULT_LLM_MODEL).strip(),
        "message": "大模型 API 连接成功。" if result else (diagnostics[-1] if diagnostics else "大模型 API 测试失败。"),
    }


def _refresh_compute(paper_id: int, request: PaperRefreshRequest) -> dict[str, Any] | None:
    paper = get_paper(paper_id)
    if not paper:
        return None
    messages: list[str] = []
    source_text = str(paper.get("abstract") or "")
    candidate: dict[str, Any] = {}
    if paper.get("external_source") == "zotero" and paper.get("external_key"):
        config = ZoteroConfig(
            base_url=store.setting("zotero_base_url", "http://127.0.0.1:23119/api"),
            library_id=store.setting("zotero_library_id", paper.get("external_library_id") or "users/0"),
            api_key=store.setting("zotero_api_key", ""),
        )
        try:
            context = load_zotero_paper_context(paper, config)
            candidate.update(context.get("metadata") or {})
            source_text = str(context.get("full_text") or source_text)
            if context.get("message"):
                messages.append(str(context["message"]))
        except ZoteroIntegrationError as exc:
            messages.append(f"无法读取 Zotero PDF 索引文本，已回退到现有摘要：{exc}")
    else:
        messages.append("该文献未关联 Zotero；请先同步外部文献库，才能按 PDF 附件生成完整科研笔记。")

    candidate["keywords"] = clean_keywords(candidate.get("keywords", []), candidate.get("doi") or paper.get("doi"))
    manual = set(paper.get("manual_fields", []))
    metadata_changes: dict[str, Any] = {}
    fields: tuple[str, ...] = ()
    if request.update_metadata:
        fields += ("title", "authors", "year", "journal", "volume", "issue", "pages", "doi", "language", "document_type")
    if request.update_abstract_keywords:
        fields += ("abstract", "keywords")
    for field in fields:
        after = candidate.get(field)
        before = paper.get(field)
        if after in (None, "", []):
            continue
        if field == "keywords":
            before = clean_keywords(before or [], paper.get("doi"))
        if not before or (request.overwrite_existing and field not in manual):
            if before != after:
                metadata_changes[field] = after

    before_note = {key: str(paper["note"].get(key) or "") for key in NOTE_FIELDS_ORDER}
    after_note = {key: format_note_value(value, key) for key, value in before_note.items()}
    suggestions: dict[str, str] = {}
    if request.update_notes:
        if not request.use_llm:
            messages.append("未启用大模型，科研笔记没有生成。")
        else:
            diagnostics: list[str] = []
            source_abstract = str(candidate.get("abstract") or paper.get("abstract") or "").strip()
            suggestions = _llm_suggestions(
                source_text,
                {**paper, **metadata_changes, "source_abstract": source_abstract},
                diagnostics,
            ) or {}
            if not suggestions:
                messages.append(diagnostics[-1] if diagnostics else "大模型没有返回可用的科研笔记。")
            for key, value in suggestions.items():
                if value and not after_note.get(key):
                    after_note[key] = value

    diffs: list[dict[str, Any]] = []
    for key, after in metadata_changes.items():
        diffs.append({"key": key, "label": REFRESH_LABELS[key], "kind": "metadata", "before": paper.get(key), "after": after})
    for key in NOTE_FIELDS_ORDER:
        if before_note[key] != after_note[key]:
            diffs.append({"key": f"note.{key}", "label": REFRESH_LABELS[key], "kind": "note", "before": before_note[key], "after": after_note[key]})
    return {
        "paper": paper,
        "diffs": diffs,
        "payload": {
            "metadata": metadata_changes,
            "metadata_before": {key: paper.get(key) for key in metadata_changes},
            "note_before": before_note,
            "note_after": after_note,
        },
        "note_suggestions": suggestions,
        "messages": messages,
    }


def refresh_paper_preview(paper_id: int, request: PaperRefreshRequest) -> dict[str, Any] | None:
    computed = _refresh_compute(paper_id, request)
    if computed is None:
        return None
    token = secrets.token_urlsafe(24)
    now = utc_now()
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
    with store.edit() as state:
        state["refresh_previews"] = {key: item for key, item in state["refresh_previews"].items() if str(item["expires_at"]) >= now}
        state["refresh_previews"][token] = {"token": token, "paper_id": paper_id, "payload": computed["payload"], "created_at": now, "expires_at": expires}
    return {
        "paper": computed["paper"], "diffs": computed["diffs"], "token": token, "preview": True,
        "note_suggestions": computed["note_suggestions"], "message": "；".join(computed["messages"]),
    }


def _apply_payload(paper_id: int, payload: dict[str, Any], accepted: dict[str, bool]) -> dict[str, Any]:
    paper = get_paper(paper_id)
    if not paper:
        return {"paper": None, "changed": [], "message": "文献不存在。"}
    conflicts: list[str] = []
    metadata_changes: dict[str, Any] = {}
    for key, after in payload.get("metadata", {}).items():
        if not accepted.get(key, False):
            continue
        if paper.get(key) != payload.get("metadata_before", {}).get(key):
            conflicts.append(REFRESH_LABELS.get(key, key))
        else:
            metadata_changes[key] = after
    if metadata_changes:
        update_paper(paper_id, PaperUpdate(**metadata_changes), mark_manual=False)

    current_note = {key: str(paper["note"].get(key) or "") for key in NOTE_FIELDS_ORDER}
    note_changes: dict[str, str] = {}
    for key, after in payload.get("note_after", {}).items():
        if key not in NOTE_FIELDS_ORDER or not accepted.get(f"note.{key}", False):
            continue
        if current_note[key] != payload.get("note_before", {}).get(key, ""):
            conflicts.append(REFRESH_LABELS.get(key, key))
        else:
            note_changes[key] = str(after or "")
    if note_changes:
        save_note(paper_id, NotePayload(**{**current_note, **note_changes, "force_version": True}))
    changed = [*metadata_changes, *(f"note.{key}" for key in note_changes)]
    message = f"已保存 {len(changed)} 项更新。"
    if conflicts:
        message += f" 预览后已被修改的字段已跳过：{', '.join(conflicts)}。"
    return {"paper": get_paper(paper_id), "changed": changed, "note_suggestions": {}, "llm_used": bool(note_changes), "message": message}


def apply_refresh_preview(paper_id: int, token: str, accepted: dict[str, bool]) -> dict[str, Any] | None:
    row = store.snapshot()["refresh_previews"].get(token)
    if not row or int(row["paper_id"]) != paper_id or row["expires_at"] < utc_now():
        raise ValueError("更新预览已过期，请重新生成。")
    result = _apply_payload(paper_id, row["payload"], accepted)
    with store.edit() as state:
        state["refresh_previews"].pop(token, None)
    return result


def refresh_paper(paper_id: int, request: PaperRefreshRequest) -> dict[str, Any] | None:
    computed = _refresh_compute(paper_id, request)
    if computed is None:
        return None
    accepted = {diff["key"]: True for diff in computed["diffs"]}
    return _apply_payload(paper_id, computed["payload"], accepted)


def import_external_model_text(
    paper_id: int, filename: str, content: str, *, overwrite_existing: bool = False,
) -> dict[str, Any] | None:
    paper = get_paper(paper_id)
    if not paper:
        return None
    if not content.strip():
        raise ValueError("导入的笔记文件为空。")
    imported = parse_external_model_file(filename, content)
    provided = set(imported.pop("_provided_fields", set()))
    metadata_changes: dict[str, Any] = {}
    skipped: list[str] = []
    metadata_fields = (
        "title", "authors", "year", "journal", "volume", "issue", "pages", "doi",
        "abstract", "keywords", "language", "citation_key", "document_type",
    )
    for field in metadata_fields:
        value = imported.get(field)
        if field not in provided or value in (None, "", []):
            continue
        if not paper.get(field) or overwrite_existing:
            metadata_changes[field] = value
        else:
            skipped.append(field)
    state = store.snapshot()
    if metadata_changes.get("doi") and any(int(key) != paper_id and item.get("doi") == metadata_changes["doi"] for key, item in state["papers"].items()):
        metadata_changes.pop("doi")
        skipped.append("doi（库内已存在）")
    if metadata_changes.get("citation_key") and any(int(key) != paper_id and item.get("citation_key") == metadata_changes["citation_key"] for key, item in state["papers"].items()):
        metadata_changes["citation_key"] = generate_citation_key(
            None, str(metadata_changes.get("title") or paper.get("title") or "paper"),
            metadata_changes.get("year") or paper.get("year"),
            metadata_changes.get("authors") or paper.get("authors") or [],
        )
    if metadata_changes:
        update_paper(paper_id, PaperUpdate(**metadata_changes), mark_manual=True)

    current_note = {key: str(paper["note"].get(key) or "") for key in NOTE_FIELDS_ORDER}
    imported_note = imported.get("note") or {}
    note_changes: dict[str, str] = {}
    for field in NOTE_FIELDS_ORDER:
        value = str(imported_note.get(field) or "").strip()
        if field not in provided or not value:
            continue
        if not current_note[field] or overwrite_existing:
            note_changes[field] = value
        else:
            skipped.append(f"note.{field}")
    if note_changes:
        save_note(paper_id, NotePayload(**{**current_note, **note_changes, "force_version": True}))
    changed = [*metadata_changes, *(f"note.{key}" for key in note_changes)]
    return {
        "paper": get_paper(paper_id), "changed": changed, "skipped": skipped,
        "message": f"已从 {filename} 导入 {len(changed)} 项资料。" + (f" 保留已有内容 {len(skipped)} 项。" if skipped else ""),
    }
