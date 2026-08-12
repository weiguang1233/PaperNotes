# PaperNote 与 Zotero 跨电脑迁移

## 先理解三类内容

| 内容 | 负责人 | 建议迁移方式 |
|---|---|---|
| 题录、条目 Key、附件关系 | Zotero | Zotero Sync，或完整复制 Zotero 数据目录 |
| PDF 与其他附件 | Zotero | Zotero 文件同步、WebDAV，或复制 Zotero `storage`/链接附件目录 |
| 科研笔记 | PaperNote | 复制 `library-data/notes` 或整个 PaperNote 数据目录 |

GitHub 代码仓库不包含以上个人数据。

## 推荐方案：Zotero 同步 + 复制 Markdown

### 旧电脑

1. 确认 Zotero 已完成同步，附件也能正常打开。
2. 退出 PaperNote，避免复制时恰好正在写笔记。
3. 复制 `library-data/notes` 到移动硬盘、私有云盘或受控同步目录。
4. 如需保留专题、标签、回收站和设置，改为复制整个 `library-data`。

### 新电脑

1. 安装 Zotero，用同一账户完成同步并检查任意 PDF。
2. 克隆或解压 PaperNote，运行对应系统的安装脚本。
3. 在首次启动前，把 `notes` 放入新电脑的 `library-data/notes`；若复制了整个数据目录，则整体放回。
4. 启动 PaperNote，在设置页测试 Zotero。
5. 打开“外部文献”，刷新当前 Zotero 库。
6. 打开一篇已有笔记的文献，核对摘要、论文思路和主要结论。

## 完整复制 Zotero 数据目录

这种方式适用于不使用 Zotero 云同步的情况。两台电脑上都必须完全退出 Zotero 后再复制，避免损坏 `zotero.sqlite`。Zotero 的数据目录位置应以 Zotero“设置 → 高级 → 文件和文件夹”显示的位置为准，不要只复制单独的 `zotero.sqlite`。

链接附件还需要复制其外部根目录，并在新电脑 Zotero 中调整“链接附件根目录”。PaperNote 不管理这些路径。

## PaperNote 怎样重新找到笔记

1. 先查找题录记录指向的笔记文件；
2. 再按 Zotero Key 查找；
3. Key 改变时，尝试唯一 DOI；
4. 再尝试唯一引用键；
5. 最后才尝试唯一题名。

如果候选不唯一，PaperNote 不会猜测，以免把 A 文献的笔记接到 B 文献。

## 只复制 `notes` 还是复制整个数据目录

- 只复制 `notes`：最轻量，Zotero 刷新后重新生成题录缓存；需要重新配置 API 和专题。
- 整体复制 `library-data`：保留全部 PaperNote 状态，但其中可能包含 API Key。只应通过可信介质迁移。

不要复制旧电脑的 `app-config.json`，其中可能是只对旧电脑有效的绝对路径。新电脑可重新选择数据目录，或设置 `PAPERNOTE_DATA_DIR`。

## 迁移后看不到笔记

依次检查：

1. 当前 PaperNote 数据目录是否正确；
2. `notes` 下是否确实有 `.md` 文件；
3. 文献 YAML 的 `zotero_key` 或 `doi` 是否与 Zotero 条目一致；
4. 是否已经刷新当前 Zotero 库，而不是仍显示旧缓存；
5. 是否存在多条相同 DOI/题名造成不唯一。

不要为了修复显示问题移动或重命名 Zotero PDF；PaperNote 只需要题录标识和 Zotero 的正文索引。

