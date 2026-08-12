# PaperNote Markdown 笔记格式

PaperNote 每篇文献对应一个 UTF-8 Markdown 文件，默认位于 `library-data/notes`。文件可以脱离 PaperNote 直接阅读、检索、备份和版本管理。

## 示例

```markdown
---
papernote_format: 1
paper_id: 123
zotero_key: ABCD1234
citation_key: Author2024Title
title: "论文题名"
doi: "10.xxxx/xxxxx"
updated_at: "2026-08-11T10:00:00+08:00"
---

# 论文题名

## 摘要（原文摘要的中文翻译）

……

## 研究问题

……

## 论文思路（写作逻辑）

……

## 数据集

……

## 气象变量

……

## 研究区域

……

## 时间范围

……

## 研究方法

……

## 模式 / 模型

……

## 主要结论

……

## 局限性

……

## 可借鉴点

……

## 自由笔记

……
```

## 哪些字段用于跨电脑关联

按可靠性从高到低：

1. `zotero_key`：Zotero Item Key；官方同步或完整迁移 Zotero 数据目录时通常保持不变；
2. `doi`：Key 改变时的首选后备标识；
3. `citation_key`：没有 DOI 时的后备标识；
4. `title`：只有唯一匹配时才使用。

`paper_id` 只是当前 PaperNote 题录缓存中的内部编号。换电脑后它可以改变，不需要人工修改，也不应把它作为永久链接。

## 手工编辑规则

- 可以直接修改各二级标题下的正文，PaperNote 下次打开会读取修改。
- 建议保留 YAML 头部的 `zotero_key`、`doi`、`citation_key` 和 `title`。
- 建议保留预设二级标题；没有内容的栏目留空即可。
- 不要在正文中再增加一个同名预设二级标题，否则只能读取第一个对应区块。
- 历史版本在 `notes/.history`，不会混入普通文献列表。

## 文件名

有 Zotero Key 时使用 `<Zotero Key>.md`。没有 Key 时使用引用键或本地稳定名称。PaperNote 重新关联后会继续使用找到的旧笔记文件，避免迁移时重复生成两份笔记。

## Obsidian

可把 `library-data/notes` 直接作为 Vault，或同步到已有 Vault。推荐按 YAML 字段建立 Dataview 查询；不要让 Obsidian 插件批量删除 YAML 标识字段。

## 最小备份

只关心科研笔记时，至少备份：

```text
library-data/notes/
```

还需要专题、标签、回收站和 PaperNote 设置时，再备份：

```text
library-data/papernote-state.json
```

Zotero 题录、附件路径和 PDF 由 Zotero 自己单独备份或同步。

