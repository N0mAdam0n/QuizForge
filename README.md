# QuestionBank

面向个人与教研团队的题库系统，当前以**刷题**为核心使用路径。支持导入题库、发布后自主练习、错题本，以及组稿、知识点与 AI 辅助等能力。

## 主要功能

### 刷题（核心）

- **自主练习**（`/practice`）：从个人空间或共享空间选择题库后开始。
  - 顺序刷题
  - 乱序刷题（20 / 40 / 60 / 80 / 100 题或全部）
  - 按题型刷题
  - 错题练习
  - 区间刷题（按题号范围）
- 单选、多选、判断题自动判分；填空题、解答题由用户自评。
- 支持“我不知道”，答错或选择不知道会自动记入错题本。
- 可开启“答对后自动下一题”。
- **错题本**（`/practice/wrong-book`）：汇总所有可访问题库中的错题，保留正确答案与解析。

### 题库管理

- 每份导入文档作为一个独立题库（基于导入任务）。
- 个人空间 / 共享空间。
- 题库需发布后才可进入刷题；共享题库发布前需审核。
- 支持在题库详情中查看、修改题目后发布。

### 其他能力

- **智能导入**：Word / Markdown / 图片等，AI 抽取或本地解析后审核入库。
- **组稿工作台**：个人 / 共享空间，试题篮、排版、定稿快照，导出 Word / LaTeX。
- **知识点与标签**：树形知识点、标签分类，支持向量检索匹配。
- **AI 助手**：对话、找题、对稿件提出修改建议等。
- **学科与权限**：多学科、成员角色、审核流程、操作审计。

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | Python 3.13+、FastAPI、SQLAlchemy Async、Alembic、Pydantic |
| 前端 | Nuxt 4（SPA）、Vue 3、TypeScript、Tailwind CSS 4、Shadcn UI |
| 数据 | 桌面版 SQLite；服务器版 MySQL 8。向量检索使用 ChromaDB |
| AI | 统一 Provider 接口，支持 Gemini 与 OpenAI 兼容接口，配置存数据库 |
| 文档与公式 | Pandoc、Tiptap、KaTeX、MathLive |
| 桌面与部署 | PyInstaller + 系统托盘 + pywebview；Docker Compose |

## 快速开始

### Windows 桌面版（推荐个人使用）

下载 Releases 中的安装包或便携版，启动后以托盘图标运行，首次打开进入初始化向导创建管理员账号即可。

- 安装版数据：`%APPDATA%\QuestionBank`
- 便携版数据：解压目录下的 `data` 文件夹

### 服务器版（Docker Compose）

适用于多人协作。包含 MySQL、ChromaDB、后端、Worker 与前端。

```bash
# 复制并填写环境变量后启动
docker compose up -d
```

详见 `docker-compose.yml`。

### 匿名研究数据收集

首次使用时会显示简明的数据收集声明；默认不勾选，拒绝不会影响软件使用。只有明确同意后，后端才会创建本地匿名上报队列并发送应用版本、解析统计、审核类别及练习正误/耗时等字段。题目原文、用户名、文件名和学科名称不会进入上报数据；本机随机盐不上传，标识以盐化 SHA-256 处理。接收服务器位于中国境内，计划保留至 2027-10-22（届时若服务器仍租用且数据未主动删除，可能继续保留）。

同意状态按一个后端实例统一生效，不按账号隔离；用户菜单中的“数据收集声明”可随时撤回。撤回会停止该实例后续上报并清空待上传队列及本地设备凭证。系统设置中的累计参与安装数仅管理员可见，来自接收服务器的匿名汇总；只统计同意参与的安装，不代表独立自然人数。可通过环境变量 `TELEMETRY_ENABLED=false` 完全关闭上报；仅用于本机测试时，可将 `TELEMETRY_ENDPOINT` 设置为 `http://127.0.0.1:<port>`。

### Windows 便携版热更新

Windows 便携版支持通过 TUF 签名元数据检查增量或完整更新；安装版及 Docker 部署仍使用原有更新方式。更新包只替换程序文件，不覆盖便携目录中的 `data/` 和 `updates/`；安装前会备份 SQLite 数据库，启动迁移检查失败时自动恢复程序与数据库。热更新需要客户端内置受信任的 TUF `root.json`，并由更新服务器提供签名元数据和目标文件；未配置这些发布条件的版本继续提供 GitHub Releases 手动更新。下载请求不携带遥测设备标识或 token，但更新服务器的常规访问日志可能记录连接 IP。MySQL 部署不支持此便携版热更新流程。

首次配置签名仓库时，在 `backend/` 下运行 `uv run python scripts/manage_portable_updates.py init`。脚本会在仓库外的 `D:\qb-keys` 创建加密签名密钥，并将公开信任根复制到 `backend/deploy/windows/update/root.json`；之后必须重新构建客户端。每次发布时，确保 `app/_version.py` 使用新的 PEP 440 版本、构建便携目录，再运行 `uv run python scripts/manage_portable_updates.py publish`。将脚本输出中的 `targets/` 先于 `metadata/` 上传到已配置的更新服务器；私钥不得上传或提交。更新服务器的 nginx 静态目录、限流及 HTTPS 证书需另行按部署方案配置，客户端发布工具不会修改服务器。

### 本地开发

后端（`backend/`）：

```bash
# 依赖管理使用 uv
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

前端（`frontend/`）：

```bash
pnpm install
pnpm dev
```

## 项目结构

```
.
├── backend/          # FastAPI 后端
│   └── app/
│       ├── api/v1/endpoints/   # 路由（含 practice）
│       ├── models/             # 数据模型
│       ├── services/           # 业务服务（导入、导出、AI 等）
│       └── ...
├── frontend/         # Nuxt 4 前端
│   └── app/
│       ├── pages/              # 页面（practice、question-banks 等）
│       └── components/
├── docs/             # 文档站点
└── docker-compose.yml
```

## 开源协议

[AGPL-3.0-or-later](LICENSE)

- 可自由使用、修改、分发，包括商业使用。
- 通过网络提供服务时，必须公开修改后的代码。
- 衍生作品须使用相同协议。

## 贡献

欢迎 Issue 与 Pull Request。开发约定见 `CONTRIBUTING.md`。
