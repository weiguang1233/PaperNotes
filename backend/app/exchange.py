from __future__ import annotations

import hashlib
import ast
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from xml.sax.saxutils import escape

from .config import PATHS, save_data_root
from .storage import utc_now
from .library import active_paper_ids, author_display, get_paper
from .storage import store


def _safe_name(value: str, fallback: str = "export") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return (cleaned or fallback)[:120]


def _bib_escape(value: Any) -> str:
    text = str(value or "")
    return text.replace("\\", "\\textbackslash{}") .replace("{", "\\{").replace("}", "\\}").replace("&", "\\&").replace("%", "\\%")


def _ris_escape(value: Any) -> str:
    return re.sub(r"[\r\n]+", " ", str(value or "")).strip()


def _selected_ids(ids: list[int] | None, collection_id: int | None) -> list[int]:
    state = store.snapshot()
    if ids:
        selected = {identifier for identifier in ids if str(identifier) in state["papers"]}
    elif collection_id:
        selected = {int(paper_id) for paper_id, values in state["paper_collections"].items() if collection_id in values}
    else:
        selected = set(active_paper_ids())
    return sorted(selected, key=lambda identifier: (state["papers"][str(identifier)].get("year") or 0, str(state["papers"][str(identifier)].get("title") or "")))


def export_library(fmt: str, ids: list[int] | None = None, collection_id: int | None = None) -> Path:
    fmt = fmt.lower()
    if fmt == "gb":
        fmt = "gbt7714"
    if fmt in {"word", "docx"}:
        fmt = "word"
    if fmt not in {"bibtex", "ris", "markdown", "apa", "gbt7714", "word"}:
        raise ValueError("仅支持 bibtex、ris、apa、gbt7714 或 markdown")
    paper_ids = _selected_ids(ids, collection_id)
    papers = [paper for paper_id in paper_ids if (paper := get_paper(paper_id))]
    stamp = utc_now().replace(":", "-")
    if fmt == "bibtex":
        content = "\n\n".join(_as_bibtex(paper) for paper in papers) + "\n"
        target = PATHS.exports / f"papernote-{stamp}.bib"
        target.write_text(content, encoding="utf-8")
    elif fmt == "ris":
        content = "\n\n".join(_as_ris(paper) for paper in papers) + "\n"
        target = PATHS.exports / f"papernote-{stamp}.ris"
        target.write_text(content, encoding="utf-8")
    elif fmt in {"apa", "gbt7714"}:
        formatter = _as_apa if fmt == "apa" else _as_gbt7714
        content = "\n\n".join(formatter(paper) for paper in papers) + "\n"
        target = PATHS.exports / f"papernote-{stamp}-{fmt}.txt"
        target.write_text(content, encoding="utf-8")
    elif fmt == "word":
        target = PATHS.exports / f"papernote-{stamp}.docx"
        _write_docx_with_headings(target, papers)
    else:
        if len(papers) == 1:
            paper = papers[0]
            name = _safe_name(f"{paper.get('citation_key') or paper['id']}-{paper['title']}", str(paper["id"]))
            target = PATHS.exports / f"{name}.md"
            target.write_text(_as_markdown(paper), encoding="utf-8")
            return target
        folder = PATHS.exports / f"papernote-notes-{stamp}"
        folder.mkdir(parents=True, exist_ok=False)
        for paper in papers:
            name = _safe_name(f"{paper.get('citation_key') or paper['id']}-{paper['title']}", str(paper["id"]))
            (folder / f"{name}.md").write_text(_as_markdown(paper), encoding="utf-8")
        target = PATHS.exports / f"papernote-notes-{stamp}.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for note_file in folder.glob("*.md"):
                archive.write(note_file, note_file.name)
        shutil.rmtree(folder)
    return target


def _write_docx(target: Path, papers: list[dict[str, Any]]) -> None:
    """Write a small, dependency-free DOCX readable by Word and LibreOffice."""
    paragraphs: list[str] = []
    for index, paper in enumerate(papers):
        if index:
            paragraphs.append("")
        paragraphs.extend([
            str(paper.get("title") or "未命名文献"),
            f"作者：{'; '.join(author_display(a) for a in paper.get('authors', [])) or '待补充'}",
            f"年份：{paper.get('year') or '待补充'}    期刊/来源：{paper.get('journal') or '待补充'}",
            f"DOI：{paper.get('doi') or '无'}",
        ])
        if paper.get("abstract"):
            paragraphs.extend(["原文摘要", str(paper["abstract"])])
        note = paper.get("note") or {}
        for label, key in (("摘要（中文译文）", "abstract_zh"), ("研究问题", "research_question"), ("论文思路", "paper_idea"), ("数据集", "datasets"), ("气象变量", "variables"), ("研究区域", "region"), ("时间范围", "time_range"), ("研究方法", "methods"), ("模式/模型", "models"), ("主要结论", "key_findings"), ("局限性", "limitations"), ("可借鉴点", "reusable_ideas"), ("自由笔记", "markdown")):
            if note.get(key):
                paragraphs.extend([label, str(note[key])])
        for excerpt in paper.get("excerpts", []):
            paragraphs.extend([f"摘录（PDF 第 {excerpt['page']} 页）", str(excerpt["text"]), str(excerpt.get("comment") or "")])
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    document = f"<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>{body}<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\"/></w:sectPr></w:body></w:document>"
    content_types = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/></Types>"
    rels = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/></Relationships>"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)


def _docx_paragraph(text: str, style: str | None = None, *, page_break: bool = False) -> str:
    ppr_parts: list[str] = []
    if style:
        ppr_parts.append(f'<w:pStyle w:val="{style}"/>')
    if style is None:
        # First-line indentation and generous line spacing make long Chinese
        # Structured notes read like an article instead of a pasted text dump.
        ppr_parts.append('<w:ind w:firstLine="420"/>')
        ppr_parts.append('<w:spacing w:after="120" w:line="360" w:lineRule="auto"/>')
    elif style == "ListParagraph":
        ppr_parts.append('<w:ind w:left="540" w:hanging="180"/>')
        ppr_parts.append('<w:spacing w:after="80" w:line="360" w:lineRule="auto"/>')
    ppr = f"<w:pPr>{''.join(ppr_parts)}</w:pPr>" if ppr_parts else ""
    run = (
        '<w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="等线"/>'
        '<w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">'
        f'{escape(text)}</w:t></w:r>'
        if text else "<w:r/>"
    )
    if page_break:
        run = '<w:r><w:br w:type="page"/></w:r>'
    return f"<w:p>{ppr}{run}</w:p>"


def _docx_note_blocks(text: str) -> list[tuple[str, str | None]]:
    """Convert Markdown and common paper section labels to Word styles."""
    blocks: list[tuple[str, str | None]] = []
    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            level = min(len(match.group(1)), 4)
            blocks.append((match.group(2), f"Heading{level}"))
            continue
        plain_heading = re.match(
            r"^(?:\u6458\u8981|Abstract|\u5f15\u8a00|Introduction|\u7814\u7a76\u80cc\u666f|Background|"
            r"\u8d44\u6599\u4e0e\u65b9\u6cd5|\u6750\u6599\u4e0e\u65b9\u6cd5|Methods?|\u7814\u7a76\u533a|"
            r"\u6570\u636e\u4e0e\u65b9\u6cd5|Results?|\u7ed3\u679c(?:\u4e0e\u5206\u6790)?|Discussion|"
            r"\u8ba8\u8bba|Conclusions?|\u7ed3\u8bba)$",
            line,
            re.I,
        )
        if plain_heading:
            blocks.append((line, "Heading2"))
            continue
        numbered = re.match(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+(.+?)\s*$", line)
        if numbered and len(line) <= 140 and not numbered.group(2).endswith(("。", "！", "？", ".", "!", "?")):
            # Do not turn values such as ``1.3 km resolution`` into headings.
            if not re.match(r"^(?:km|m|mm|cm|k|°|%)\b", numbered.group(2), re.I):
                level = min(numbered.group(1).count(".") + 1, 4)
                blocks.append((line, f"Heading{level}"))
                continue
        lettered = re.match(r"^([a-zA-Z])[.)]\s+(.+?)\s*$", line)
        if lettered and len(line) <= 120 and not lettered.group(2).endswith(("。", "！", "？", ".", "!", "?")):
            blocks.append((line, "Heading2"))
        elif re.match(r"^(?:[-*•]|\d+[.)])\s+", line):
            blocks.append((re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", line), "ListParagraph"))
        else:
            blocks.append((line, None))
    return blocks


def _readable_block(value: Any) -> str:
    """Render old JSON/Python-list note values as Markdown-friendly text."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                parsed = None
        if isinstance(parsed, list):
            return "\n".join(f"- {str(item).strip()}" for item in parsed if str(item).strip())
    return text


def _write_docx_with_headings(target: Path, papers: list[dict[str, Any]]) -> None:
    """Write a reader-friendly DOCX with Title/Heading 1-4 styles."""
    paragraphs: list[str] = []
    for index, paper in enumerate(papers):
        if index:
            paragraphs.append(_docx_paragraph("", page_break=True))
        paragraphs.append(_docx_paragraph(str(paper.get("title") or "未命名文献"), "Title"))
        paragraphs.append(_docx_paragraph("题录信息", "Heading1"))
        metadata_rows = [
            ("作者", "; ".join(author_display(a) for a in paper.get("authors", [])) or "待补充"),
            ("文献类型", {"article": "期刊论文", "thesis": "学位论文", "report": "报告", "book": "书籍/章节", "conference": "会议论文", "dataset": "数据集", "preprint": "预印本", "other": "其他"}.get(paper.get("document_type"), "其他")),
            ("年份", paper.get("year") or "待补充"), ("期刊/来源", paper.get("journal") or "待补充"),
            ("卷", paper.get("volume") or ""), ("期", paper.get("issue") or ""),
            ("页码", paper.get("pages") or ""), ("DOI", paper.get("doi") or "无"),
            ("关键词", "；".join(paper.get("keywords", []))),
        ]
        paragraphs.extend(_docx_paragraph(f"{label}：{value}") for label, value in metadata_rows if value not in (None, ""))
        if paper.get("abstract"):
            paragraphs.append(_docx_paragraph("原文摘要", "Heading2"))
            paragraphs.extend(_docx_paragraph(text, style) for text, style in _docx_note_blocks(_readable_block(paper["abstract"])))
        paragraphs.append(_docx_paragraph("科研笔记", "Heading1"))
        note = paper.get("note") or {}
        for label, key in (
            ("摘要（中文译文）", "abstract_zh"), ("研究问题", "research_question"), ("论文思路", "paper_idea"), ("数据集", "datasets"), ("气象变量", "variables"),
            ("研究区域", "region"), ("时间范围", "time_range"), ("研究方法", "methods"),
            ("模式 / 模型", "models"), ("主要结论", "key_findings"), ("局限性", "limitations"),
            ("可借鉴点", "reusable_ideas"),
        ):
            if note.get(key):
                paragraphs.append(_docx_paragraph(label, "Heading2"))
                paragraphs.extend(_docx_paragraph(text, style) for text, style in _docx_note_blocks(_readable_block(note[key])))
        if note.get("markdown"):
            paragraphs.append(_docx_paragraph("自由笔记", "Heading2"))
            paragraphs.extend(_docx_paragraph(text, style) for text, style in _docx_note_blocks(_readable_block(note["markdown"])))
        for excerpt in paper.get("excerpts", []):
            paragraphs.append(_docx_paragraph(f"摘录（PDF 第 {excerpt['page']} 页）", "Heading2"))
            paragraphs.extend(_docx_paragraph(text, style) for text, style in _docx_note_blocks(_readable_block(excerpt.get("text") or "")))
            if excerpt.get("comment"):
                paragraphs.extend(_docx_paragraph(text, style) for text, style in _docx_note_blocks(_readable_block(excerpt["comment"])))

    body = "".join(paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
        '</w:sectPr></w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="等线"/><w:sz w:val="22"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="120" w:line="360" w:lineRule="auto"/><w:ind w:firstLine="420"/></w:pPr><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="等线"/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="540" w:hanging="180"/><w:spacing w:after="80" w:line="360" w:lineRule="auto"/></w:pPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:ind w:firstLine="0"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="等线"/><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        + "".join(
            f'<w:style w:type="paragraph" w:styleId="Heading{level}"><w:name w:val="heading {level}"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:outlineLvl w:val="{level - 1}"/><w:keepNext/><w:ind w:firstLine="0"/><w:spacing w:before="{300 if level == 1 else 200}" w:after="120"/></w:pPr><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="等线"/><w:b/><w:sz w:val="{28 - (level - 1) * 2}"/></w:rPr></w:style>'
            for level in range(1, 5)
        )
        + '</w:styles>'
    )
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
        archive.writestr("word/styles.xml", styles)


def _as_bibtex(paper: dict[str, Any]) -> str:
    authors = " and ".join(author_display(author) for author in paper["authors"])
    fields = {
        "title": paper["title"], "author": authors, "year": paper.get("year"), "journal": paper.get("journal"),
        "volume": paper.get("volume"), "number": paper.get("issue"), "pages": paper.get("pages"),
        "doi": paper.get("doi"), "abstract": paper.get("abstract"), "keywords": ", ".join(paper.get("keywords", [])),
    }
    body = ",\n".join(f"  {key} = {{{_bib_escape(value)}}}" for key, value in fields.items() if value not in (None, ""))
    entry_type = {"thesis": "phdthesis", "book": "book", "report": "techreport", "conference": "inproceedings"}.get(paper.get("document_type"), "article")
    return f"@{entry_type}{{{paper.get('citation_key') or 'paper' + str(paper['id'])},\n{body}\n}}"


def _as_ris(paper: dict[str, Any]) -> str:
    ris_type = {"thesis": "THES", "book": "BOOK", "report": "RPRT", "conference": "CONF"}.get(paper.get("document_type"), "JOUR")
    lines = [f"TY  - {ris_type}", f"TI  - {_ris_escape(paper['title'])}"]
    lines.extend(f"AU  - {_ris_escape(author_display(author))}" for author in paper["authors"])
    mapping = [("PY", "year"), ("JO", "journal"), ("VL", "volume"), ("IS", "issue"), ("SP", "pages"), ("DO", "doi"), ("AB", "abstract")]
    lines.extend(f"{code}  - {_ris_escape(paper.get(key))}" for code, key in mapping if paper.get(key) not in (None, ""))
    lines.extend(f"KW  - {_ris_escape(keyword)}" for keyword in paper.get("keywords", []))
    lines.append("ER  -")
    return "\n".join(lines)


def _author_parts(author: dict[str, Any]) -> tuple[str, str]:
    family = str(author.get("family") or "").strip()
    given = str(author.get("given_name") or "").strip()
    literal = str(author.get("literal") or "").strip()
    if not family and literal:
        tokens = literal.split()
        family = tokens[-1]
        given = " ".join(tokens[:-1])
    return family, given


def _apa_author(author: dict[str, Any]) -> str:
    family, given = _author_parts(author)
    initials = " ".join(f"{part[0].upper()}." for part in re.split(r"[\s-]+", given) if part)
    if family and initials:
        return f"{family}, {initials}"
    return family or given


def _apa_authors(authors: list[dict[str, Any]]) -> str:
    names = [_apa_author(author) for author in authors if _apa_author(author)]
    if len(names) > 20:
        names = [*names[:19], "…", names[-1]]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + ", & " + names[-1]


def _gb_author(author: dict[str, Any]) -> str:
    family, given = _author_parts(author)
    initials = " ".join(part[0].upper() for part in re.split(r"[\s-]+", given) if part)
    return " ".join(value for value in (family, initials) if value)


def _gb_authors(authors: list[dict[str, Any]]) -> str:
    names = [_gb_author(author) for author in authors if _gb_author(author)]
    if len(names) > 3:
        return ", ".join(names[:3]) + ", et al"
    return ", ".join(names)


def _as_apa(paper: dict[str, Any]) -> str:
    authors = _apa_authors(paper["authors"]) or "Unknown author"
    year = paper.get("year") or "n.d."
    title = _ris_escape(paper.get("title"))
    reference = f"{authors} ({year}). {title}."
    journal = _ris_escape(paper.get("journal"))
    if journal:
        source = journal
        if paper.get("volume"):
            source += f", {paper['volume']}"
        if paper.get("issue"):
            source += f"({paper['issue']})"
        if paper.get("pages"):
            source += f", {paper['pages']}"
        reference += f" {source}."
    if paper.get("doi"):
        reference += f" https://doi.org/{paper['doi']}"
    return reference


def _as_gbt7714(paper: dict[str, Any]) -> str:
    authors = _gb_authors(paper["authors"]) or "佚名"
    title = _ris_escape(paper.get("title"))
    type_code = {"thesis": "D", "book": "M", "report": "R", "conference": "C", "dataset": "DS"}.get(paper.get("document_type"), "J")
    reference = f"{authors}. {title}[{type_code}]."
    journal = _ris_escape(paper.get("journal"))
    source = journal
    if paper.get("year"):
        source += f", {paper['year']}"
    if paper.get("volume"):
        source += f", {paper['volume']}"
    if paper.get("issue"):
        source += f"({paper['issue']})"
    if paper.get("pages"):
        source += f": {paper['pages']}"
    if source:
        reference += f" {source}."
    if paper.get("doi"):
        reference += f" DOI: {paper['doi']}."
    return reference


def _yaml_string(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _as_markdown(paper: dict[str, Any]) -> str:
    note = paper["note"]
    frontmatter = [
        "---", f"title: {_yaml_string(paper['title'])}",
        f"authors: {_yaml_string([author_display(a) for a in paper['authors']])}",
        f"year: {_yaml_string(paper.get('year'))}", f"document_type: {_yaml_string(paper.get('document_type'))}",
        f"journal: {_yaml_string(paper.get('journal'))}", f"volume: {_yaml_string(paper.get('volume'))}",
        f"issue: {_yaml_string(paper.get('issue'))}", f"pages: {_yaml_string(paper.get('pages'))}",
        f"doi: {_yaml_string(paper.get('doi'))}", f"keywords: {_yaml_string(paper.get('keywords', []))}",
        f"citation_key: {_yaml_string(paper.get('citation_key'))}",
        f"tags: {_yaml_string([tag['name'] for tag in paper['tags']])}", "---", "",
    ]
    sections = [
        ("摘要（中文译文）", "abstract_zh"), ("研究问题", "research_question"), ("论文思路", "paper_idea"), ("数据集", "datasets"), ("气象变量", "variables"),
        ("研究区域", "region"), ("时间范围", "time_range"), ("方法", "methods"),
        ("模式与模型", "models"), ("主要结论", "key_findings"), ("局限性", "limitations"),
        ("可借鉴点", "reusable_ideas"), ("自由笔记", "markdown"),
    ]
    body = [f"# {paper['title']}", "", "## 题录信息", ""]
    metadata_rows = [
        ("作者", "; ".join(author_display(a) for a in paper.get("authors", [])) or "待补充"),
        ("文献类型", {"article": "期刊论文", "thesis": "学位论文", "report": "报告", "book": "书籍/章节", "conference": "会议论文", "dataset": "数据集", "preprint": "预印本", "other": "其他"}.get(paper.get("document_type"), "其他")),
        ("年份", paper.get("year") or "待补充"), ("期刊/来源", paper.get("journal") or "待补充"),
        ("卷", paper.get("volume") or ""), ("期", paper.get("issue") or ""),
        ("页码", paper.get("pages") or ""), ("DOI", paper.get("doi") or "无"),
        ("关键词", "；".join(paper.get("keywords", []))),
    ]
    body.extend(f"- **{label}**：{value}" for label, value in metadata_rows if value not in (None, ""))
    body.append("")
    if paper.get("abstract"):
        body.extend(["## 原文摘要", "", _readable_block(paper["abstract"]), ""])
    body.append("## 科研笔记")
    body.append("")
    for label, key in sections:
        if note.get(key):
            body.extend([f"### {label}", "", _readable_block(note[key]), ""])
    if paper["excerpts"]:
        body.extend(["## 原文摘录（手工补充）", ""])
        for excerpt in paper["excerpts"]:
            body.extend([f"### PDF 第 {excerpt['page']} 页", "", f"> {_readable_block(excerpt['text'])}", ""])
            if excerpt.get("comment"):
                body.extend([f"个人评论：{_readable_block(excerpt['comment'])}", ""])
    return "\n".join(frontmatter + body).rstrip() + "\n"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup() -> tuple[Path, dict[str, Any]]:
    PATHS.ensure()
    stamp = utc_now().replace(":", "-")
    target = PATHS.backups / f"papernote-backup-{stamp}.zip"
    temp_target = target.with_suffix(".zip.part")
    manifest: dict[str, Any] = {"format_version": 3, "storage_mode": "markdown_json", "created_at": utc_now(), "files": []}
    files: list[tuple[Path, str]] = []
    if PATHS.state.is_file():
        files.append((PATHS.state, PATHS.state.name))
    for source_path in PATHS.notes.rglob("*.md"):
        files.append((source_path, str(source_path.relative_to(PATHS.root)).replace("\\", "/")))
    for source_path, archive_name in files:
        manifest["files"].append({"path": archive_name, "size": source_path.stat().st_size, "sha256": _hash_file(source_path)})
    with zipfile.ZipFile(temp_target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for source_path, archive_name in files:
            archive.write(source_path, archive_name)
    temp_target.replace(target)
    return target, manifest


def restore_backup(backup_path: Path, destination_path: Path) -> dict[str, Any]:
    backup_path = backup_path.expanduser().resolve()
    destination_path = destination_path.expanduser().resolve()
    if not backup_path.is_file():
        raise ValueError("备份文件不存在")
    if destination_path == PATHS.root:
        raise ValueError("不能覆盖正在使用的文献库")
    if destination_path.exists() and any(destination_path.iterdir()):
        raise ValueError("恢复目标目录必须为空")
    destination_path.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(backup_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            allowed = {item["path"]: item for item in manifest.get("files", [])}
            for name, item in allowed.items():
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts:
                    raise ValueError("备份中包含不安全路径")
                target = (destination_path / Path(*pure.parts)).resolve()
                if destination_path != target and destination_path not in target.parents:
                    raise ValueError("备份路径越界")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                if target.stat().st_size != item["size"] or _hash_file(target) != item["sha256"]:
                    raise ValueError(f"恢复文件校验失败：{name}")
        save_data_root(destination_path)
        return {"destination": str(destination_path), "restart_required": True, "manifest": manifest}
    except Exception:
        if destination_path.exists() and not any(destination_path.iterdir()):
            destination_path.rmdir()
        raise
