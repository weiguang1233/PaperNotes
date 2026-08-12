# PaperNote 开发约束

本文件供 Codex、其他代码 Agent 和新开发者进入仓库时首先阅读。更完整的接手流程见 `docs/CONTINUING_DEVELOPMENT.md`。

## 当前产品边界

- Zotero 是题录、附件和 PDF 的唯一来源；PaperNote 不复制、不迁移、不删除 Zotero PDF。
- PaperNote 的长期数据是 `notes/*.md`，每篇文献一个 UTF-8 Markdown 文件。
- 不使用 SQLite。`papernote-state.json` 只是可以从 Zotero 和 Markdown 重建的轻量 JSON 缓存。
- 不保留全文翻译；“一键读文献”只生成或补充题录与中文科研笔记。
- 中文文献和综述类文献默认不进入自动批量阅读。
- 手工内容不能被模型静默覆盖；模型建议必须经过新旧内容对比和用户选择。
- `paper_idea` 是“论文思路（写作逻辑）”的固定字段名，`abstract_zh` 是原文摘要的中文翻译。
- 摘录和关系由用户手工管理，不受一键阅读控制。

## 数据安全

- 不提交 `library-data/`、`.venv/`、`frontend/node_modules/`、`app-config.json`、日志或 API Key。
- 不为修复 PaperNote 而移动、重命名或删除 Zotero 数据目录和附件。
- 永久删除 PaperNote 文献时，只删除 PaperNote 缓存和对应 Markdown；不得触碰 Zotero 条目或 PDF。
- 修改数据目录逻辑时，必须支持项目目录以外的绝对路径和 `PAPERNOTE_DATA_DIR`。

## 修改后的最低验证

```powershell
.venv\Scripts\python.exe -m pytest -q
cd frontend
npm.cmd run typecheck
npm.cmd run build
```

macOS/Linux 将 Python 路径替换为 `.venv/bin/python`，npm 命令替换为 `npm`。前端变更后必须更新并提交 `frontend/dist-portable`，因为普通用户启动时不依赖 Node.js。
