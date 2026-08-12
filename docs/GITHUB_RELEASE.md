# GitHub 发布清单

## 发布前

1. 确认 `.gitignore` 排除了 `library-data`、`.venv`、`node_modules`、缓存、日志、`app-config.json`。
2. 搜索并确认没有 API Key、个人邮箱、绝对数据路径或科研笔记进入待提交文件。
3. 运行后端测试：

   ```powershell
   .venv\Scripts\python.exe -m pytest -q
   ```

4. 运行前端构建：

   ```sh
   cd frontend
   npm ci
   npm run build
   ```

5. 确认 `frontend/dist-portable` 已更新并准备提交。
6. 在公开发布前自行选择许可证；没有许可证时，默认不授予他人复制、修改或再发布代码的权利。

## 首次创建远端仓库

在 GitHub 创建一个空仓库，不勾选自动生成 README。然后在项目根目录执行：

```sh
git init
git add .
git status
git commit -m "Initial PaperNote release"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

在 `git commit` 前仔细检查 `git status`：不应出现 `library-data`、`.venv`、`node_modules` 或 `app-config.json`。

## 新电脑从 GitHub 安装

```sh
git clone <你的仓库地址>
cd PaperNote
```

随后运行 `setup.bat`（Windows）或 `./setup.sh`（macOS/Linux）。GitHub 只恢复程序，不恢复 Zotero 库和科研笔记；个人数据按 [MIGRATION.md](MIGRATION.md) 单独迁移。

