# 百炼 QuizForge

> AI 原生的智能刷题系统。基于 [gygy-open/question-bank](https://github.com/gygy-open/question-bank) 二次开发，遵循 AGPL-3.0-or-later 协议。

面向个人与教研团队的智能刷题系统，当前以**刷题**为核心使用路径。支持导入题库、发布后自主练习、错题本，以及组稿、知识点与 AI 辅助等能力。

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

## 使用教程

### 1. 下载与运行（Windows 便携版）

1. 从 [GitHub Releases](https://github.com/N0mAdam0n/QuizForge/releases) 下载便携版压缩包，**完整解压**到一个可写目录（如 `D:\QuizForge`），不要放在 `Program Files` 下，也不要直接在压缩包里运行。
2. 双击 `QuizForge.exe`。程序以系统托盘图标运行，并自动打开应用窗口（也可在浏览器访问 `http://127.0.0.1:8000`）。
3. 目录中的 `portable.mode` 文件表示“便携模式”：所有数据写在同目录的 `data\` 下，不使用 `%APPDATA%\QuizForge`。请勿删除该文件。
   - `data\app.db`：SQLite 数据库
   - `data\config.json`：本机配置（含自动生成的密钥，勿外传）
   - `data\uploads\`、`data\static\`：上传文件与生成的图片
   - `data\logs\`：运行日志
4. 托盘菜单：**打开百炼**、**局域网共享**、**重启**、**退出**。退出请使用托盘菜单。

> 安装版（`QuizForge-Setup-x.y.z.exe`）数据位于 `%APPDATA%\QuizForge`，其余用法相同。

### 2. 首次初始化与登录

1. 首次打开会进入 **初始化向导**（`/setup`），按提示创建超级管理员账号；向导会自动完成数据库迁移。
2. 未完成初始化前，除初始化相关接口外的 API 都会返回 `503 setup_required`，这是正常现象。
3. 之后在 `/login` 使用管理员账号登录；管理员可在“用户管理”中添加成员或开放注册。

### 3. 配置 AI 模型

1. 进入 **设置 → AI 配置**，添加 AI 服务（支持 Gemini 与 OpenAI 兼容接口），填写地址、API Key 与模型。
2. 在系统设置中选择用途模型：
   - 文本模型（`AI_TEXT_MODEL_ID`）：对话、AI 抽题、组稿建议等；
   - 视觉模型（`AI_VISION_MODEL_ID`）：图片 / 扫描件识别；
   - 向量模型（`AI_EMBEDDING_MODEL_ID`，**可选**）：知识点语义匹配与向量检索。
3. 未配置向量模型时，题库导入、刷题、组稿均可正常使用，只是**语义检索 / 知识点自动匹配不可用**。
4. 可在“学科提示词”中为不同学科定制 AI 提示词。

### 4. 学科、标签与知识点

- **学科**（`/subjects`）：先建学科，题目、题库、组稿都归属学科；可设置成员与角色。
- **标签**（`/tags`）：按标签分类管理，可用于筛选题目。
- **知识点**（`/knowledge-points`）：树形知识点，支持批量导入；配置向量模型后可自动匹配题目。

### 5. 导入题目

1. 打开 **智能导入**（`/import/smart`），上传 Word（`.docx`）、Markdown 或图片。
2. 系统使用**多策略识别**：先用本地规则解析（含“1. / 1、/（1）”等编号题目、统一答案区、答案表），对多种解析结果打分择优；本地解析效果不佳且已配置 AI 时自动回退 AI 抽取。
3. 在审核界面逐题检查题干、选项、答案、解析，修改后确认入库。
4. 在 **导入记录**（`/imports`）查看历史任务；每份导入文档形成一个独立题库，也可另存为组稿。

### 6. 题目与题库管理

- **题目**（`/questions`）：检索、编辑富文本题目（公式、图片），设置题型、难度、可见性。
- **题库**（`/question-banks`）：分为个人空间与共享空间；题库需**发布**后才能刷题，共享题库发布前需审核。

### 7. 组稿与导出

- **组稿**（`/compositions`）：试题篮选题、排版、调整顺序与分值，生成定稿版本快照，可回看历史版本。
- 支持导出 Word / LaTeX；AI 助手可对稿件提出修改建议。

### 8. 刷题与错题本

- **刷题**（`/practice`）：选择已发布的题库，支持顺序、乱序（20/40/60/80/100 题或全部）、按题型、错题练习、区间刷题（按题号范围）。
- 单选、多选、判断自动判分；填空、解答题自评；可选“我不知道”，可开启“答对后自动下一题”。
- **错题本**（`/practice/wrong-book`）：答错或“不知道”的题自动收录，保留正确答案与解析。

### 9. 局域网访问

1. 托盘菜单勾选 **局域网共享**：服务改为监听 `0.0.0.0:8000`，并添加防火墙规则 `QuizForge (8000)`（会弹出一次管理员授权 UAC）。
2. 同一局域网的设备可访问 `http://quizforge.local:8000`（mDNS），或 `http://<本机IP>:8000`。
3. 取消勾选即恢复仅本机访问并移除防火墙规则。手机端网页已做适配。

### 10. 热更新（便携版）

1. 管理员在 **关于** 页面点击“检查更新”；有新版本时可下载（签名校验后支持增量包）。
2. 点击安装后应用会退出，由独立安装器替换程序文件并重启；`data\` 和 `updates\` 不会被覆盖，安装前自动备份数据库。
3. 新版本启动健康检查失败时自动回滚到旧版本，并在下次启动时提示。
4. 相关文件位于便携目录的 `updates\`：`state.json`（更新状态）、`update.log`（安装器日志）、`backup\`（回滚备份）。

### 11. 备份与迁移

- 先从托盘 **退出** 应用，再复制整个便携目录（重点是 `data\`）即可备份；迁移到新电脑时把整个目录复制过去直接运行。
- 升级到新的完整包时，可把旧目录的 `data\` 复制到新目录覆盖。

### 12. 服务器部署（多人协作）

使用 Docker Compose（MySQL + ChromaDB + 后端 + Worker + 前端），见 [docs/server/docker.md](docs/server/docker.md)。Compose 项目名保持为 `question-bank`，以兼容已有数据卷（`question-bank_app_data` 等）；默认数据库名为 `question_bank`。

### 13. 常见问题

| 问题 | 处理 |
|------|------|
| 启动后打不开 / 端口 8000 被占用 | 在任务管理器结束旧的 `QuizForge.exe`，或用 `netstat -ano \| findstr :8000` 找到占用进程后关闭，再重新启动 |
| 一直显示“正在打开百炼…” | 稍等数秒（首次启动需迁移数据库）；仍不行则托盘点“重启”，并查看 `data\logs\` |
| 更新后页面一直显示“正在重启” | 按 F12 打开控制台执行 `localStorage.removeItem('quizforge-update-check'); location.reload()` |
| 接口返回 `503 setup_required` | 尚未完成初始化向导，访问 `/setup` 完成即可 |
| 知识点匹配 / 语义检索不可用 | 未配置向量模型，按第 3 节设置 `AI_EMBEDDING_MODEL_ID` |
| 更新失败 | 查看 `updates\update.log`；应用会自动回滚，数据不受影响 |

### 14. 开发者

- **本地开发**：见下方“本地开发”。
- **测试**：后端 `cd backend && uv run pytest`；前端 `cd frontend && pnpm exec vitest run`。
- **构建便携版**：仓库根目录运行 `powershell -ExecutionPolicy Bypass -File .\build-portable.ps1 [-TestDir <目录>] [-SkipFrontend]`，产物在 `backend\dist\QuizForge-Portable\`。
- **发布热更新**：`powershell -ExecutionPolicy Bypass -File backend\scripts\publish-release.ps1 -Version x.y.z`。脚本依次写入版本号、构建、备份元数据、签名（逐个提示 root/targets/snapshot/timestamp 密钥密码，输入显示为 `*`，输错可重试）、上传并校验服务器。
- **签名私钥必须离线保存在仓库外（默认 `D:\qb-keys`），绝不能提交或上传。** 仓库中只有公开的 `root.json`。

## 快速开始

### Windows 桌面版（推荐个人使用）

下载 [Releases](https://github.com/N0mAdam0n/QuizForge/releases) 中的安装包或便携版，启动后以托盘图标运行，首次打开进入初始化向导创建管理员账号即可。

- 安装版数据：`%APPDATA%\QuizForge`
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

首次配置签名仓库时，在 `backend/` 下运行 `uv run python scripts/manage_portable_updates.py init`。脚本会在仓库外的 `D:\qb-keys` 创建加密签名密钥，并将公开信任根复制到 `backend/deploy/windows/update/root.json`；之后必须重新构建客户端。每次发布时，确保 `app/_version.py` 使用新的 PEP 440 版本、构建便携目录，再运行 `uv run python scripts/manage_portable_updates.py publish`。推荐直接使用 `backend\scripts\publish-release.ps1 -Version x.y.z` 一键完成构建、签名、上传与校验。将脚本输出中的 `targets/` 先于 `metadata/` 上传到已配置的更新服务器；私钥不得上传或提交。更新服务器的 nginx 静态目录、限流及 HTTPS 证书需另行按部署方案配置，客户端发布工具不会修改服务器。

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

本项目基于上游 [gygy-open/question-bank](https://github.com/gygy-open/question-bank)，感谢原作者。

## 贡献

欢迎 Issue 与 Pull Request。开发约定见 `CONTRIBUTING.md`。
