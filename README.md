# PaperNote

PaperNote 是 Zotero 的轻量本地科研笔记伴侣：

- Zotero 负责题录、附件与 PDF；
- PaperNote 只按需读取 Zotero 已索引的题录和正文，不复制 PDF；
- 每篇科研笔记是一个普通 Markdown 文件；
- 没有 SQLite，也不把笔记锁在浏览器或专用数据库里；
- 可直接用 Obsidian、VS Code 或任意文本编辑器继续整理。

应用只监听 `127.0.0.1`，没有账号系统，也不会主动对局域网开放。

## 快速开始

需要 Python 3.10 或更高版本，并建议安装 Zotero 桌面版。

### Windows

首次双击 `setup.bat`，完成后双击 `start.bat`。

安装脚本默认直连 Python 官方软件源，并隔离系统中遗留或失效的代理配置。第一次安装中途失败也不必删除 `.venv`，修复网络后重新运行 `setup.bat` 即可补全依赖。

只有当前网络明确要求代理、并且已确认代理可用时，才手动指定：

```powershell
setup.bat -ProxyUrl http://127.0.0.1:7897
```

### macOS

首次在终端运行：

```sh
chmod +x setup.sh start.sh start.command
./setup.sh
```

只有当前网络明确要求代理时才使用：

```sh
PAPERNOTE_PIP_PROXY=http://127.0.0.1:7897 ./setup.sh
```

以后双击 `start.command`，或运行 `./start.sh`。

### Linux

首次运行：

```sh
chmod +x setup.sh start.sh
./setup.sh
```

以后运行 `./start.sh`。

统一启动器会尝试启动 Zotero、等待 Local API、启动 PaperNote 伴随服务，并打开实际可用的本机地址（通常为 `http://127.0.0.1:8766/?mode=server`）。

## 日常工作流

1. 在 Zotero 中维护题录和 PDF。
2. 在 PaperNote“设置与备份”中测试 Zotero 连接。
3. 在“外部文献”中刷新当前 Zotero 库。
4. 对单篇或多篇文献使用“一键读文献”。
5. 审核更新前后差异后，将科研笔记保存成 Markdown。
6. 用 Obsidian 直接打开或同步这些 Markdown。

Zotero 更新后需要再次刷新；PaperNote 的题录只是可重建缓存，Zotero 仍是唯一题录来源。

## 保存位置

默认数据目录为 `library-data`：

```text
library-data/
├─ notes/                  # 每篇文献一个 Markdown
│  └─ .history/            # 笔记历史版本
├─ papernote-state.json    # 可重建题录缓存、设置、专题和标签
├─ exports/                # 导出结果
└─ backups/                # PaperNote 轻量备份
```

数据目录不包含 Zotero PDF。`papernote-state.json` 是 UTF-8 JSON，不是数据库；真正需要长期保存的是 `notes/*.md`。

可通过环境变量把数据放到代码目录之外：

```text
PAPERNOTE_DATA_DIR=D:\Research\PaperNoteData
```

也可以在设置页修改笔记库位置，修改后需重启。

设置页的“更改目录”会打开操作系统原生文件夹选择器，选中后立即校验可写性并保存，重启 PaperNote 后切换到新目录。它不会自动移动或删除旧目录中的 Markdown；已有笔记需要迁移时，请先备份或复制旧目录。

如果设置页显示位置被锁定，表示系统中设置了 `PAPERNOTE_DATA_DIR`。该环境变量的优先级高于界面设置，需要先修改或删除环境变量，再重启 PaperNote。

## 换电脑后怎样找回笔记

程序代码和个人数据应分开迁移：

1. 在新电脑安装/克隆 PaperNote，并运行一次安装脚本。
2. 用 Zotero 官方同步，或在 Zotero 完全退出时复制完整 Zotero 数据目录和附件。
3. 复制旧电脑的 `library-data/notes` 到新电脑对应的数据目录；需要专题、标签和设置时可复制整个 `library-data`。
4. 启动 Zotero 和 PaperNote，测试连接，再“刷新当前 Zotero 库”。
5. 打开任意已写过笔记的文献核对。

PaperNote 首先按稳定的 Zotero Item Key 查找 `<Zotero Key>.md`。若导出再导入导致 Item Key 改变，会在唯一匹配时按 DOI、引用键、题名依次重新关联。Markdown 头部的旧 `paper_id` 只是历史缓存编号，不影响新电脑读取。

完整步骤和故障排查见 [跨电脑迁移说明](docs/MIGRATION.md)。

若要换 Codex/代码 Agent、重新打开 Project，或让另一位开发者继续本项目，请先阅读 [继续开发与交接说明](docs/CONTINUING_DEVELOPMENT.md)。仓库根目录的 `AGENTS.md` 记录了不得恢复 SQLite、本地 PDF 副本和全文翻译等当前架构约束。

## Obsidian

最简单的方式是把 `library-data/notes` 直接作为 Obsidian Vault 打开。若已有 Vault，在“设置与备份 → Obsidian 笔记”中填写 Vault 路径和目标子目录，再同步全部笔记。

笔记格式见 [MARKDOWN_NOTES.md](MARKDOWN_NOTES.md)。YAML 中保留 Zotero Key、DOI、引用键和题名，便于 Obsidian 查询和跨电脑重新关联。

## 完全离线查看

不连接 Zotero 或大模型时，仍能查看和编辑已有 Markdown：

Windows：

```powershell
.venv\Scripts\python.exe scripts\launcher.py --mode local
```

macOS/Linux：

```sh
.venv/bin/python scripts/launcher.py --mode local
```

离线模式通常使用 `http://127.0.0.1:8765/?mode=local`。它不刷新 Zotero 题录，也不运行一键读文献。

## 项目结构

- `backend/app`：本机 API、Markdown 存储、Zotero 接入和导出；
- `frontend/src`：React 界面源码；
- `frontend/dist-portable`：无需 Node.js 即可运行的预构建网页；
- `scripts/launcher.py`：Windows、macOS、Linux 共用启动逻辑；
- `tests`：关键迁移、Zotero 和笔记格式测试。

换 Agent、换 Project 和换电脑的开发接手流程见 [继续开发与交接说明](docs/CONTINUING_DEVELOPMENT.md)。

`.venv`、`frontend/node_modules`、`library-data`、临时文件和 API Key 均被 `.gitignore` 排除，不应上传 GitHub。

## 开发与验收

后端测试：

```powershell
.venv\Scripts\python.exe -m pytest -q
```

前端重新构建：

```sh
cd frontend
npm ci
npm run build
```

`frontend/dist-portable` 是发布包的一部分，修改前端后需要提交新的构建结果。发布检查见 [GitHub 发布清单](docs/GITHUB_RELEASE.md)。

## 常见问题

- 页面拒绝连接：重新运行当前系统的启动入口；终端窗口需保持运行。
- 首次安装出现 `ProxyError`：确认使用的是 GitHub 最新版；新版不会猜测代理。直接重新运行 `setup.bat`/`./setup.sh`。只有代理确实可用时才按上面的格式显式指定。
- 启动提示缺少 `uvicorn`、`fastapi`：说明前一次安装没有完成。不要直接反复启动，先重新运行安装脚本，看到 `Runtime dependency check passed.` 后再启动。
- Zotero 拒绝连接：先启动 Zotero，确认 Local API 可用，再测试连接。
- 加载后仍是旧题录：在“外部文献”退出当前库，再刷新当前 Zotero 库。
- 新电脑有题录但没有笔记：确认复制的是 `notes` 目录，并检查 Zotero 条目 Key/DOI 是否保留。
- 端口被占用：启动器会选择其他端口，以实际打开的地址为准。
