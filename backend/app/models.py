from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ReadingStatus = Literal["unread", "reading", "read", "archived"]
RelationType = Literal["cites", "extends", "contrasts", "method_related", "custom"]
DocumentType = Literal["article", "thesis", "report", "book", "conference", "dataset", "preprint", "other"]


class Author(BaseModel):
    family: str = ""
    given_name: str = ""
    literal: str = ""


class PaperUpdate(BaseModel):
    title: str | None = None
    authors: list[Author] | None = None
    year: int | None = Field(default=None, ge=1400, le=2200)
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    abstract: str | None = None
    keywords: list[str] | None = None
    language: str | None = None
    reading_status: ReadingStatus | None = None
    favorite: bool | None = None
    citation_key: str | None = None
    needs_review: bool | None = None
    document_type: DocumentType | None = None


class PaperCreate(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    authors: list[Author] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1400, le=2200)
    journal: str = ""
    doi: str | None = None
    document_type: DocumentType = "article"


class NotePayload(BaseModel):
    abstract_zh: str = ""
    research_question: str = ""
    paper_idea: str = ""
    datasets: str = ""
    variables: str = ""
    region: str = ""
    time_range: str = ""
    methods: str = ""
    models: str = ""
    key_findings: str = ""
    limitations: str = ""
    reusable_ideas: str = ""
    markdown: str = ""
    force_version: bool = False


class ExcerptCreate(BaseModel):
    page: int = Field(ge=1)
    text: str = Field(min_length=1)
    comment: str = ""


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    parent_id: int | None = None


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = "#4f6b62"

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        if len(value) != 7 or not value.startswith("#"):
            raise ValueError("颜色必须是 #RRGGBB")
        int(value[1:], 16)
        return value.lower()


class AssignIds(BaseModel):
    ids: list[int] = Field(default_factory=list)


class RelationCreate(BaseModel):
    source_paper_id: int
    target_paper_id: int
    relation_type: RelationType
    label: str = ""

    @field_validator("target_paper_id")
    @classmethod
    def positive_target(cls, value: int) -> int:
        if value < 1:
            raise ValueError("目标文献无效")
        return value


class SettingsUpdate(BaseModel):
    crossref_email: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    zotero_base_url: str | None = None
    zotero_library_id: str | None = None
    zotero_api_key: str | None = None
    obsidian_vault_path: str | None = None
    obsidian_folder: str | None = None


class DataRootUpdate(BaseModel):
    path: str = Field(min_length=1)


class BackupRestore(BaseModel):
    backup_path: str = Field(min_length=1)
    destination_path: str = Field(min_length=1)


class ExportRequest(BaseModel):
    format: Literal["bibtex", "ris", "apa", "gb", "gbt7714", "markdown", "word", "docx"]
    paper_ids: list[int] | None = None
    collection_id: int | None = None


class PaperRefreshRequest(BaseModel):
    update_metadata: bool = True
    update_abstract_keywords: bool = True
    update_notes: bool = True
    overwrite_existing: bool = False
    use_llm: bool = True


class PaperRefreshApplyRequest(BaseModel):
    """Apply only the rows the user accepted in the refresh comparison."""

    token: str = Field(min_length=16, max_length=200)
    accepted: dict[str, bool] = Field(default_factory=dict)


class ExternalModelImportPayload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=20_000_000)
    overwrite_existing: bool = False
