# 在新 Agent、新电脑或新 Project 中继续开发

这份文档说明如何恢复“可继续工作的开发环境”。个人文献数据迁移另见 [MIGRATION.md](MIGRATION.md)。

## 一、先分清三样东西

| 内容 | 保存位置 | 是否在 GitHub |
|---|---|---|
| PaperNote 程序 | 本仓库 | 是 |
| Zotero 题录、附件、PDF | Zotero 数据目录或 Zotero Sync | 否 |
| 科研笔记 | PaperNote 数据目录的 `notes/*.md` | 否 |

GitHub 只能恢复程序代码。换电脑后还要恢复 Zotero，并复制 Markdown 笔记；换 Agent 或重新打开 Project 时通常不需要移动个人数据，只需确认 Agent 打开的是正确仓库和数据目录。

## 二、换 Agent 后如何接手

让新 Agent 先阅读：

1. 根目录的 `AGENTS.md`；
2. `README.md`；
3. 本文档；
4. 与任务相关的源码和测试，不要只依据旧对话猜测当前实现。

开始修改前执行：

```sh
git status --short
git branch --show-current
git remote -v
```

必须保留用户已有的未提交修改。若工作区不干净，应先区分哪些是用户改动、哪些是本次任务，不能使用 `git reset --hard` 或覆盖整个文件。

推荐给新 Agent 的接手说明：

```text
请先阅读 AGENTS.md、README.md 和 docs/CONTINUING_DEVELOPMENT.md，再检查 git status。
PaperNote 当前是 Zotero + Markdown 的轻量架构：不使用 SQLite、不保存 PDF、不保留全文翻译。
请基于现有实现继续，不要恢复已经废弃的数据库或 PDF 导入设计；修改后运行后端测试、前端类型检查和发布构建。
```

## 三、换 Project 或重新打开工作区

1. 将 Project/工作区根目录指向 PaperNote 仓库根目录，而不是 `frontend`、`backend` 或 `library-data` 子目录。
2. 确认根目录能看到 `README.md`、`AGENTS.md`、`backend`、`frontend`、`scripts`。
3. 确认 Git 远端仍是正确仓库：

   ```sh
   git remote -v
   ```

4. 若个人数据在仓库外，通过设置页重新选择笔记库，或设置环境变量：

   ```text
   PAPERNOTE_DATA_DIR=D:\Research\PaperNoteData
   ```

5. 重启 PaperNote。环境变量存在时会锁定界面里的目录选择，这是预期行为。

不要把包含 API Key 的 `app-config.json` 或整个个人数据目录加入 Project 的 Git 提交范围。

## 四、换电脑后的完整恢复

### 1. 恢复代码

```sh
git clone https://github.com/weiguang1233/PaperNotes.git
cd PaperNotes
```

Windows 运行 `setup.bat`，macOS/Linux 运行 `./setup.sh`。安装成功应显示 `Runtime dependency check passed.`。

### 2. 恢复 Zotero

优先使用同一 Zotero 账户同步。若不使用云同步，必须在两台电脑都完全退出 Zotero 后复制完整 Zotero 数据目录；不能只复制 `zotero.sqlite`。链接附件还要复制其外部根目录。

### 3. 恢复 Markdown 笔记

将旧电脑的 `notes` 目录复制到新 PaperNote 数据目录中。最小必需内容是：

```text
PaperNoteData/
└─ notes/
   ├─ <Zotero Item Key>.md
   └─ .history/
```

需要同时保留专题、标签、回收站和本机设置时，可复制整个数据目录，但要注意其中可能包含 API Key。

### 4. 重新关联

1. 启动 Zotero；
2. 启动 PaperNote 的 server 模式；
3. 在设置页测试 Zotero；
4. 在“外部文献”刷新当前 Zotero 库；
5. 打开一篇已写过笔记的文献核对。

PaperNote 会依次按 Zotero Item Key、唯一 DOI、唯一引用键和唯一题名查找已有 Markdown。`paper_id` 可以在新电脑变化，不是永久标识。

## 五、当前架构速览

```text
Zotero Local/Web API
        │ 题录、附件链接、已索引正文（按需读取）
        ▼
backend/app
        │
        ├─ papernote-state.json：可重建缓存
        └─ notes/*.md：长期科研笔记
                │
                └─ Obsidian / 文本编辑器
```

关键目录：

- `backend/app`：本机 API、Zotero 接入、Markdown 存储、一键阅读；
- `frontend/src`：React 界面；
- `frontend/dist-portable`：随发布提交的预构建页面；
- `scripts/launcher.py`：跨平台启动；
- `tests/test_core.py`：迁移、笔记格式、Zotero 和模型解析的关键测试；
- `MARKDOWN_NOTES.md`：Markdown 字段与跨电脑匹配规则。

科研笔记固定字段包括：`abstract_zh`、`research_question`、`paper_idea`、`datasets`、`variables`、`region`、`time_range`、`methods`、`models`、`key_findings`、`limitations`、`reusable_ideas`、`markdown`。

## 六、每次继续开发的检查清单

1. `git status --short`，确认没有误覆盖用户文件；
2. 启动 Zotero，确认 `http://127.0.0.1:23119/api` 可访问；
3. 启动 PaperNote，确认 `/api/v1/health` 返回正常；
4. 检查当前数据目录是否是预期目录；
5. 修改后运行：

   ```powershell
   .venv\Scripts\python.exe -m pytest -q
   cd frontend
   npm.cmd run typecheck
   npm.cmd run build
   ```

6. 前端变更需同时提交 `frontend/src` 与最新 `frontend/dist-portable`；
7. 提交前检查 `git status`，不得出现 `library-data`、API Key、日志、`.venv` 或 `node_modules`；
8. 推送后核对远端分支的提交编号。

## 七、常见接手问题

- 页面拒绝连接：重新运行启动脚本并保持终端窗口运行；启动器可能自动改用其他端口。
- 新电脑缺少 `uvicorn`：安装没有完成，重新运行 setup，而不是反复运行 start。
- Zotero 连接被拒绝：先打开 Zotero，并确认 Local API；远程 Web API 则需要正确 Library ID 和 Key。
- 题录仍是旧库：退出当前 Zotero 库后重新刷新；题录缓存可以重建。
- 有题录但没有笔记：检查当前数据目录、`notes/*.md` 和 YAML 中的 `zotero_key`/`doi`。
- Obsidian 看不到新笔记：确认 Obsidian 打开的 Vault 或同步目标就是当前数据目录下的 `notes`。
- 只修改了源码但页面没变化：重新运行前端 `npm run build`，并重启 PaperNote 服务。
