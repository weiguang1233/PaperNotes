from __future__ import annotations

import ast
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_ZOTERO_LOCAL_API = "http://127.0.0.1:23119/api"
DEFAULT_ZOTERO_LIBRARY = "users/0"
ZOTERO_REGULAR_TYPES = {
    "artwork", "audioRecording", "bill", "blogPost", "book", "bookSection",
    "case", "computerProgram", "conferencePaper", "dataset", "dictionaryEntry",
    "document", "email", "encyclopediaArticle", "film", "forumPost", "hearing",
    "instantMessage", "interview", "journalArticle", "letter", "magazineArticle",
    "manuscript", "map", "newspaperArticle", "patent", "podcast", "preprint",
    "presentation", "radioBroadcast", "report", "standard", "statute", "thesis",
    "tvBroadcast", "videoRecording", "webpage",
}
ZOTERO_SKIPPED_TYPES = {"attachment", "note", "annotation"}
AUTHOR_CREATOR_TYPES = {
    "author", "bookAuthor", "inventor", "programmer", "presenter", "cartographer",
    "artist", "composer", "performer", "podcaster", "reviewedAuthor",
}


class ZoteroIntegrationError(RuntimeError):
    """A user-facing Zotero connection or response error."""


@dataclass(frozen=True)
class ZoteroConfig:
    """Connection details for either Zotero's Local API or Web API.

    ``base_url`` may be the API host, a library root, or an ``.../items`` URL.
    Local Zotero therefore works with either the default value or the complete
    URL shown in Zotero's Local API documentation.
    """

    base_url: str = DEFAULT_ZOTERO_LOCAL_API
    library_id: str = DEFAULT_ZOTERO_LIBRARY
    api_key: str = ""
    timeout: float = 20.0

    @property
    def library_root(self) -> str:
        value = self.base_url.strip().rstrip("/") or DEFAULT_ZOTERO_LOCAL_API
        if value.endswith("/items"):
            value = value[:-6]
        if re.search(r"/(?:users|groups)/[^/]+$", value):
            return value
        library_id = normalize_zotero_library_id(self.library_id)
        return f"{value}/{library_id}"

    @property
    def items_url(self) -> str:
        return f"{self.library_root}/items"

    def item_url(self, item_key: str) -> str:
        return f"{self.items_url}/{item_key}"


def normalize_zotero_library_id(value: Any) -> str:
    raw = str(value or DEFAULT_ZOTERO_LIBRARY).strip().strip("/")
    if not raw:
        return DEFAULT_ZOTERO_LIBRARY
    if re.fullmatch(r"\d+", raw):
        return f"users/{raw}"
    if not re.fullmatch(r"(?:users|groups)/[^/]+", raw):
        raise ValueError("Zotero 文献库标识应为 users/<id> 或 groups/<id>")
    return raw


def _with_query(url: str, **params: Any) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items() if value is not None})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _response_headers(response: Any) -> Mapping[str, str]:
    headers = getattr(response, "headers", {})
    return headers if isinstance(headers, Mapping) else dict(headers.items())


def _open_json(
    url: str,
    config: ZoteroConfig,
    opener: Callable[..., Any] = urlopen,
) -> tuple[Any, Mapping[str, str]]:
    headers = {
        "Accept": "application/json",
        "Zotero-API-Version": "3",
        "User-Agent": "PaperNote/1.0",
    }
    if config.api_key.strip():
        headers["Zotero-API-Key"] = config.api_key.strip()
    request = Request(url, headers=headers, method="GET")
    try:
        response = opener(request, timeout=config.timeout)
        with response:
            raw = response.read()
            response_headers = _response_headers(response)
    except HTTPError as exc:
        if exc.code == 403 and "127.0.0.1:23119" in url:
            raise ZoteroIntegrationError(
                "Zotero Local API 未启用；请在 Zotero 设置 → 高级中允许其他应用与 Zotero 通信"
            ) from exc
        if exc.code in {401, 403}:
            raise ZoteroIntegrationError("Zotero API 无权访问该文献库，请核对文献库 ID 与 API Key") from exc
        raise ZoteroIntegrationError(f"Zotero API 返回 HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ZoteroIntegrationError(f"无法连接 Zotero：{reason}") from exc
    try:
        return json.loads(raw.decode("utf-8-sig")), response_headers
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ZoteroIntegrationError("Zotero API 返回了无法识别的数据") from exc


def _next_link(value: str | None) -> str | None:
    if not value:
        return None
    for part in value.split(","):
        match = re.match(r'\s*<([^>]+)>\s*;\s*rel=["\']?([^"\';]+)', part)
        if match and match.group(2).strip().lower() == "next":
            return match.group(1)
    return None


def _fetch_all_items(
    config: ZoteroConfig,
    *,
    since: int | None = None,
    opener: Callable[..., Any] = urlopen,
) -> tuple[list[dict[str, Any]], int | None]:
    url = _with_query(config.items_url, limit=100, start=0, since=since)
    items: list[dict[str, Any]] = []
    version: int | None = None
    visited: set[str] = set()
    for _ in range(10_000):
        if url in visited:
            raise ZoteroIntegrationError("Zotero API 分页链接发生循环")
        visited.add(url)
        payload, headers = _open_json(url, config, opener)
        if not isinstance(payload, list):
            raise ZoteroIntegrationError("Zotero 条目列表格式不正确")
        items.extend(item for item in payload if isinstance(item, dict))
        raw_version = headers.get("Last-Modified-Version") or headers.get("last-modified-version")
        if raw_version:
            try:
                version = int(raw_version)
            except ValueError:
                pass
        url = _next_link(headers.get("Link") or headers.get("link"))
        if not url:
            break
    else:  # pragma: no cover - defensive guard for a broken remote API
        raise ZoteroIntegrationError("Zotero API 分页数量异常")
    return items, version


def _item_data(item: Mapping[str, Any]) -> dict[str, Any]:
    value = item.get("data")
    return dict(value) if isinstance(value, Mapping) else dict(item)


def _year(value: Any) -> int | None:
    match = re.search(r"(?<!\d)(1[4-9]\d{2}|20\d{2}|21\d{2})(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


def _normalize_doi(value: Any) -> str | None:
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value or "").strip(), flags=re.I)
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, flags=re.I)
    return match.group(0).rstrip(".,;)]}").lower() if match else None


def _authors(creators: Any) -> list[dict[str, str]]:
    if not isinstance(creators, list):
        return []
    selected = [creator for creator in creators if isinstance(creator, Mapping) and creator.get("creatorType") in AUTHOR_CREATOR_TYPES]
    if not selected:
        selected = [creator for creator in creators if isinstance(creator, Mapping)]
    result: list[dict[str, str]] = []
    for creator in selected:
        literal = str(creator.get("name") or "").strip()
        family = str(creator.get("lastName") or "").strip()
        given = str(creator.get("firstName") or "").strip()
        if literal or family or given:
            result.append({"family": family, "given_name": given, "literal": literal})
    return result


def _document_type(item_type: str) -> str:
    return {
        "journalArticle": "article",
        "magazineArticle": "article",
        "newspaperArticle": "article",
        "thesis": "thesis",
        "report": "report",
        "book": "book",
        "bookSection": "book",
        "conferencePaper": "conference",
        "presentation": "conference",
        "dataset": "dataset",
        "preprint": "preprint",
    }.get(item_type, "other")


def _library_open_segment(library_id: str) -> str:
    kind, value = normalize_zotero_library_id(library_id).split("/", 1)
    return "library" if kind == "users" else f"groups/{value}"


def _zotero_item_uri(item_key: str, library_id: str) -> str:
    return f"zotero://select/{_library_open_segment(library_id)}/items/{item_key}"


def _zotero_pdf_uri(item_key: str, library_id: str) -> str:
    return f"zotero://open-pdf/{_library_open_segment(library_id)}/items/{item_key}"


def map_zotero_attachment(
    item: Mapping[str, Any],
    config: ZoteroConfig,
) -> dict[str, Any]:
    data = _item_data(item)
    key = str(item.get("key") or data.get("key") or "").strip()
    links = item.get("links") if isinstance(item.get("links"), Mapping) else {}
    enclosure = links.get("enclosure") if isinstance(links.get("enclosure"), Mapping) else {}
    self_link = links.get("self") if isinstance(links.get("self"), Mapping) else {}
    content_type = str(data.get("contentType") or enclosure.get("type") or "").strip()
    return {
        "external_key": key,
        "parent_key": str(data.get("parentItem") or "").strip(),
        "title": str(data.get("title") or "").strip(),
        "filename": str(data.get("filename") or "").strip(),
        "content_type": content_type,
        "link_mode": str(data.get("linkMode") or "").strip(),
        "external_url": str(enclosure.get("href") or self_link.get("href") or (config.item_url(key) if key else "")),
        "open_uri": _zotero_pdf_uri(key, config.library_id) if key and content_type.lower() == "application/pdf" else "",
    }


def map_zotero_item(
    item: Mapping[str, Any],
    config: ZoteroConfig,
    attachments: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    data = _item_data(item)
    item_type = str(data.get("itemType") or "")
    if item_type in ZOTERO_SKIPPED_TYPES or (item_type and item_type not in ZOTERO_REGULAR_TYPES):
        return None
    key = str(item.get("key") or data.get("key") or "").strip()
    title = str(data.get("title") or "").strip()
    if not key or not title:
        return None
    tags = []
    seen_tags: set[str] = set()
    for tag in data.get("tags") or []:
        value = str(tag.get("tag") if isinstance(tag, Mapping) else tag).strip()
        folded = value.casefold()
        if value and folded not in seen_tags:
            tags.append(value)
            seen_tags.add(folded)
    links = item.get("links") if isinstance(item.get("links"), Mapping) else {}
    alternate = links.get("alternate") if isinstance(links.get("alternate"), Mapping) else {}
    source = next(
        (
            str(data.get(field) or "").strip()
            for field in (
                "publicationTitle", "proceedingsTitle", "bookTitle", "university",
                "institution", "publisher", "repository", "websiteTitle",
            )
            if str(data.get(field) or "").strip()
        ),
        "",
    )
    mapped_attachments = [map_zotero_attachment(value, config) for value in attachments]
    return {
        "title": title,
        "authors": _authors(data.get("creators")),
        "year": _year(data.get("date")),
        "journal": source,
        "volume": str(data.get("volume") or "").strip(),
        "issue": str(data.get("issue") or "").strip(),
        "pages": str(data.get("pages") or "").strip(),
        "doi": _normalize_doi(data.get("DOI")),
        "abstract": str(data.get("abstractNote") or "").strip(),
        "keywords": tags,
        "language": str(data.get("language") or "").strip(),
        "document_type": _document_type(item_type),
        "metadata_source": "zotero",
        "external_source": "zotero",
        "external_library_id": normalize_zotero_library_id(config.library_id),
        "external_key": key,
        "external_item_url": str(alternate.get("href") or data.get("url") or config.item_url(key)),
        "external_open_uri": _zotero_item_uri(key, config.library_id),
        "external_version": int(item.get("version") or data.get("version") or 0),
        "external_modified_at": str(data.get("dateModified") or ""),
        "attachments": mapped_attachments,
    }


def fetch_zotero_library(
    config: ZoteroConfig | None = None,
    *,
    since: int | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Read Zotero metadata and external attachment references without files."""

    config = config or ZoteroConfig()
    raw_items, library_version = _fetch_all_items(config, since=since, opener=opener)
    attachments_by_parent: dict[str, list[dict[str, Any]]] = {}
    skipped = 0
    for item in raw_items:
        data = _item_data(item)
        if data.get("itemType") == "attachment":
            parent = str(data.get("parentItem") or "").strip()
            if parent:
                attachments_by_parent.setdefault(parent, []).append(item)
        elif data.get("itemType") in {"note", "annotation"}:
            skipped += 1
    papers: list[dict[str, Any]] = []
    for item in raw_items:
        key = str(item.get("key") or _item_data(item).get("key") or "").strip()
        mapped = map_zotero_item(item, config, attachments_by_parent.get(key, ()))
        if mapped:
            papers.append(mapped)
        elif _item_data(item).get("itemType") != "attachment":
            skipped += 1
    return {
        "items": papers,
        "library_version": library_version,
        "raw_count": len(raw_items),
        "skipped": skipped,
        "attachment_count": sum(len(item["attachments"]) for item in papers),
    }


def test_zotero_connection(
    config: ZoteroConfig | None = None,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    config = config or ZoteroConfig()
    payload, headers = _open_json(_with_query(config.items_url, limit=1, start=0), config, opener)
    if not isinstance(payload, list):
        raise ZoteroIntegrationError("Zotero API 返回的条目列表格式不正确")
    total = headers.get("Total-Results") or headers.get("total-results")
    return {
        "connected": True,
        "items_url": config.items_url,
        "total": int(total) if str(total or "").isdigit() else len(payload),
    }


def _single_item(
    url: str,
    config: ZoteroConfig,
    opener: Callable[..., Any],
) -> dict[str, Any]:
    payload, _ = _open_json(url, config, opener)
    if not isinstance(payload, Mapping):
        raise ZoteroIntegrationError("Zotero 条目格式不正确")
    return dict(payload)


def load_zotero_paper_context(
    paper: Mapping[str, Any],
    config: ZoteroConfig | None = None,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Load current metadata and indexed attachment text only into memory.

    This is intended for PaperNote's one-click note update. No PDF or full text
    is written by this function. If Zotero has no indexed full text, the
    abstract is returned as a transparent fallback.
    """

    key = str(paper.get("external_key") or "").strip()
    if not key:
        raise ZoteroIntegrationError("该文献没有 Zotero external_key")
    library_id = str(paper.get("external_library_id") or DEFAULT_ZOTERO_LIBRARY)
    if config is None:
        config = ZoteroConfig(library_id=library_id)
    elif normalize_zotero_library_id(config.library_id) != normalize_zotero_library_id(library_id):
        config = ZoteroConfig(
            base_url=config.base_url,
            library_id=library_id,
            api_key=config.api_key,
            timeout=config.timeout,
        )
    item = _single_item(config.item_url(key), config, opener)
    children_payload, _ = _open_json(
        _with_query(f"{config.item_url(key)}/children", itemType="attachment", limit=100),
        config,
        opener,
    )
    children = children_payload if isinstance(children_payload, list) else []
    attachment_maps = [map_zotero_attachment(child, config) for child in children if isinstance(child, Mapping)]
    metadata = map_zotero_item(item, config, children) or {}
    ordered = sorted(
        attachment_maps,
        key=lambda value: (value.get("content_type") != "application/pdf", not value.get("external_key")),
    )
    full_text = ""
    attachment_url = ""
    errors: list[str] = []
    for attachment in ordered:
        attachment_key = str(attachment.get("external_key") or "")
        if not attachment_key:
            continue
        if not attachment_url:
            attachment_url = str(attachment.get("open_uri") or attachment.get("external_url") or "")
        try:
            payload, _ = _open_json(f"{config.item_url(attachment_key)}/fulltext", config, opener)
        except ZoteroIntegrationError as exc:
            errors.append(str(exc))
            continue
        if isinstance(payload, Mapping):
            content = str(payload.get("content") or payload.get("fullText") or "").strip()
            if content:
                full_text = content
                break
    message = ""
    if not full_text:
        full_text = str(metadata.get("abstract") or paper.get("abstract") or "").strip()
        message = "Zotero 未提供附件全文，已回退到摘要。" if full_text else "Zotero 未提供可用的附件全文或摘要。"
        if errors:
            message += f" 首个全文读取错误：{errors[0]}"
    return {
        "metadata": metadata,
        "full_text": full_text,
        "attachment_url": attachment_url,
        "message": message,
    }


NOTE_LABELS = (
    ("abstract_zh", "摘要（中文译文）"),
    ("research_question", "研究问题"),
    ("paper_idea", "论文思路"),
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
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{value}" for value in range(1, 10)),
    *(f"LPT{value}" for value in range(1, 10)),
}


def safe_obsidian_filename(value: Any, fallback: str = "paper") -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" ._")
    if not text:
        text = fallback
    if text.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        text = f"_{text}"
    return text[:120].rstrip(" .") or fallback


def _author_display(author: Any) -> str:
    if isinstance(author, Mapping):
        literal = str(author.get("literal") or "").strip()
        if literal:
            return literal
        return " ".join(
            part for part in (
                str(author.get("given_name") or author.get("given") or "").strip(),
                str(author.get("family") or "").strip(),
            ) if part
        )
    return str(author or "").strip()


def _names(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            name = str(value.get("name") or value.get("title") or value.get("label") or "").strip()
        else:
            name = str(value or "").strip()
        if name:
            result.append(name)
    return result


def _readable_note(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(f"- {str(item).strip()}" for item in value if str(item).strip())
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        parsed: Any = None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                pass
        if isinstance(parsed, list):
            return "\n".join(f"- {str(item).strip()}" for item in parsed if str(item).strip())
    return text


def _yaml_scalar(value: Any) -> str:
    return json.dumps(value if value is not None else "", ensure_ascii=False)


def render_obsidian_markdown(paper: Mapping[str, Any]) -> str:
    """Render a complete PaperNote note. Translation data is never included."""

    title = str(paper.get("title") or "未命名文献").strip()
    authors = [name for author in paper.get("authors") or [] if (name := _author_display(author))]
    keywords = [str(value).strip() for value in paper.get("keywords") or [] if str(value).strip()]
    tags = _names(paper.get("tags"))
    collections = _names(paper.get("collections"))
    frontmatter = [
        "---",
        f"papernote_id: {_yaml_scalar(paper.get('id') or '')}",
        f"citation_key: {_yaml_scalar(paper.get('citation_key') or '')}",
        f"title: {_yaml_scalar(title)}",
        f"authors: {_yaml_scalar(authors)}",
        f"year: {_yaml_scalar(paper.get('year') or '')}",
        f"journal: {_yaml_scalar(paper.get('journal') or '')}",
        f"doi: {_yaml_scalar(paper.get('doi') or '')}",
        f"keywords: {_yaml_scalar(keywords)}",
        f"tags: {_yaml_scalar(tags)}",
        f"collections: {_yaml_scalar(collections)}",
        f"external_source: {_yaml_scalar(paper.get('external_source') or '')}",
        f"external_library_id: {_yaml_scalar(paper.get('external_library_id') or '')}",
        f"external_key: {_yaml_scalar(paper.get('external_key') or '')}",
        f"external_item_url: {_yaml_scalar(paper.get('external_item_url') or '')}",
        f"updated_at: {_yaml_scalar(paper.get('updated_at') or '')}",
        "---",
    ]
    lines = [*frontmatter, "", f"# {title}", "", "## 题录信息", ""]
    metadata = (
        ("作者", "; ".join(authors)),
        ("文献类型", paper.get("document_type")),
        ("年份", paper.get("year")),
        ("期刊 / 来源", paper.get("journal")),
        ("卷", paper.get("volume")),
        ("期", paper.get("issue")),
        ("页码", paper.get("pages")),
        ("DOI", paper.get("doi")),
        ("关键词", "; ".join(keywords)),
        ("外部文献链接", paper.get("external_item_url") or paper.get("external_open_uri")),
    )
    for label, value in metadata:
        if value not in (None, ""):
            lines.append(f"- **{label}**：{value}")
    abstract = str(paper.get("abstract") or "").strip()
    if abstract:
        lines.extend(["", "### 原文摘要", "", abstract])
    lines.extend(["", "## 科研笔记", ""])
    note = paper.get("note") if isinstance(paper.get("note"), Mapping) else {}
    for key, label in NOTE_LABELS:
        value = _readable_note(note.get(key))
        if value:
            lines.extend([f"### {label}", "", value, ""])
    excerpts = paper.get("excerpts") if isinstance(paper.get("excerpts"), list) else []
    if excerpts:
        lines.extend(["## 摘录", ""])
        for excerpt in excerpts:
            if not isinstance(excerpt, Mapping):
                continue
            page = excerpt.get("page") or "?"
            lines.extend([f"### PDF 第 {page} 页", "", str(excerpt.get("text") or "").strip()])
            if excerpt.get("comment"):
                lines.extend(["", f"> 个人评论：{str(excerpt['comment']).strip()}"])
            lines.append("")
    relations = paper.get("relations") if isinstance(paper.get("relations"), list) else []
    if relations:
        lines.extend(["## 关联文献", ""])
        for relation in relations:
            if not isinstance(relation, Mapping):
                continue
            label = str(relation.get("label") or relation.get("relation_type") or "关联")
            target = str(relation.get("target_title") or relation.get("target_paper_id") or "未知文献")
            lines.append(f"- **{label}**：{target}")
        lines.append("")
    lines.append(f"<!-- PaperNote: paper_id={paper.get('id') or ''} -->")
    return "\n".join(lines).rstrip() + "\n"


def _obsidian_target(
    paper: Mapping[str, Any],
    vault_path: str | Path,
    subfolder: str = "PaperNote",
) -> tuple[Path, Path]:
    vault = Path(vault_path).expanduser().resolve()
    if not vault.is_dir():
        raise ValueError("Obsidian vault 目录不存在或不是文件夹")
    relative_folder = Path(subfolder or ".")
    if relative_folder.is_absolute() or relative_folder.drive or ".." in relative_folder.parts:
        raise ValueError("Obsidian 子目录必须位于 vault 内")
    folder = (vault / relative_folder).resolve()
    if not folder.is_relative_to(vault):
        raise ValueError("Obsidian 子目录越过了 vault 边界")
    folder.mkdir(parents=True, exist_ok=True)
    stable = paper.get("citation_key") or paper.get("external_key") or paper.get("id") or "paper"
    filename = safe_obsidian_filename(f"{stable}-{paper.get('title') or ''}", str(stable)) + ".md"
    target = (folder / filename).resolve()
    if not target.is_relative_to(vault):
        raise ValueError("Obsidian 笔记文件越过了 vault 边界")
    return vault, target


def export_paper_to_obsidian(
    paper: Mapping[str, Any],
    vault_path: str | Path,
    subfolder: str = "PaperNote",
) -> dict[str, Any]:
    vault, target = _obsidian_target(paper, vault_path, subfolder)
    content = render_obsidian_markdown(paper)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    relative = target.relative_to(vault).with_suffix("").as_posix()
    uri = "obsidian://open?" + urlencode({"vault": vault.name, "file": relative})
    return {
        "paper_id": paper.get("id"),
        "path": str(target),
        "relative_path": target.relative_to(vault).as_posix(),
        "obsidian_uri": uri,
        "bytes": len(content.encode("utf-8")),
    }


def sync_papers_to_obsidian(
    papers: Iterable[Mapping[str, Any]],
    vault_path: str | Path,
    subfolder: str = "PaperNote",
) -> dict[str, Any]:
    written: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for paper in papers:
        try:
            written.append(export_paper_to_obsidian(paper, vault_path, subfolder))
        except (OSError, ValueError) as exc:
            errors.append({"paper_id": paper.get("id"), "error": str(exc)})
    return {
        "written": written,
        "errors": errors,
        "count": len(written),
        # Stable names for the UI and automation clients.
        "exported": len(written),
        "failed": len(errors),
    }
