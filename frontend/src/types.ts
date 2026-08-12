export type ReadingStatus = "unread" | "reading" | "read" | "archived";
export type DocumentType = "article" | "thesis" | "report" | "book" | "conference" | "dataset" | "preprint" | "other";

export interface Author { family: string; given_name: string; literal: string }
export interface Note {
  paper_id: number; abstract_zh: string; research_question: string; datasets: string; variables: string;
  region: string; time_range: string; methods: string; models: string;
  key_findings: string; limitations: string; reusable_ideas: string; paper_idea: string; markdown: string;
  updated_at: string;
}
export interface NoteVersion { id: number; paper_id: number; created_at: string }
export interface Excerpt { id: number; paper_id: number; page: number; text: string; comment: string }
export interface Collection { id: number; name: string; description: string; parent_id: number | null; paper_count?: number }
export interface Tag { id: number; name: string; color: string; paper_count?: number }
export interface Relation { id: number; target_paper_id: number; target_title: string; relation_type: string; label: string }
export interface NoteOverview {
  completed_fields: number; total_fields: number; missing_critical: string[];
  preview_field: string; preview_label: string; preview: string; updated_at: string;
  source_is_newer: boolean; needs_update: boolean; status: string;
}
export interface PaperSummary {
  id: number; title: string; authors: Author[]; year: number | null; journal: string;
  doi: string | null; abstract: string; keywords: string[]; language: string;
  reading_status: ReadingStatus; favorite: boolean; citation_key: string;
  metadata_source: string; needs_review: boolean; needs_ocr: boolean; updated_at: string;
  document_type: DocumentType;
  external_source?: string | null;
  external_key?: string | null;
  note_overview: NoteOverview;
}
export interface TrashPaper extends PaperSummary {
  deleted_at: string;
  file_count: number;
  size_bytes: number;
}
export interface RefreshDiff {
  key: string; label: string; kind: "metadata" | "note";
  before: unknown; after: unknown;
}
export interface RefreshPreview {
  paper: PaperDetail; token: string; preview: boolean; diffs: RefreshDiff[];
  note_suggestions: Record<string, string>; message: string;
}
export interface PaperDetail extends PaperSummary {
  volume: string; issue: string; pages: string; manual_fields: string[];
  note: Note; excerpts: Excerpt[]; tags: Tag[];
  collections: Collection[]; relations: Relation[];
  external_source?: string | null; external_library_id?: string | null;
  external_key?: string | null; external_item_url?: string | null;
  external_open_uri?: string | null; external_version?: number | null;
  external_modified_at?: string | null; attachment_url?: string | null;
  deleted_at?: string | null;
}
export interface PagedPapers { items: PaperSummary[]; total: number; page: number; page_size: number }
export interface AppSettings {
  data_root: string; crossref_email: string;
  llm_base_url: string; llm_api_key: string; llm_model: string; llm_configured: boolean;
  zotero_base_url: string; zotero_library_id: string; zotero_api_key: string; zotero_configured: boolean;
  obsidian_vault_path: string; obsidian_folder: string;
  host: string; port: number;
}

export interface IntegrationResult {
  ok?: boolean; connected?: boolean; message: string;
  imported?: number; updated?: number; unchanged?: number; total?: number;
  path?: string;
}
