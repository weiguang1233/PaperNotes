import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { api, isServerMode, patchJson, postJson, putJson } from "./api";
import type { AppSettings, Collection, DocumentType, Note, NoteVersion, PagedPapers, PaperDetail, PaperSummary, RefreshDiff, RefreshPreview, Tag, TrashPaper } from "./types";

type View = "library" | "review" | "imports" | "organize" | "trash" | "settings";
type SearchCriterion = { id: number; field: string; value: string };

const SEARCH_FIELD_OPTIONS: [string, string][] = [
  ["all", "全部内容"], ["title", "标题"], ["author", "作者"], ["year", "年份"],
  ["journal", "期刊/来源"], ["abstract", "原文摘要"], ["keyword", "关键词"], ["note", "科研笔记"],
];

const STATUS_LABEL: Record<string, string> = {
  unread: "未读", reading: "在读", read: "已读", archived: "归档",
  queued: "等待中", scanning: "扫描目录", running: "导入中", paused: "已暂停",
  cancelled: "已取消", completed: "已完成", completed_with_errors: "完成，有错误", failed: "失败"
};
const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
  article: "期刊论文", thesis: "学位论文", report: "报告", book: "书籍/章节",
  conference: "会议论文", dataset: "数据集", preprint: "预印本", other: "其他",
};
const NAV: { id: View; label: string; icon: string }[] = [
  { id: "library", label: "文献库", icon: "▤" },
  { id: "review", label: "待复核", icon: "◌" },
  { id: "imports", label: "外部文献", icon: "⇄" },
  { id: "organize", label: "专题与标签", icon: "⌘" },
  { id: "trash", label: "回收站", icon: "♻" },
  { id: "settings", label: "设置与备份", icon: "⚙" },
];

function displayAuthor(author: { family: string; given_name: string; literal: string }) {
  return author.literal || [author.given_name, author.family].filter(Boolean).join(" ");
}

function formatAuthors(paper: PaperSummary) {
  const names = paper.authors.map(displayAuthor).filter(Boolean);
  return names.length > 3 ? `${names.slice(0, 3).join(" · ")} 等` : names.join(" · ");
}

export default function App() {
  const [view, setView] = useState<View>("library");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [data, setData] = useState<PagedPapers>({ items: [], total: 0, page: 1, page_size: 30 });
  const [libraryTotal, setLibraryTotal] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selected, setSelected] = useState<PaperDetail | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [filterStatuses, setFilterStatuses] = useState<string[]>([]);
  const criterionId = useRef(2);
  const paperRequestId = useRef(0);
  const [searchCriteria, setSearchCriteria] = useState<SearchCriterion[]>([{ id: 1, field: "year", value: "" }]);
  const [noteStatuses, setNoteStatuses] = useState<string[]>([]);
  const [documentTypes, setDocumentTypes] = useState<string[]>([]);
  const [sortField, setSortField] = useState("year");
  const [sortDirection, setSortDirection] = useState("desc");
  const [batchMode, setBatchMode] = useState(false);
  const [batchSelected, setBatchSelected] = useState<Set<number>>(new Set());
  const [batchPapers, setBatchPapers] = useState<Map<number, PaperSummary>>(new Map());
  const [batchOpen, setBatchOpen] = useState(false);

  const refreshTaxonomy = async () => {
    const [nextCollections, nextTags] = await Promise.all([
      api<Collection[]>("/api/v1/collections"), api<Tag[]>("/api/v1/tags")
    ]);
    setCollections(nextCollections); setTags(nextTags);
  };

  const loadPapers = async (page = 1) => {
    const requestId = ++paperRequestId.current;
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({ q: query, page: String(page), page_size: "30" });
      if (view === "review") { params.set("needs_review", "true"); }
      if (filterStatuses.length) params.set("reading_status", filterStatuses.join(","));
      const activeCriteria = searchCriteria.filter(item => item.value.trim()).map(({ field, value }) => ({ field, value: value.trim() }));
      if (activeCriteria.length) params.set("criteria", JSON.stringify(activeCriteria));
      if (noteStatuses.length) params.set("note_status", noteStatuses.join(","));
      if (documentTypes.length) params.set("document_types", documentTypes.join(","));
      params.set("sort_by", `${sortField}_${sortDirection}`);
      const [next, allPapers] = await Promise.all([
        api<PagedPapers>(`/api/v1/search?${params}`),
        api<PagedPapers>("/api/v1/papers?page=1&page_size=1"),
      ]);
      if (requestId !== paperRequestId.current) return;
      setData(next);
      setLibraryTotal(allPapers.total);
      if (selectedId && !next.items.some(item => item.id === selectedId)) {
        setSelectedId(null); setSelected(null);
      }
    } catch (reason) {
      if (requestId === paperRequestId.current) setError(reason instanceof Error ? reason.message : "加载失败");
    } finally {
      if (requestId === paperRequestId.current) setLoading(false);
    }
  };

  useEffect(() => { void refreshTaxonomy(); }, []);
  useEffect(() => {
    if (view !== "library" && view !== "review") return;
    const timer = window.setTimeout(() => void loadPapers(1), 260);
    return () => window.clearTimeout(timer);
  }, [query, view, filterStatuses, searchCriteria, noteStatuses, documentTypes, sortField, sortDirection]);

  const submitSearch = () => setQuery(queryInput.trim());
  const clearSearchAndFilters = () => {
    setQueryInput(""); setQuery(""); setSearchCriteria([{ id: criterionId.current++, field: "year", value: "" }]); setFilterStatuses([]);
    setNoteStatuses([]); setDocumentTypes([]); setSortField("year"); setSortDirection("desc");
  };
  const activeCriteria = searchCriteria.filter(item => item.value.trim());
  const hasActiveFilters = Boolean(query || activeCriteria.length || filterStatuses.length || noteStatuses.length || documentTypes.length || sortField !== "year" || sortDirection !== "desc");
  const updateCriterion = (id: number, changes: Partial<SearchCriterion>) => setSearchCriteria(current => current.map(item => item.id === id ? { ...item, ...changes } : item));
  const addCriterion = () => setSearchCriteria(current => [...current, { id: criterionId.current++, field: "all", value: "" }]);
  const removeCriterion = (id: number) => setSearchCriteria(current => current.length === 1 ? [{ ...current[0], value: "" }] : current.filter(item => item.id !== id));

  useEffect(() => {
    if (!selectedId) { setSelected(null); return; }
    setSelected(null);
    api<PaperDetail>(`/api/v1/papers/${selectedId}`).then(setSelected).catch(reason => setError(reason.message));
  }, [selectedId]);

  const onPaperUpdated = (paper: PaperDetail) => {
    setSelected(paper);
    setData(current => ({ ...current, items: current.items.map(item => item.id === paper.id ? paper : item) }));
  };
  const toggleBatchPaper = (paper: PaperSummary) => setBatchSelected(current => {
    const next = new Set(current);
    if (next.has(paper.id)) next.delete(paper.id); else next.add(paper.id);
    setBatchPapers(known => { const updated = new Map(known); if (next.has(paper.id)) updated.set(paper.id, paper); else updated.delete(paper.id); return updated; });
    return next;
  });
  const leaveBatchMode = () => { setBatchMode(false); setBatchSelected(new Set()); setBatchPapers(new Map()); };
  const trashBatchPapers = async () => {
    if (!batchSelected.size || !window.confirm(`确定将所选 ${batchSelected.size} 篇文献移入回收站吗？这只会处理 PaperNote 的题录和科研笔记，不会删除 Zotero 条目或 PDF。`)) return;
    try {
      const result = await postJson<{ requested: number; removed: number }>("/api/v1/papers/batch/trash", { ids: [...batchSelected] });
      leaveBatchMode();
      await loadPapers(data.page);
      setError(result.removed === result.requested ? "" : `已移入回收站 ${result.removed} 篇，另有 ${result.requested - result.removed} 篇未找到。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "批量删除失败"); }
  };

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">P</div><div><strong>PaperNote</strong><span>气象科研文献库</span></div></div>
      <nav>{NAV.map(item => <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => { setView(item.id); setSelectedId(null); leaveBatchMode(); }}>
        <span className="nav-icon">{item.icon}</span>{item.label}
        {item.id === "review" && <em>{data.items.filter(p => p.needs_review || p.needs_ocr).length || ""}</em>}
      </button>)}</nav>
      <div className="sidebar-foot"><span className="status-dot" />{isServerMode ? "Zotero 伴随服务模式" : "离线本地模式"}</div>
    </aside>
    <main className="workspace">
      {(view === "library" || view === "review") && <>
        <header className="topbar">
          <form className="searchbox" onSubmit={event => { event.preventDefault(); submitSearch(); }}><span>⌕</span><input value={queryInput} onChange={event => setQueryInput(event.target.value)} placeholder="输入关键词后按 Enter 搜索…" /><button type="submit">搜索</button>{queryInput && <button type="button" className="search-clear" aria-label="清空搜索词" onClick={() => { setQueryInput(""); setQuery(""); }}>×</button>}</form>
          <MultiFilter label="阅读状态" values={filterStatuses} options={[["unread", "未读"], ["reading", "在读"], ["read", "已读"], ["archived", "归档"]]} onChange={setFilterStatuses} compact />
          <button className="primary" onClick={() => setView("imports")}>⇄ 外部文献</button>
          <button className="icon-button" title="手工新建" onClick={() => setShowCreate(true)}>＋</button>
        </header>
        <section className="library-layout">
          <div className={`paper-pane ${selectedId ? "has-selection" : ""}`}>
            <div className="section-heading"><div><span className="eyebrow">{view === "review" ? "REVIEW QUEUE" : "NOTE LIBRARY"}</span><h1>{view === "review" ? "待复核文献" : "我的文献"}</h1></div><div className="section-heading-actions"><div className="library-count"><strong>{libraryTotal.toLocaleString()}</strong><span>文献总数</span>{(hasActiveFilters || view === "review") && <em>当前结果 {data.total.toLocaleString()} 篇</em>}</div><button className={batchMode ? "active" : ""} onClick={() => { if (batchMode) leaveBatchMode(); else { setBatchMode(true); setSelectedId(null); } }}>{batchMode ? "退出批量选择" : "多选文献"}</button></div></div>
            <div className="library-filterbar">
              <div className="criteria-builder"><div className="criteria-heading"><div><strong>组合检索</strong><span>每行一个条件，所有行需同时满足（AND）</span></div><button type="button" onClick={addCriterion}>＋ 添加条件</button></div><div className="criteria-rows">{searchCriteria.map((item, index) => <div className="criterion-row" key={item.id}><b>{index + 1}</b><select aria-label={`第 ${index + 1} 行检索字段`} value={item.field} onChange={event => updateCriterion(item.id, { field: event.target.value })}>{SEARCH_FIELD_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input aria-label={`第 ${index + 1} 行检索内容`} type={item.field === "year" ? "number" : "text"} min={item.field === "year" ? "1000" : undefined} max={item.field === "year" ? "2100" : undefined} value={item.value} onChange={event => updateCriterion(item.id, { value: event.target.value })} placeholder={item.field === "year" ? "例如 2025" : "输入要匹配的内容"} /><button type="button" aria-label={`删除第 ${index + 1} 行条件`} onClick={() => removeCriterion(item.id)}>×</button></div>)}</div></div>
              <MultiFilter label="文献类型" values={documentTypes} options={Object.entries(DOCUMENT_TYPE_LABEL)} onChange={setDocumentTypes} />
              <MultiFilter label="笔记状态" values={noteStatuses} options={[["complete", "核心笔记完整"], ["incomplete", "笔记待完善"], ["empty", "暂无笔记"], ["stale", "Zotero 后有更新"]]} onChange={setNoteStatuses} />
              <label className="sort-control"><span>排序字段</span><select value={sortField} onChange={event => setSortField(event.target.value)}><option value="year">年份</option><option value="author">作者</option><option value="title">标题</option><option value="journal">期刊/来源</option></select></label>
              <label className="sort-direction"><span>排序方向</span><select value={sortDirection} onChange={event => setSortDirection(event.target.value)}><option value="asc">升序</option><option value="desc">降序</option></select></label>
              {hasActiveFilters && <button className="clear-filters" onClick={clearSearchAndFilters}>清除全部条件</button>}
            </div>
            {hasActiveFilters && <div className="active-filter-summary"><strong>当前采用组合检索</strong><span>各检索行以及其他筛选栏目之间均需同时满足。</span>{query && <em>快速搜索：{query}</em>}{activeCriteria.map((item, index) => <em key={item.id}>{index + 1}. {SEARCH_FIELD_OPTIONS.find(option => option[0] === item.field)?.[1]}：{item.value}</em>)}{filterStatuses.length > 0 && <em>阅读状态 {filterStatuses.length} 项</em>}{documentTypes.length > 0 && <em>文献类型 {documentTypes.length} 项</em>}{noteStatuses.length > 0 && <em>笔记状态 {noteStatuses.length} 项</em>}</div>}
            {error && <div className="error-banner">{error}</div>}
            {batchMode && <div className="batch-select-toolbar"><label><input type="checkbox" checked={data.items.length > 0 && data.items.every(item => batchSelected.has(item.id))} onChange={event => { const checked = event.target.checked; setBatchSelected(current => { const next = new Set(current); data.items.forEach(item => checked ? next.add(item.id) : next.delete(item.id)); return next; }); setBatchPapers(current => { const next = new Map(current); data.items.forEach(item => checked ? next.set(item.id, item) : next.delete(item.id)); return next; }); }} />选择当前页</label><strong>已选 {batchSelected.size} 篇</strong><button className="primary" disabled={!batchSelected.size} onClick={() => setBatchOpen(true)}>一键读所选文献</button><button className="danger" disabled={!batchSelected.size} onClick={() => void trashBatchPapers()}>删除所选到回收站</button></div>}
            {loading ? <Loading /> : data.items.length === 0 ? <EmptyLibrary onImport={() => setView("imports")} /> : <div className="paper-list">
              {data.items.map(paper => <PaperCard key={paper.id} paper={paper} selected={paper.id === selectedId} batchMode={batchMode} checked={batchSelected.has(paper.id)} onToggle={() => toggleBatchPaper(paper)} onClick={() => batchMode ? toggleBatchPaper(paper) : setSelectedId(paper.id)} />)}
            </div>}
            {data.total > data.page_size && <Pagination page={data.page} total={data.total} pageSize={data.page_size} onPage={loadPapers} />}
          </div>
          {selectedId && <aside className="detail-pane">{selected ? <PaperDetailView paper={selected} collections={collections} tags={tags} onUpdated={onPaperUpdated} onDeleted={() => { setSelectedId(null); setSelected(null); void loadPapers(); }} onClose={() => setSelectedId(null)} /> : <Loading />}</aside>}
        </section>
      </>}
      {view === "imports" && <ImportsView onDone={() => { setView("library"); void loadPapers(); }} />}
      {view === "organize" && <OrganizeView collections={collections} tags={tags} refresh={refreshTaxonomy} />}
      {view === "trash" && <TrashView />}
      {view === "settings" && <SettingsView collections={collections} />}
    </main>
    {showCreate && <CreatePaper onClose={() => setShowCreate(false)} onCreated={paper => { setShowCreate(false); setData(current => ({ ...current, items: [paper, ...current.items], total: current.total + 1 })); setLibraryTotal(current => current + 1); setSelectedId(paper.id); }} />}
    {batchOpen && <BatchRefreshDialog papers={[...batchPapers.values()]} onClose={() => setBatchOpen(false)} onPaperUpdated={paper => { onPaperUpdated(paper); }} onFinished={() => { setBatchOpen(false); leaveBatchMode(); void loadPapers(data.page); }} />}
  </div>;
}

function Loading() { return <div className="loading"><i /><span>正在整理资料…</span></div>; }

function EmptyLibrary({ onImport }: { onImport: () => void }) {
  return <div className="empty-state"><div className="empty-orbit"><span>REF</span></div><h2>连接你的文献库</h2><p>从 Zotero 同步题录和附件链接，PaperNote 只在本地保存科研笔记，不复制文献 PDF。</p><button className="primary" onClick={onImport}>连接外部文献库</button></div>;
}

function MultiFilter({ label, values, options, onChange, compact = false }: { label: string; values: string[]; options: [string, string][]; onChange: (values: string[]) => void; compact?: boolean }) {
  const toggle = (value: string) => onChange(values.includes(value) ? values.filter(item => item !== value) : [...values, value]);
  return <details className={`multi-filter ${compact ? "compact" : ""}`}>
    <summary><span>{label}</span><strong>{values.length ? `已选 ${values.length} 项` : `全部${label.replace("状态", "")}`}</strong></summary>
    <div className="multi-filter-menu">
      <div className="multi-filter-head"><b>{label}（可多选）</b>{values.length > 0 && <button type="button" onClick={() => onChange([])}>清空</button>}</div>
      {options.map(([value, text]) => <label key={value}><input type="checkbox" checked={values.includes(value)} onChange={() => toggle(value)} /><span>{text}</span></label>)}
    </div>
  </details>;
}

function PaperCard({ paper, selected, batchMode, checked, onToggle, onClick }: { paper: PaperSummary; selected: boolean; batchMode: boolean; checked: boolean; onToggle: () => void; onClick: () => void }) {
  const note = paper.note_overview;
  const updateReason = note.completed_fields === 0 ? `待补：${note.missing_critical.slice(0, 3).join("、")}${note.missing_critical.length > 3 ? "等" : ""}` : note.source_is_newer ? "Zotero 内容晚于笔记" : note.missing_critical.length ? `待补：${note.missing_critical.slice(0, 3).join("、")}${note.missing_critical.length > 3 ? "等" : ""}` : "核心栏目完整";
  return <div className={`paper-select-row ${batchMode ? "batch" : ""} ${checked ? "checked" : ""}`}>{batchMode && <input className="paper-select-checkbox" type="checkbox" checked={checked} aria-label={`选择 ${paper.title}`} onChange={onToggle} onClick={event => event.stopPropagation()} />}<button className={`paper-card ${selected ? "selected" : ""}`} onClick={onClick}>
    <div className="paper-year">{paper.year || "—"}</div>
    <div className="paper-content"><h3>{paper.title || "未识别题名"}</h3><p>{formatAuthors(paper) || "作者待补充"}</p><div className="paper-meta"><span>{paper.journal || "期刊待补充"}</span><span className="document-type">{DOCUMENT_TYPE_LABEL[paper.document_type] || DOCUMENT_TYPE_LABEL.other}</span><span className={`read-status ${paper.reading_status}`}>{STATUS_LABEL[paper.reading_status]}</span>{paper.needs_ocr && <span className="warn">需 OCR</span>}{paper.needs_review && <span className="warn">待复核</span>}</div><div className={`note-overview ${note.needs_update ? "needs-update" : "complete"}`}><div className="note-overview-head"><strong>{note.status}</strong><span>{note.completed_fields}/{note.total_fields} 栏</span><em>{note.needs_update ? "建议检查" : "暂不需更新"}</em></div>{note.preview && <p><b>{note.preview_label}</b>{note.preview}</p>}<small>{updateReason}{note.updated_at && ` · 笔记 ${new Date(note.updated_at).toLocaleDateString("zh-CN")}`}</small></div></div>
    <div className="paper-tail">{paper.favorite ? "◆" : "›"}</div>
  </button></div>;
}

function Pagination({ page, total, pageSize, onPage }: { page: number; total: number; pageSize: number; onPage: (page: number) => void }) {
  const pages = Math.ceil(total / pageSize);
  const [target, setTarget] = useState(String(page));
  useEffect(() => setTarget(String(page)), [page]);
  const jump = () => { const next = Math.min(pages, Math.max(1, Number.parseInt(target, 10) || page)); setTarget(String(next)); if (next !== page) onPage(next); };
  return <div className="pagination"><button disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</button><span>第</span><input aria-label="跳转页码" type="number" min="1" max={pages} value={target} onChange={event => setTarget(event.target.value)} onKeyDown={event => { if (event.key === "Enter") jump(); }} /><span>页 / 共 {pages} 页</span><button onClick={jump}>跳转</button><button disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</button></div>;
}

function PaperDetailView({ paper, collections, tags, onUpdated, onDeleted, onClose }: { paper: PaperDetail; collections: Collection[]; tags: Tag[]; onUpdated: (paper: PaperDetail) => void; onDeleted: () => void; onClose: () => void }) {
  const [tab, setTab] = useState<"note" | "meta" | "links">("note");
  const [note, setNote] = useState<Note>(paper.note);
  const [saveState, setSaveState] = useState("已保存");
  const [excerpt, setExcerpt] = useState({ page: 1, text: "", comment: "" });
  const [openState, setOpenState] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const [refreshOpen, setRefreshOpen] = useState(false);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshPreview, setRefreshPreview] = useState<RefreshPreview | null>(null);
  const [refreshMessage, setRefreshMessage] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [versions, setVersions] = useState<NoteVersion[]>([]);
  const [externalImportBusy, setExternalImportBusy] = useState(false);
  const [externalImportMessage, setExternalImportMessage] = useState("");
  const externalModelInput = useRef<HTMLInputElement>(null);
  const dirty = useRef(false); const noteRef = useRef(note);
  noteRef.current = note;

  useEffect(() => { setNote(paper.note); dirty.current = false; }, [paper.id, paper.note.updated_at]);
  useEffect(() => {
    if (!dirty.current) return;
    setSaveState("等待保存");
    const timer = window.setTimeout(async () => {
      try { await putJson(`/api/v1/notes/${paper.id}`, note); dirty.current = false; setSaveState("已自动保存"); }
      catch { setSaveState("保存失败"); }
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [note, paper.id]);
  useEffect(() => () => { if (dirty.current) void putJson(`/api/v1/notes/${paper.id}`, { ...noteRef.current, force_version: true }); }, [paper.id]);

  const setField = (field: keyof Note, value: string) => { dirty.current = true; setNote(current => ({ ...current, [field]: value })); };
  const patchPaper = async (changes: Record<string, unknown>) => onUpdated(await patchJson<PaperDetail>(`/api/v1/papers/${paper.id}`, changes));
  const openExternal = async () => { setOpenState(null); try { await postJson(`/api/v1/papers/${paper.id}/open`); setOpenState({ kind: "success", message: "已调用外部文献库打开文献" }); } catch (reason) { setOpenState({ kind: "error", message: reason instanceof Error ? reason.message : "无法打开文献" }); } };
  const refreshMetadata = async (options: { update_metadata: boolean; update_abstract_keywords: boolean; update_notes: boolean; overwrite_existing: boolean; use_llm: boolean }) => {
    setRefreshBusy(true); setRefreshMessage("");
    try {
      const result = await postJson<RefreshPreview>(`/api/v1/papers/${paper.id}/refresh/preview`, options);
      if (result.diffs.length) {
        setRefreshOpen(false);
        setRefreshPreview(result);
      } else {
        setRefreshMessage(result.message || "题录和科研笔记已检查，未发现需要替换的内容。");
      }
    } catch (reason) { setRefreshMessage(reason instanceof Error ? reason.message : "更新失败"); }
    finally { setRefreshBusy(false); }
  };
  const applyRefresh = async (accepted: Record<string, boolean>) => {
    if (!refreshPreview) return;
    setRefreshBusy(true); setRefreshMessage("");
    try {
      const result = await postJson<{ paper: PaperDetail; changed: string[]; llm_used: boolean; message?: string }>(`/api/v1/papers/${paper.id}/refresh/apply`, { token: refreshPreview.token, accepted });
      onUpdated(result.paper); setRefreshPreview(null);
      const summary = result.changed.length ? `已保留 ${result.changed.length} 项更新${result.llm_used ? "（含中文科研笔记）" : ""}` : "未保留任何更新";
      setRefreshMessage([summary, result.message].filter(Boolean).join("；"));
    } catch (reason) { setRefreshMessage(reason instanceof Error ? reason.message : "应用更新失败"); }
    finally { setRefreshBusy(false); }
  };
  const exportSingle = async (format: "markdown" | "word") => {
    try {
      const result = await postJson<{ download_url: string }>("/api/v1/exports", { format, paper_ids: [paper.id] });
      window.location.href = result.download_url;
    } catch (reason) { setOpenState({ kind: "error", message: reason instanceof Error ? reason.message : "导出失败" }); }
  };
  const addExcerpt = async () => {
    if (!excerpt.text.trim()) return;
    await postJson(`/api/v1/excerpts/${paper.id}`, excerpt); setExcerpt({ page: 1, text: "", comment: "" });
    onUpdated(await api<PaperDetail>(`/api/v1/papers/${paper.id}`));
  };
  const openHistory = async () => {
    setHistoryOpen(true); setHistoryBusy(true);
    try { setVersions(await api<NoteVersion[]>(`/api/v1/notes/${paper.id}/versions`)); }
    finally { setHistoryBusy(false); }
  };
  const restoreVersion = async (versionId: number) => {
    setHistoryBusy(true);
    try {
      const restored = await postJson<Note>(`/api/v1/notes/${paper.id}/versions/${versionId}/restore`);
      dirty.current = false; setNote(restored);
      const updated = await api<PaperDetail>(`/api/v1/papers/${paper.id}`);
      onUpdated(updated); setHistoryOpen(false); setSaveState("已恢复历史版本");
    } finally { setHistoryBusy(false); }
  };
  const importNotes = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; event.target.value = "";
    if (!file) return;
    // Confirm means overwrite; cancel still performs a safe blank-field import.
    const overwrite = window.confirm("是否用这个文件替换当前文献中已有的题录和科研笔记？\n\n确定：使用文件内容替换；\n取消：只补充当前为空的项目。\n\n支持直接读回 PaperNote 导出的 Markdown，导入过程不会调用网络 API。");
    setExternalImportBusy(true); setExternalImportMessage("");
    try {
      const result = await postJson<{ paper: PaperDetail; changed: string[]; skipped: string[]; message: string }>(
        `/api/v1/papers/${paper.id}/external-model-import`,
        { filename: file.name, content: await file.text(), overwrite_existing: overwrite },
      );
      onUpdated(result.paper);
      setExternalImportMessage(`${result.message}${result.changed.length ? ` 已更新：${result.changed.join("、")}` : ""}`);
    } catch (reason) {
      setExternalImportMessage(reason instanceof Error ? reason.message : "笔记文件导入失败");
    } finally { setExternalImportBusy(false); }
  };
  const moveToTrash = async () => {
    if (!window.confirm("确定将这篇文献移入回收站吗？外部 Zotero 条目和原始 PDF 不会被删除；回收站中可恢复或永久删除本地笔记记录。")) return;
    try { await api(`/api/v1/papers/${paper.id}`, { method: "DELETE" }); onDeleted(); }
    catch (reason) { setOpenState({ kind: "error", message: reason instanceof Error ? reason.message : "移入回收站失败" }); }
  };
  return <div className="detail-wrap">
    <div className="detail-head"><button className="close" onClick={onClose}>×</button><div className="detail-actions"><button onClick={() => void patchPaper({ favorite: !paper.favorite })}>{paper.favorite ? "◆ 已收藏" : "◇ 收藏"}</button>{paper.external_source && <button onClick={() => void openExternal()}>↗ 打开外部文献</button>}<button title="按 Zotero 附件全文生成题录和科研笔记预览" onClick={() => { setRefreshMessage(""); setRefreshOpen(true); }}>一键读文献</button><input ref={externalModelInput} type="file" hidden accept=".md,.markdown,.txt,.json,application/json,text/markdown,text/plain" onChange={event => void importNotes(event)} /><button title="导入 PaperNote 导出的 Markdown、JSON 或外部整理的笔记文件" disabled={externalImportBusy} onClick={() => externalModelInput.current?.click()}>{externalImportBusy ? "导入中…" : "导入笔记"}</button><button onClick={() => void exportSingle("markdown")}>导出 Markdown</button><button onClick={() => void exportSingle("word")}>导出 Word</button><button className="danger" onClick={() => void moveToTrash()}>删除到回收站</button></div><h2>{paper.title}</h2><p>{formatAuthors(paper)}</p><div className="chips"><span>{paper.year || "年份未知"}</span><span>{DOCUMENT_TYPE_LABEL[paper.document_type] || DOCUMENT_TYPE_LABEL.other}</span>{paper.journal && <span>{paper.journal}</span>}{paper.external_source && <span>外部：{paper.external_source}</span>}{paper.doi && <span>DOI</span>}</div></div>
    {openState && <div className={`${openState.kind}-banner open-status`}>{openState.message}</div>}
    {refreshMessage && !refreshOpen && <div className="success-banner open-status">{refreshMessage}</div>}
    {externalImportMessage && <div className="success-banner open-status">{externalImportMessage}</div>}
    {refreshOpen && <RefreshDialog paper={paper} busy={refreshBusy} resultMessage={refreshMessage} onClose={() => setRefreshOpen(false)} onSubmit={options => void refreshMetadata(options)} />}
    {refreshPreview && <RefreshReviewDialog preview={refreshPreview} busy={refreshBusy} onClose={() => setRefreshPreview(null)} onApply={accepted => void applyRefresh(accepted)} />}
    <div className="detail-tabs"><button className={tab === "note" ? "active" : ""} onClick={() => setTab("note")}>科研笔记</button><button className={tab === "meta" ? "active" : ""} onClick={() => setTab("meta")}>题录信息</button><button className={tab === "links" ? "active" : ""} onClick={() => setTab("links")}>摘录与关联</button><span>{tab === "note" ? saveState : ""}</span></div>
    <div className="detail-body">
      {tab === "note" && <NoteEditor note={note} setField={setField} onHistory={() => void openHistory()} />}
      {tab === "meta" && <MetadataEditor paper={paper} onSave={patchPaper} collections={collections} tags={tags} onUpdated={onUpdated} />}
      {tab === "links" && <>
        <section className="form-section"><h3>添加原文摘录</h3><div className="excerpt-entry"><label>页码<input type="number" min="1" value={excerpt.page} onChange={e => setExcerpt(v => ({ ...v, page: Number(e.target.value) }))} /></label><label className="grow">原文<textarea value={excerpt.text} onChange={e => setExcerpt(v => ({ ...v, text: e.target.value }))} /></label><label className="grow">评论<textarea value={excerpt.comment} onChange={e => setExcerpt(v => ({ ...v, comment: e.target.value }))} /></label><button className="primary small" onClick={() => void addExcerpt()}>保存摘录</button></div></section>
        <section className="form-section"><h3>摘录</h3>{paper.excerpts.length === 0 ? <p className="muted">还没有带页码的摘录。</p> : paper.excerpts.map(item => <article className="excerpt-card" key={item.id}><b>第 {item.page} 页</b><blockquote>{item.text}</blockquote>{item.comment && <p>{item.comment}</p>}</article>)}</section>
        <RelationEditor paper={paper} onUpdated={onUpdated} />
      </>}
    </div>
    {historyOpen && <div className="modal"><div className="dialog history-dialog"><button className="close" onClick={() => setHistoryOpen(false)}>×</button><span className="eyebrow">NOTE HISTORY</span><h2>科研笔记历史</h2><p>自动更新和手工编辑前的版本会保存在这里。恢复后仍可再次回退。</p>{historyBusy ? <Loading /> : versions.length === 0 ? <div className="muted">暂无历史版本</div> : <div className="history-list">{versions.map(version => <div key={version.id}><span>{new Date(version.created_at).toLocaleString("zh-CN")}</span><button disabled={historyBusy} onClick={() => void restoreVersion(version.id)}>恢复此版本</button></div>)}</div>}</div></div>}
  </div>;
}

function RefreshDialog({ paper, busy, resultMessage, onClose, onSubmit }: { paper: PaperDetail; busy: boolean; resultMessage: string; onClose: () => void; onSubmit: (options: { update_metadata: boolean; update_abstract_keywords: boolean; update_notes: boolean; overwrite_existing: boolean; use_llm: boolean }) => void }) {
  const [options, setOptions] = useState(() => ({ update_metadata: true, update_abstract_keywords: true, update_notes: true, overwrite_existing: false, use_llm: true }));
  const toggle = (key: keyof typeof options) => setOptions(current => ({ ...current, [key]: !current[key] }));
  const toggleChineseNotes = () => setOptions(current => ({ ...current, update_notes: !current.update_notes, use_llm: !current.update_notes }));
  return <div className="modal"><div className="dialog refresh-dialog"><button className="close" onClick={onClose}>×</button><span className="eyebrow">READ WITH MODEL</span><h2>一键读取文献并生成科研笔记</h2><p>根据已关联的 Zotero PDF 附件读取可索引全文，在内存中生成题录和科研笔记预览。确认后只保存所选题录与笔记；PDF 和全文不会写入 PaperNote。</p><div className="refresh-options"><label><input type="checkbox" checked={options.update_metadata} onChange={() => toggle("update_metadata")} />补齐空白的题录、作者、年份、期刊和文献类型</label><label><input type="checkbox" checked={options.update_abstract_keywords} onChange={() => toggle("update_abstract_keywords")} />补齐空白的摘要与关键词（自动排除 DOI）</label><label><input type="checkbox" checked={options.update_notes} onChange={toggleChineseNotes} />使用已配置的大模型生成中文科研笔记（只填空白字段）</label><label><input type="checkbox" checked={options.overwrite_existing} onChange={() => toggle("overwrite_existing")} />允许替换已有的非手工题录字段（不影响手工科研笔记）</label></div><small>{paper.external_source ? "当前文献已关联外部文献库；读取过程不复制附件。" : "尚未关联外部文献库，只能使用现有摘要；建议先同步 Zotero。"}</small>{resultMessage && <div className="refresh-result-message" role="status"><strong>检查完成</strong><span>{resultMessage}</span></div>}<div className="dialog-actions"><button className="secondary" onClick={onClose}>{resultMessage ? "完成" : "取消"}</button><button className="primary" disabled={busy || (!options.update_metadata && !options.update_abstract_keywords && !options.update_notes)} onClick={() => onSubmit(options)}>{busy ? "读取并生成预览中…" : resultMessage ? "重新读取" : "生成更新预览"}</button></div></div></div>;
}

function previewValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "（空白）";
  if (Array.isArray(value)) {
    return value.map(item => {
      if (typeof item === "object" && item !== null) {
        const author = item as { literal?: string; given_name?: string; family?: string };
        return author.literal || [author.given_name, author.family].filter(Boolean).join(" ") || JSON.stringify(item);
      }
      return String(item);
    }).filter(Boolean).map(item => `• ${item}`).join("\n");
  }
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function RefreshDiffWorkspace({ diffs, accepted, onToggle }: { diffs: RefreshDiff[]; accepted: Record<string, boolean>; onToggle: (diff: RefreshDiff) => void }) {
  const [activeKey, setActiveKey] = useState(diffs[0]?.key || "");
  useEffect(() => {
    setActiveKey(current => diffs.some(diff => diff.key === current) ? current : (diffs[0]?.key || ""));
  }, [diffs]);

  const activeIndex = Math.max(0, diffs.findIndex(diff => diff.key === activeKey));
  const activeDiff = diffs[activeIndex];
  if (!activeDiff) return <div className="empty-state"><strong>没有可审阅的字段</strong></div>;

  const selectAt = (index: number) => setActiveKey(diffs[Math.max(0, Math.min(index, diffs.length - 1))].key);
  return <div className="refresh-review-body">
    <aside className="refresh-field-list" aria-label="待审阅字段">
      <div className="refresh-field-list-head"><strong>待审阅字段</strong><span>点击字段查看完整内容</span></div>
      {diffs.map((diff, index) => <div className={`refresh-field-item ${diff.key === activeDiff.key ? "active" : ""} ${accepted[diff.key] ? "accepted" : "rejected"}`} key={diff.key}>
        <input aria-label={`采用${diff.label}的更新后内容`} type="checkbox" checked={Boolean(accepted[diff.key])} onChange={() => onToggle(diff)} />
        <button type="button" onClick={() => setActiveKey(diff.key)}>
          <strong>{index + 1}. {diff.label}</strong>
          <span>{diff.kind === "note" ? "科研笔记" : "题录信息"} · {accepted[diff.key] ? "采用更新后" : "保留原内容"}</span>
        </button>
      </div>)}
    </aside>
    <section className="refresh-field-review" aria-live="polite">
      <header className="refresh-field-review-head">
        <div><span>当前字段 {activeIndex + 1} / {diffs.length}</span><h3>{activeDiff.label}</h3></div>
        <label><input type="checkbox" checked={Boolean(accepted[activeDiff.key])} onChange={() => onToggle(activeDiff)} />采用“更新后”内容</label>
      </header>
      <div className="refresh-diff-columns refresh-active-columns">
        <div><small>更新前</small><pre>{previewValue(activeDiff.before)}</pre></div>
        <div><small>更新后</small><pre>{previewValue(activeDiff.after)}</pre></div>
      </div>
      <nav className="refresh-field-nav" aria-label="字段切换">
        <button className="secondary" type="button" disabled={activeIndex === 0} onClick={() => selectAt(activeIndex - 1)}>← 上一项</button>
        <span>{activeIndex + 1} / {diffs.length}</span>
        <button className="secondary" type="button" disabled={activeIndex === diffs.length - 1} onClick={() => selectAt(activeIndex + 1)}>下一项 →</button>
      </nav>
    </section>
  </div>;
}

function RefreshReviewDialog({ preview, busy, onClose, onApply }: { preview: RefreshPreview; busy: boolean; onClose: () => void; onApply: (accepted: Record<string, boolean>) => void }) {
  const [accepted, setAccepted] = useState<Record<string, boolean>>(() => Object.fromEntries(preview.diffs.map(diff => [diff.key, true])));
  useEffect(() => setAccepted(Object.fromEntries(preview.diffs.map(diff => [diff.key, true]))), [preview.token]);
  const acceptedCount = preview.diffs.filter(diff => accepted[diff.key]).length;
  const toggle = (diff: RefreshDiff) => setAccepted(current => ({ ...current, [diff.key]: !current[diff.key] }));
  return <div className="modal review-workspace"><div className="dialog refresh-review-dialog"><button className="close" onClick={onClose}>×</button><span className="eyebrow">REVIEW CHANGES</span><h2>确认一键更新内容</h2><p>左侧选择字段，右侧始终完整显示当前字段的更新前后内容。勾选表示采用“更新后”版本；未勾选则保留原内容。</p>{preview.message && <div className="warning-banner">{preview.message}</div>}<RefreshDiffWorkspace diffs={preview.diffs} accepted={accepted} onToggle={toggle} /><div className="dialog-actions"><span className="muted">已选择 {acceptedCount} / {preview.diffs.length} 项</span><button className="secondary" disabled={busy} onClick={onClose}>取消</button><button className="primary" disabled={busy} onClick={() => onApply(accepted)}>{busy ? "保存中…" : "保留所选并保存"}</button></div></div></div>;
}

type BatchRefreshStatus = { paperId: number; title: string; kind: "saved" | "unchanged" | "skipped" | "error"; message: string };
type BatchRefreshStrategy = "review" | "auto_accept";

function BatchRefreshDialog({ papers, onClose, onPaperUpdated, onFinished }: { papers: PaperSummary[]; onClose: () => void; onPaperUpdated: (paper: PaperDetail) => void; onFinished: () => void }) {
  const [phase, setPhase] = useState<"ready" | "loading" | "review" | "done">("ready");
  const [currentIndex, setCurrentIndex] = useState(0);
  const [preview, setPreview] = useState<RefreshPreview | null>(null);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [statuses, setStatuses] = useState<BatchRefreshStatus[]>([]);
  const [progressTitle, setProgressTitle] = useState("");
  const [strategy, setStrategy] = useState<BatchRefreshStrategy>("review");

  useEffect(() => {
    if (preview) setAccepted(Object.fromEntries(preview.diffs.map(diff => [diff.key, true])));
  }, [preview?.token]);

  const record = (paper: PaperSummary, kind: BatchRefreshStatus["kind"], message: string) => {
    setStatuses(current => [...current, { paperId: paper.id, title: paper.title, kind, message }]);
  };
  const readFrom = async (startIndex: number) => {
    setPhase("loading"); setPreview(null);
    for (let index = startIndex; index < papers.length; index += 1) {
      const paper = papers[index];
      setCurrentIndex(index); setProgressTitle(paper.title);
      try {
        const result = await postJson<RefreshPreview>(`/api/v1/papers/${paper.id}/refresh/preview`, { update_metadata: true, update_abstract_keywords: true, update_notes: true, overwrite_existing: false, use_llm: true });
        if (result.diffs.length) {
          if (strategy === "auto_accept") {
            const acceptedAll = Object.fromEntries(result.diffs.map(diff => [diff.key, true]));
            setProgressTitle(`正在默认确认并保存：${paper.title}`);
            const saved = await postJson<{ paper: PaperDetail; changed: string[]; message?: string }>(`/api/v1/papers/${paper.id}/refresh/apply`, { token: result.token, accepted: acceptedAll });
            onPaperUpdated(saved.paper);
            record(paper, "saved", saved.changed.length ? `默认确认并保存 ${saved.changed.length} 项` : "没有需要保存的字段");
            continue;
          }
          setPreview(result); setPhase("review"); return;
        }
        record(paper, "unchanged", result.message || "未发现需要替换的内容");
      } catch (reason) {
        record(paper, "error", reason instanceof Error ? reason.message : "读取失败");
      }
    }
    setPhase("done"); setProgressTitle("");
  };
  const applyCurrent = async () => {
    const paper = papers[currentIndex];
    if (!paper || !preview) return;
    setPhase("loading"); setProgressTitle(`正在保存：${paper.title}`);
    try {
      const result = await postJson<{ paper: PaperDetail; changed: string[]; message?: string }>(`/api/v1/papers/${paper.id}/refresh/apply`, { token: preview.token, accepted });
      onPaperUpdated(result.paper);
      record(paper, "saved", result.changed.length ? `已保存 ${result.changed.length} 项` : "未选择需要保存的字段");
    } catch (reason) {
      record(paper, "error", reason instanceof Error ? reason.message : "保存失败");
    }
    await readFrom(currentIndex + 1);
  };
  const skipCurrent = async () => {
    const paper = papers[currentIndex];
    if (paper) record(paper, "skipped", "已跳过，未修改");
    await readFrom(currentIndex + 1);
  };
  const acceptedCount = preview?.diffs.filter(diff => accepted[diff.key]).length || 0;
  const statusLabel: Record<BatchRefreshStatus["kind"], string> = { saved: "已保存", unchanged: "无变化", skipped: "已跳过", error: "失败" };

  return <div className="modal"><div className="dialog refresh-review-dialog batch-refresh-dialog"><button className="close" disabled={phase === "loading"} onClick={onClose}>×</button><span className="eyebrow">BATCH READ</span><h2>批量一键读文献</h2><p>按顺序读取所选文献。可以逐篇核对，也可以默认确认所有模型建议并自动保存；不会保存 PDF 或全文，手工摘录与关联始终不会被修改。</p>
    {phase === "ready" && <div className="batch-ready"><strong>已选择 {papers.length} 篇文献</strong><div className="batch-strategy" role="radiogroup" aria-label="批量更新确认方式"><label className={strategy === "review" ? "selected" : ""}><input type="radio" name="batch-strategy" checked={strategy === "review"} onChange={() => setStrategy("review")} /><span><strong>逐篇确认</strong><small>每篇展示新旧对比，由你选择字段后保存。适合需要仔细校正的文献。</small></span></label><label className={strategy === "auto_accept" ? "selected" : ""}><input type="radio" name="batch-strategy" checked={strategy === "auto_accept"} onChange={() => setStrategy("auto_accept")} /><span><strong>默认确认并自动保存</strong><small>每篇自动采用全部模型建议并继续下一篇，不再逐篇停下来确认。</small></span></label></div>{strategy === "auto_accept" && <div className="warning-banner">自动模式会保存每篇文献的全部模型建议字段。已有手工笔记仍受保护，中文文献和综述类文献仍按既定规则跳过。</div>}<div className="batch-paper-preview">{papers.map((paper, index) => <span key={paper.id}>{index + 1}. {paper.title}</span>)}</div><div className="dialog-actions"><button className="secondary" onClick={onClose}>取消</button><button className="primary" disabled={!papers.length} onClick={() => void readFrom(0)}>{strategy === "auto_accept" ? "开始并默认确认" : "开始逐篇核对"}</button></div></div>}
    {phase === "loading" && <div className="batch-progress"><Loading /><strong>{currentIndex + 1} / {papers.length}</strong><span>{progressTitle}</span><small>{strategy === "auto_accept" ? "正在调用模型并自动保存建议，请保持此窗口打开。" : "正在调用模型并整理更新预览，请保持此窗口打开。"}</small></div>}
    {phase === "review" && preview && <><div className="batch-current"><strong>{currentIndex + 1} / {papers.length}</strong><span>{papers[currentIndex]?.title}</span></div>{preview.message && <div className="warning-banner">{preview.message}</div>}<RefreshDiffWorkspace diffs={preview.diffs} accepted={accepted} onToggle={diff => setAccepted(current => ({ ...current, [diff.key]: !current[diff.key] }))} /><div className="dialog-actions"><span className="muted">已选择 {acceptedCount} / {preview.diffs.length} 项</span><button className="secondary" onClick={() => void skipCurrent()}>跳过此篇</button><button className="primary" disabled={!acceptedCount} onClick={() => void applyCurrent()}>保存所选并继续</button></div></>}
    {phase === "done" && <div className="batch-results"><div className="success-banner">批量读取完成：处理 {statuses.length} 篇，保存 {statuses.filter(item => item.kind === "saved").length} 篇，失败 {statuses.filter(item => item.kind === "error").length} 篇。</div><div className="batch-status-list">{statuses.map(item => <div key={`${item.paperId}-${item.kind}`} className={item.kind}><strong>{statusLabel[item.kind]}</strong><span>{item.title}</span><small>{item.message}</small></div>)}</div><div className="dialog-actions"><button className="primary" onClick={onFinished}>完成</button></div></div>}
  </div></div>;
}

const NOTE_SECTIONS: { key: keyof Note; label: string; hint: string; rows?: number }[] = [
  { key: "abstract_zh", label: "摘要（中文译文）", hint: "由“一键读文献”忠实翻译论文原始摘要；也可以手工修改。", rows: 8 },
  { key: "research_question", label: "研究问题", hint: "这篇文献试图回答什么问题？" },
  { key: "paper_idea", label: "论文思路（写作逻辑）", hint: "按背景/问题→数据与方法→结果→机制解释→结论列出文章写作逻辑。", rows: 5 },
  { key: "datasets", label: "数据集", hint: "ERA5、CMIP6、站点观测……" },
  { key: "variables", label: "气象变量", hint: "温度、降水、位势高度、风场……" },
  { key: "region", label: "研究区域", hint: "区域范围与空间分辨率" },
  { key: "time_range", label: "时间范围", hint: "研究时段与时间分辨率" },
  { key: "methods", label: "研究方法", hint: "统计方法、诊断方法、实验设计", rows: 3 },
  { key: "models", label: "模式 / 模型", hint: "WRF、CESM、机器学习模型……" },
  { key: "key_findings", label: "主要结论", hint: "最值得记住的结果", rows: 4 },
  { key: "limitations", label: "局限性", hint: "数据、方法或结论的边界", rows: 3 },
  { key: "reusable_ideas", label: "可借鉴点", hint: "可以复用的思路、图表或方法", rows: 3 },
];

function noteRows(value: string, minimum: number, maximum: number) {
  // The editor is shown in a fairly narrow two-column pane.  Estimating with
  // a shorter line length keeps long Chinese/English notes readable without
  // forcing the user to scroll inside every field.
  const lines = value.split("\n").reduce((count, line) => count + Math.max(1, Math.ceil(line.length / 14)), 0);
  return Math.min(maximum, Math.max(minimum, lines));
}

function NoteEditor({ note, setField, onHistory }: { note: Note; setField: (field: keyof Note, value: string) => void; onHistory: () => void }) {
  return <div className="note-editor"><div className="note-toolbar"><p className="note-help">长内容会自动展开；也可以拖动输入框右下角调整高度。</p><button onClick={onHistory}>查看笔记历史</button></div><div className="note-grid">{NOTE_SECTIONS.map(item => { const value = String(note[item.key] || ""); return <label className="note-card" key={item.key}><span>{item.label}</span><textarea rows={noteRows(value, item.rows || 6, 36)} placeholder={item.hint} value={value} onChange={e => setField(item.key, e.target.value)} /></label>; })}<label className="full note-card"><span>自由笔记 · Markdown</span><textarea className="markdown-area" rows={noteRows(note.markdown, 18, 60)} placeholder="记录你的推理、疑问和后续计划……" value={note.markdown} onChange={e => setField("markdown", e.target.value)} /></label></div></div>;
}

function MetadataEditor({ paper, onSave, collections, tags, onUpdated }: { paper: PaperDetail; onSave: (data: Record<string, unknown>) => Promise<void>; collections: Collection[]; tags: Tag[]; onUpdated: (p: PaperDetail) => void }) {
  const [form, setForm] = useState({ title: paper.title, authors: paper.authors.map(displayAuthor).join("; "), year: paper.year || "", journal: paper.journal, volume: paper.volume, issue: paper.issue, pages: paper.pages, doi: paper.doi || "", abstract: paper.abstract, keywords: paper.keywords.length ? paper.keywords : [""], reading_status: paper.reading_status, citation_key: paper.citation_key, document_type: paper.document_type });
  const save = async () => onSave({ ...form, year: form.year ? Number(form.year) : null, authors: form.authors.split(";").map(name => ({ literal: name.trim(), family: "", given_name: "" })).filter(a => a.literal), keywords: form.keywords.map(v => v.trim()).filter(Boolean) });
  const updateKeyword = (index: number, value: string) => setForm(current => ({ ...current, keywords: current.keywords.map((keyword, position) => position === index ? value : keyword) }));
  const addKeyword = () => setForm(current => ({ ...current, keywords: [...current.keywords, ""] }));
  const removeKeyword = (index: number) => setForm(current => ({ ...current, keywords: current.keywords.filter((_, position) => position !== index) }));
  const assign = async (kind: "tags" | "collections", ids: number[]) => { await putJson(`/api/v1/papers/${paper.id}/${kind}`, { ids }); onUpdated(await api<PaperDetail>(`/api/v1/papers/${paper.id}`)); };
  return <><div className="meta-form"><label className="full">题名<input value={form.title} onChange={e => setForm(v => ({ ...v, title: e.target.value }))} /></label><label className="full">作者（分号分隔）<input value={form.authors} onChange={e => setForm(v => ({ ...v, authors: e.target.value }))} /></label><label>文献类型<select value={form.document_type} onChange={e => setForm(v => ({ ...v, document_type: e.target.value as DocumentType }))}>{Object.entries(DOCUMENT_TYPE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>年份<input value={form.year} onChange={e => setForm(v => ({ ...v, year: e.target.value }))} /></label><label>期刊/来源<input value={form.journal} onChange={e => setForm(v => ({ ...v, journal: e.target.value }))} /></label><label>卷<input value={form.volume} onChange={e => setForm(v => ({ ...v, volume: e.target.value }))} /></label><label>期<input value={form.issue} onChange={e => setForm(v => ({ ...v, issue: e.target.value }))} /></label><label>页码<input value={form.pages} onChange={e => setForm(v => ({ ...v, pages: e.target.value }))} /></label><label>阅读状态<select value={form.reading_status} onChange={e => setForm(v => ({ ...v, reading_status: e.target.value as PaperDetail["reading_status"] }))}><option value="unread">未读</option><option value="reading">在读</option><option value="read">已读</option><option value="archived">归档</option></select></label><label className="full">DOI<input value={form.doi} onChange={e => setForm(v => ({ ...v, doi: e.target.value }))} /></label><div className="full keyword-editor"><span>关键词（逐条填写）</span><div className="keyword-list">{form.keywords.map((keyword, index) => <div className="keyword-row" key={`${index}-${keyword}`}><input aria-label={`关键词 ${index + 1}`} value={keyword} onChange={e => updateKeyword(index, e.target.value)} /><button type="button" className="keyword-remove" aria-label={`删除关键词 ${index + 1}`} onClick={() => removeKeyword(index)}>×</button></div>)}<button type="button" className="keyword-add" onClick={addKeyword}>＋ 添加关键词</button></div></div><label className="full">摘要<textarea rows={6} value={form.abstract} onChange={e => setForm(v => ({ ...v, abstract: e.target.value }))} /></label><label className="full">引用键<input value={form.citation_key} onChange={e => setForm(v => ({ ...v, citation_key: e.target.value }))} /></label><button className="primary" onClick={() => void save()}>保存题录</button></div>
    <TaxonomyAssign label="专题" options={collections} selected={paper.collections.map(item => item.id)} onChange={ids => void assign("collections", ids)} />
    <TaxonomyAssign label="标签" options={tags} selected={paper.tags.map(item => item.id)} onChange={ids => void assign("tags", ids)} />
    </>;
}

function TaxonomyAssign({ label, options, selected, onChange }: { label: string; options: { id: number; name: string }[]; selected: number[]; onChange: (ids: number[]) => void }) {
  return <section className="form-section"><h3>{label}</h3><div className="check-grid">{options.length === 0 ? <span className="muted">尚未创建{label}</span> : options.map(option => <label key={option.id}><input type="checkbox" checked={selected.includes(option.id)} onChange={e => onChange(e.target.checked ? [...selected, option.id] : selected.filter(id => id !== option.id))} />{option.name}</label>)}</div></section>;
}

function RelationEditor({ paper, onUpdated }: { paper: PaperDetail; onUpdated: (p: PaperDetail) => void }) {
  const [target, setTarget] = useState(""); const [type, setType] = useState("method_related"); const [label, setLabel] = useState("");
  const add = async () => { if (!target) return; await postJson("/api/v1/relations", { source_paper_id: paper.id, target_paper_id: Number(target), relation_type: type, label }); setTarget(""); setLabel(""); onUpdated(await api<PaperDetail>(`/api/v1/papers/${paper.id}`)); };
  return <section className="form-section"><h3>相关文献</h3><div className="inline-form"><input placeholder="目标文献 ID" value={target} onChange={e => setTarget(e.target.value)} /><select value={type} onChange={e => setType(e.target.value)}><option value="cites">引用</option><option value="extends">延伸</option><option value="contrasts">对比</option><option value="method_related">方法相似</option><option value="custom">自定义</option></select><input placeholder="补充说明" value={label} onChange={e => setLabel(e.target.value)} /><button onClick={() => void add()}>添加</button></div>{paper.relations.map(item => <div className="relation-row" key={item.id}><span>{item.relation_type}</span><b>#{item.target_paper_id} {item.target_title}</b><small>{item.label}</small></div>)}</section>;
}

function ImportsView({ onDone }: { onDone: () => void }) {
  const [error, setError] = useState(""); const [metadataMessage, setMetadataMessage] = useState(""); const [zoteroBusy, setZoteroBusy] = useState(false);
  const [zoteroConnected, setZoteroConnected] = useState<boolean | null>(null);
  useEffect(() => { api<AppSettings>("/api/v1/settings").then(settings => setZoteroConnected(settings.zotero_configured)).catch(() => setZoteroConnected(false)); }, []);
  const testZotero = async () => { setZoteroBusy(true); setError(""); try { const result = await postJson<{ total: number }>("/api/v1/integrations/zotero/test"); setMetadataMessage(`Zotero 已连接，可读取 ${result.total} 个条目。`); } catch (reason) { setError(reason instanceof Error ? reason.message : "Zotero 连接失败"); } finally { setZoteroBusy(false); } };
  const syncZotero = async () => { setZoteroBusy(true); setError(""); setMetadataMessage("正在读取并整理 Zotero 文献库。大型文献库首次加载可能需要一些时间，请保持 Zotero 开启……"); try { const result = await postJson<{ imported: number; updated: number; unchanged: number; total: number; duplicates_merged: number; removed: number }>("/api/v1/integrations/zotero/sync"); setZoteroConnected(true); setMetadataMessage(`已刷新当前 Zotero 库：共读取 ${result.total} 条，新增 ${result.imported} 篇，更新 ${result.updated} 篇，未变化 ${result.unchanged} 篇${result.removed ? `，隐藏已从 Zotero 移除的条目 ${result.removed} 篇` : ""}${result.duplicates_merged ? `，按 DOI 合并重复条目 ${result.duplicates_merged} 条` : ""}。PDF 仍保存在 Zotero，PaperNote 只保存链接和笔记。`); } catch (reason) { setMetadataMessage(""); setError(reason instanceof Error ? reason.message : "Zotero 同步失败"); } finally { setZoteroBusy(false); } };
  const disconnectZotero = async () => {
    if (!window.confirm("确定退出当前 Zotero 文献库吗？退出后，该库题录会从 PaperNote 文献库中隐藏；本地科研笔记会完整保留，Zotero 中的文献和 PDF 不受影响。")) return;
    setZoteroBusy(true); setError("");
    try {
      const result = await postJson<{ retained_notes: number }>("/api/v1/integrations/zotero/disconnect");
      setZoteroConnected(false);
      setMetadataMessage(`已退出当前 Zotero 库。${result.retained_notes} 篇已同步题录已隐藏，相关科研笔记仍保存在本地；重新连接同一库即可恢复显示。`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "退出 Zotero 库失败"); }
    finally { setZoteroBusy(false); }
  };
  return <Page title="外部文献" eyebrow="EXTERNAL LIBRARY" intro="PaperNote 不再保存或复制 PDF；从 Zotero 等外部文献库读取题录和链接，本地只保存科研笔记。">
    {!isServerMode && <div className="error-banner">当前是离线本地模式，浏览器不能直接访问 Zotero。请关闭本页并使用系统入口重新启动 PaperNote：Windows 双击 start.bat，macOS 双击 start.command，Linux 运行 ./start.sh。</div>}
    <div className="import-hero"><div><h2>{zoteroConnected ? "同步外部文献库" : "尚未加载 Zotero 文献库"}</h2><p>{zoteroConnected ? "当前库已加载。Zotero 更新后点击刷新，PaperNote 会以当前 Zotero 库为准同步题录。" : "当前没有活动的 Zotero 库，文献库中的 Zotero 题录已全部隐藏；可重新加载已配置的库。"}</p></div><div className="path-picker"><div className="import-buttons"><button disabled={zoteroBusy} onClick={() => void testZotero()}>{zoteroBusy ? "连接中…" : "测试 Zotero"}</button><button className="primary" disabled={zoteroBusy} onClick={() => void syncZotero()}>{zoteroBusy ? "正在加载，请稍候…" : zoteroConnected ? "刷新当前 Zotero 库" : "加载配置的 Zotero 库"}</button>{zoteroConnected && <button className="danger" disabled={zoteroBusy} onClick={() => void disconnectZotero()}>退出当前 Zotero 库</button>}</div></div></div>
    {metadataMessage && <div className="success-banner">{metadataMessage}</div>}
    {error && <div className="error-banner">{error}</div>}
    {metadataMessage && <button className="secondary finish-button" onClick={onDone}>返回文献库</button>}
  </Page>;
}

function TrashView() {
  const [items, setItems] = useState<TrashPaper[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const load = async () => {
    setLoading(true); setError("");
    try { setItems(await api<TrashPaper[]>("/api/v1/trash")); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "回收站加载失败"); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  const restore = async (id: number) => { try { await postJson(`/api/v1/trash/${id}/restore`); setMessage("文献已恢复到文献库"); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "恢复失败"); } };
  const remove = async (id: number) => {
    if (!window.confirm("确定永久删除这篇文献吗？这会删除 PaperNote 本地题录、Markdown 科研笔记和历史版本，无法恢复；Zotero 等外部文献库中的 PDF 与附件不会被删除。")) return;
    try { await api(`/api/v1/trash/${id}`, { method: "DELETE" }); setMessage("本地题录与科研笔记已永久删除；外部文献库未受影响"); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "永久删除失败"); }
  };
  const clear = async () => {
    if (!items.length || !window.confirm("确定清空回收站吗？其中的本地题录、Markdown 科研笔记和历史版本将永久删除，无法恢复；Zotero 等外部文献库中的 PDF 与附件不会被删除。")) return;
    try { const result = await api<{ removed: number }>("/api/v1/trash", { method: "DELETE" }); setMessage(`已永久删除 ${result.removed} 篇文献`); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "清空回收站失败"); }
  };
  const formatSize = (bytes: number) => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return <Page title="回收站" eyebrow="RECYCLE BIN" intro="移入回收站的本地题录和科研笔记仍可恢复；永久删除只清理 PaperNote 本地记录，绝不会触碰 Zotero 等外部文献库。">
    {message && <div className="success-banner">{message}</div>}
    {error && <div className="error-banner">{error}</div>}
    <div className="trash-toolbar"><div><strong>{items.length} 篇待处理</strong><span>可以逐篇恢复或永久删除</span></div><button className="danger" disabled={!items.length} onClick={() => void clear()}>清空回收站</button></div>
    {loading ? <Loading /> : items.length === 0 ? <div className="empty-state compact"><h2>回收站是空的</h2><p>删除文献后会先出现在这里，方便你检查和恢复。</p></div> : <div className="trash-list">{items.map(item => <article className="trash-card" key={item.id}><div><h2>{item.title || "未识别题名"}</h2><p>{formatAuthors(item) || "作者待补充"} · {item.year || "年份未知"} · 本地笔记与题录</p><small>移入时间：{new Date(item.deleted_at).toLocaleString("zh-CN")}</small></div><div className="trash-actions"><button onClick={() => void restore(item.id)}>恢复</button><button className="danger" onClick={() => void remove(item.id)}>永久删除</button></div></article>)}</div>}
  </Page>;
}

function OrganizeView({ collections, tags, refresh }: { collections: Collection[]; tags: Tag[]; refresh: () => Promise<void> }) {
  const [collectionName, setCollectionName] = useState(""); const [tagName, setTagName] = useState("");
  const createCollection = async () => { if (!collectionName.trim()) return; await postJson("/api/v1/collections", { name: collectionName }); setCollectionName(""); await refresh(); };
  const createTag = async () => { if (!tagName.trim()) return; await postJson("/api/v1/tags", { name: tagName, color: "#4f6b62" }); setTagName(""); await refresh(); };
  return <Page title="专题与标签" eyebrow="KNOWLEDGE MAP" intro="专题提供研究脉络，标签负责灵活交叉分类。"><div className="two-columns"><section className="panel"><h2>专题集合</h2><div className="inline-form"><input value={collectionName} onChange={e => setCollectionName(e.target.value)} placeholder="例如：东亚季风" /><button className="primary" onClick={() => void createCollection()}>创建</button></div><div className="taxonomy-list">{collections.map(item => <div key={item.id}><span>◎</span><b>{item.name}</b><em>{item.paper_count || 0} 篇</em></div>)}</div></section><section className="panel"><h2>标签</h2><div className="inline-form"><input value={tagName} onChange={e => setTagName(e.target.value)} placeholder="例如：ERA5" /><button className="primary" onClick={() => void createTag()}>创建</button></div><div className="taxonomy-list">{tags.map(item => <div key={item.id}><i style={{ background: item.color }} /><b>{item.name}</b><em>{item.paper_count || 0} 篇</em></div>)}</div></section></div></Page>;
}

function SettingsView({ collections }: { collections: Collection[] }) {
  const [settings, setSettings] = useState<AppSettings>({ data_root: "", data_root_source: "default", data_root_locked: false, crossref_email: "", llm_base_url: "https://api.deepseek.com", llm_api_key: "", llm_model: "deepseek-v4-flash", llm_configured: false, zotero_base_url: "http://127.0.0.1:23119/api", zotero_library_id: "users/0", zotero_api_key: "", zotero_configured: false, obsidian_vault_path: "", obsidian_folder: "PaperNote", host: "127.0.0.1", port: 8765 });
  const [message, setMessage] = useState(""); const [exportFormat, setExportFormat] = useState("bibtex"); const [collection, setCollection] = useState("");
  useEffect(() => { api<typeof settings>("/api/v1/settings").then(setSettings); }, []);
  const save = async () => { const result = await patchJson<Partial<AppSettings>>("/api/v1/settings", { crossref_email: settings.crossref_email, llm_base_url: settings.llm_base_url, llm_api_key: settings.llm_api_key, llm_model: settings.llm_model, zotero_base_url: settings.zotero_base_url, zotero_library_id: settings.zotero_library_id, zotero_api_key: settings.zotero_api_key, obsidian_vault_path: settings.obsidian_vault_path, obsidian_folder: settings.obsidian_folder }); setSettings(current => ({ ...current, ...result, llm_api_key: current.llm_api_key, zotero_api_key: current.zotero_api_key })); setMessage("设置已保存。PDF 仍由外部文献库管理，PaperNote 只保存题录和科研笔记。"); };
  const backup = async () => { const result = await postJson<{ path: string }>("/api/v1/backups"); setMessage(`备份已创建：${result.path}`); };
  const exportData = async () => { const result = await postJson<{ path: string; download_url: string }>("/api/v1/exports", { format: exportFormat, collection_id: collection ? Number(collection) : null }); window.location.href = result.download_url; setMessage(`导出文件已生成：${result.path}`); };
  const testZotero = async () => { try { const result = await postJson<{ total: number }>("/api/v1/integrations/zotero/test"); setMessage(`Zotero 连接成功，可读取 ${result.total} 个条目。`); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Zotero 连接失败"); } };
  const syncZotero = async () => { try { const result = await postJson<{ imported: number; updated: number; unchanged: number; total: number; duplicates_merged: number; removed: number }>("/api/v1/integrations/zotero/sync"); setSettings(current => ({ ...current, zotero_configured: true })); setMessage(`Zotero 已强制刷新：共读取 ${result.total} 条，新增 ${result.imported} 篇，更新 ${result.updated} 篇，未变化 ${result.unchanged} 篇${result.removed ? `，隐藏已从 Zotero 移除的条目 ${result.removed} 篇` : ""}${result.duplicates_merged ? `，按 DOI 合并重复条目 ${result.duplicates_merged} 条` : ""}。`); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Zotero 同步失败"); } };
  const disconnectZotero = async () => {
    if (!window.confirm("确定退出当前 Zotero 文献库吗？该库题录会从文献库视图隐藏，但本地科研笔记不会删除，Zotero 文献和 PDF 也不会受到影响。")) return;
    try {
      const result = await postJson<{ retained_notes: number }>("/api/v1/integrations/zotero/disconnect");
      setSettings(current => ({ ...current, zotero_configured: false }));
      setMessage(`已退出当前 Zotero 库；${result.retained_notes} 篇题录已隐藏，科研笔记仍保留在本地。重新连接同一库后会恢复显示。`);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "退出 Zotero 库失败"); }
  };
  const syncObsidian = async () => { try { const result = await postJson<{ exported: number; failed: number }>("/api/v1/integrations/obsidian/sync"); setMessage(`Obsidian 已同步 ${result.exported} 篇笔记${result.failed ? `，失败 ${result.failed} 篇` : ""}。`); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Obsidian 同步失败"); } };
  const chooseRoot = async () => { try { if (settings.data_root_locked) { setMessage("此位置由 PAPERNOTE_DATA_DIR 环境变量锁定，请修改或删除该环境变量后重启。"); return; } const selected = await postJson<{ path: string | null }>("/api/v1/settings/data-root/choose"); if (!selected.path) return; const result = await putJson<{ data_root: string; restart_required: boolean }>("/api/v1/settings/data-root", { path: selected.path }); setSettings((current) => ({ ...current, data_root: result.data_root, data_root_source: "config" })); setMessage(result.restart_required ? `新笔记库已保存：${result.data_root}。请关闭当前终端窗口并重新运行启动脚本。` : "当前已经在使用这个笔记库目录。"); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "笔记库位置保存失败"); } };
  return <Page title="设置与备份" eyebrow="LOCAL & PORTABLE" intro="题录可来自外部文献库，科研笔记保存在本机，并可同步到 Obsidian。">{!isServerMode && <div className="error-banner">当前是离线本地模式。Zotero、外部 PDF 路径、大模型和 Obsidian 文件写入需要伴随服务；请运行 Windows 的 start.bat、macOS 的 start.command，或 Linux 的 ./start.sh。</div>}<div className="settings-stack"><section className="panel"><h2>笔记库位置</h2><p className="path-display">{settings.data_root}</p><button onClick={() => void chooseRoot()}>更改目录</button><small>这里保存可读的 Markdown 科研笔记、轻量题录索引、导出与备份；不会创建或保存 PDF。</small></section><section className="panel"><h2>Zotero 外部文献库</h2><p>PaperNote 只读取 Zotero 题录、附件路径和可索引全文，不下载或复制 PDF。Local API 默认地址为 http://127.0.0.1:23119/api。</p><p className={settings.zotero_configured ? "success-banner compact" : "muted"}>当前状态：{settings.zotero_configured ? `已加载 ${settings.zotero_library_id}` : "未加载 Zotero 文献库"}</p><label>接口地址<input value={settings.zotero_base_url} onChange={e => setSettings(v => ({ ...v, zotero_base_url: e.target.value }))} placeholder="http://127.0.0.1:23119/api" /></label><label>文献库 ID<input value={settings.zotero_library_id} onChange={e => setSettings(v => ({ ...v, zotero_library_id: e.target.value }))} placeholder="users/0 或 groups/123" /></label><label>Web API Key（Local API 可留空）<input type="text" value={settings.zotero_api_key} onChange={e => setSettings(v => ({ ...v, zotero_api_key: e.target.value }))} placeholder={settings.zotero_configured ? "已配置，留空表示保持不变" : "仅保存在本机设置文件"} /></label><div className="inline-form"><button onClick={() => void save()}>保存 Zotero 设置</button><button onClick={() => void testZotero()}>测试连接</button><button className="primary" onClick={() => void syncZotero()}>刷新并加载当前库</button><button className="danger" disabled={!settings.zotero_configured} onClick={() => void disconnectZotero()}>退出当前库</button></div><small>退出只会隐藏该库题录；科研笔记仍保存在 PaperNote，本地或 Zotero 中的 PDF 不会被操作。</small></section><section className="panel"><h2>Obsidian 笔记</h2><p>每篇文献导出为一个 Markdown 文件，包含题录、论文思路、科研笔记、摘录与关联；不会包含翻译或 PDF。</p><label>Vault 目录<input value={settings.obsidian_vault_path} onChange={e => setSettings(v => ({ ...v, obsidian_vault_path: e.target.value }))} placeholder="例如 D:/Notes/ObsidianVault" /></label><label>Vault 内子目录<input value={settings.obsidian_folder} onChange={e => setSettings(v => ({ ...v, obsidian_folder: e.target.value }))} placeholder="PaperNote" /></label><div className="inline-form"><button onClick={() => void save()}>保存 Obsidian 设置</button><button className="primary" onClick={() => void syncObsidian()}>同步全部笔记</button></div></section><section className="panel"><h2>可选的大模型 API（仅科研笔记）</h2><p>“一键读文献”会按 Zotero PDF 附件的可索引全文生成科研笔记；全文只在内存中使用，不保存、不翻译。</p><div className="inline-form"><button type="button" onClick={() => setSettings(v => ({ ...v, llm_base_url: "https://api.deepseek.com", llm_model: "deepseek-v4-flash" }))}>使用 DeepSeek V4 Flash</button></div><label>接口地址<input value={settings.llm_base_url} onChange={e => setSettings(v => ({ ...v, llm_base_url: e.target.value }))} placeholder="https://api.deepseek.com" /></label><label>模型名称<input value={settings.llm_model} onChange={e => setSettings(v => ({ ...v, llm_model: e.target.value }))} placeholder="deepseek-v4-flash" /></label><label>API Key<input type="text" value={settings.llm_api_key} onChange={e => setSettings(v => ({ ...v, llm_api_key: e.target.value }))} placeholder={settings.llm_configured ? "已配置，留空表示保持不变" : "仅保存在本机设置文件"} /></label><small>当前配置：{settings.llm_configured ? "已配置" : "未配置"}。</small><button className="primary" onClick={() => void save()}>保存设置</button></section><section className="panel action-panel"><div><h2>完整备份</h2><p>包含题录索引和全部 Markdown 科研笔记，不包含外部 Zotero PDF；备份清单仍写入 SHA-256 校验值。</p></div><button className="primary" onClick={() => void backup()}>创建备份</button></section><section className="panel action-panel"><div><h2>导出资料</h2><p>支持 BibTeX、RIS、APA 7 和 GB/T 7714 参考文献格式，也可导出 Markdown 或 Word。</p></div><div className="inline-form"><select value={exportFormat} onChange={e => setExportFormat(e.target.value)}><option value="bibtex">BibTeX</option><option value="ris">RIS</option><option value="apa">APA 7</option><option value="gbt7714">GB/T 7714</option><option value="markdown">Markdown</option><option value="word">Word</option></select><select value={collection} onChange={e => setCollection(e.target.value)}><option value="">全部文献</option>{collections.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button onClick={() => void exportData()}>导出</button></div></section>{message && <div className="success-banner">{message}</div>}</div></Page>;
}

function Page({ title, eyebrow, intro, children }: { title: string; eyebrow: string; intro: string; children: React.ReactNode }) {
  return <div className="page"><header className="page-title"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{intro}</p></header>{children}</div>;
}

function CreatePaper({ onClose, onCreated }: { onClose: () => void; onCreated: (paper: PaperDetail) => void }) {
  const [form, setForm] = useState({ title: "", authors: "", year: "", journal: "", doi: "", document_type: "article" as DocumentType }); const [error, setError] = useState("");
  const create = async () => { try { const paper = await postJson<PaperDetail>("/api/v1/papers", { title: form.title, authors: form.authors.split(";").map(literal => ({ literal: literal.trim() })).filter(a => a.literal), year: form.year ? Number(form.year) : null, journal: form.journal, doi: form.doi || null, document_type: form.document_type }); onCreated(paper); } catch (reason) { setError(reason instanceof Error ? reason.message : "创建失败"); } };
  return <div className="modal"><div className="dialog"><button className="close" onClick={onClose}>×</button><span className="eyebrow">MANUAL ENTRY</span><h2>手工新建文献</h2>{error && <div className="error-banner">{error}</div>}<label>题名<input autoFocus value={form.title} onChange={e => setForm(v => ({ ...v, title: e.target.value }))} /></label><label>作者（分号分隔）<input value={form.authors} onChange={e => setForm(v => ({ ...v, authors: e.target.value }))} /></label><div className="inline-form"><label>文献类型<select value={form.document_type} onChange={e => setForm(v => ({ ...v, document_type: e.target.value as DocumentType }))}>{Object.entries(DOCUMENT_TYPE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>年份<input value={form.year} onChange={e => setForm(v => ({ ...v, year: e.target.value }))} /></label><label>期刊/来源<input value={form.journal} onChange={e => setForm(v => ({ ...v, journal: e.target.value }))} /></label></div><label>DOI<input value={form.doi} onChange={e => setForm(v => ({ ...v, doi: e.target.value }))} /></label><button className="primary" disabled={!form.title.trim()} onClick={() => void create()}>创建文献</button></div></div>;
}
