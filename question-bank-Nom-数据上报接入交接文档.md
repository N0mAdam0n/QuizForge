# question-bank-Nom 客户端数据上报接入交接文档

> 读者：负责在 question-bank-Nom 桌面端实现客户端数据上报的编码 agent。
> 依据：服务端代码 `/workspace/telemetry-receiver`（`app/schemas.py`、`app/main.py`、`app/config.py`、`app/ratelimit.py`、`nginx/nginx.conf`、`gen-cert.sh`），以及客户端仓库 `/workspace/repos/question-bank-Nom`（基于 HEAD `d67f11d`）。**接口以服务端代码为准**，本文与代码不一致时，以代码为准，并在第 7 节记录。
> 文档写于 2026-10-22（北京时间，UTC+8）。

---

## 1. 背景与目标

- **用途**：为毕业论文收集匿名使用数据，研究方向有三个：
  1. **逐题置信度校准 / 共形预测**：判断规则解析的置信度 S 是否可靠，并为"S 低于多少就调用 AI"给出有统计保证的阈值。
  2. **基于审核修改的主动学习**：用户在审核阶段改了哪些题、改了什么，作为解析错误的标签。
  3. **IRT 题目质量**：练习作答的对错、耗时、第几次作答，用于估计题目难度和区分度。
- **项目来源**：question-bank-Nom 是 `gygy-open/question-bank` 的 fork，许可证 **AGPL-3.0**（见仓库根目录 `LICENSE`）。
- **匿名规则（硬性要求）**：
  - 不上传任何原文，包括题干、选项、答案、解析、文件名、用户名、学科名。
  - 所有内容标识一律写成 `sha256(install_salt + 规范化内容或内部ID)`，结果是 64 位小写十六进制。
  - `install_salt` 在每次安装时随机生成，只保存在本机，永不上传。
  - 服务端用 `extra="forbid"` 拒绝一切未知字段（`app/schemas.py` 中的 `_Base.model_config`），所以不可能"顺手多传一个字段"。

## 2. 当前服务器现状（2026-10-22 已部署并验证）

| 项 | 值 |
|---|---|
| 云 | 阿里云 ECS，华东，Ubuntu 22.04 |
| 规格 | 2 vCPU / 1.7G 内存 + 4G swap |
| 公网 IP | `120.26.57.15`，**没有域名**，按 IP 访问（不需要 ICP 备案） |
| Docker | 已配置镜像加速：`docker.m.daocloud.io`、`docker.1ms.run` |
| 部署目录 | `/opt/telemetry-receiver` |
| 对外端口 | 只开 443（nginx，自签证书）。app 的 8000 端口只在 compose 内网（`docker-compose.yml` 中 `expose`，没有 `ports`） |
| 健康检查 | `https://120.26.57.15/healthz` 返回 `{"status":"ok"}`（已验证） |
| 备份 | cron 每天 03:30 运行 `backup.sh`（`sqlite3 .backup` 后 gzip，保留 30 天） |
| SSH | root 只允许密钥登录，密码登录已关闭 |

**证书固定（pinning）**
- 整张证书 DER 的 SHA-256 指纹（已确认）：
  `28:DE:60:79:AC:E8:EE:8C:9B:7A:AB:E4:C7:51:71:EB:28:DB:32:93:2C:40:A3:67:B9:78:25:3B:4F:57:FB:DC`
- 证书 SAN 是 `IP:120.26.57.15`，有效期 10 年（`gen-cert.sh`）。
- **SPKI pin（公钥哈希）**：用户报回的值被改动过或不完整，**不可使用**。如果要用 SPKI pin，必须到服务器上用 `gen-cert.sh` 里的同一条命令重新读取：
  ```bash
  cd /opt/telemetry-receiver
  openssl x509 -in certs/server.crt -pubkey -noout | openssl pkey -pubin -outform der | openssl dgst -sha256 -binary | base64
  ```
  在拿到可靠的值之前，客户端只用上面的 DER 指纹，或直接把 `certs/server.crt`（公开文件）作为 CA 文件。

**机密**：`ADMIN_TOKEN` 只放在服务器 `/opt/telemetry-receiver/.env` 里，**绝不能**进入客户端代码、配置或仓库。客户端只会拿到自己注册得到的设备 token。

## 3. 接口规范

基础地址：`https://120.26.57.15`。nginx 只转发 `/healthz` 和 `/v1/*`，其他路径返回 404（`nginx/nginx.conf`）。所有请求与响应都是 `Content-Type: application/json`（CSV 导出除外）。服务端没有开放 OpenAPI 文档（`docs_url=None`）。

### 3.1 端点一览（`app/main.py` → `create_app`）

| 方法 | 路径 | 认证 | 成功码 |
|---|---|---|---|
| GET | `/healthz` | 无 | 200 `{"status":"ok"}` |
| POST | `/v1/devices/register` | 无 | 201 |
| POST | `/v1/events` | `Authorization: Bearer <device token>` | 202 |
| GET | `/v1/admin/export.csv[?event_type=...]` | `Authorization: Bearer <ADMIN_TOKEN>` | 200 text/csv（**只给研究者在服务器侧用，客户端不实现**） |

### 3.2 注册 `POST /v1/devices/register`

请求（`RegisterIn`，`extra=forbid`）：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `consent` | bool | 是 | 必须为 `true`（`Literal[True]`），否则返回 422 |
| `app_version` | string\|null | 否 | ≤32 个字符，只能包含 `[A-Za-z0-9._\- ]` |

响应 201（`RegisterOut`）：
```json
{"device_id": "32位十六进制", "token": "约43字符的 urlsafe 随机串"}
```
- 服务器只保存 token 的 SHA-256，**丢了无法找回**，只能重新注册。
- 客户端要把 `device_id` 和 `token` 存在本地（见 4b），不要写进日志。

### 3.3 上报 `POST /v1/events`

请求体（`EventBatch`）：`{"events": [事件, ...]}`，至少 1 条。

**限制**
- 单批最多 `MAX_BATCH=200` 条，超过返回 413。客户端**按 50 条一批**发送。
- 包体最大 `MAX_BODY_BYTES=262144`（256KB），超过返回 413。nginx 也设置了 `client_max_body_size 256k`。

响应 202：`{"accepted": N, "quarantined": bool}`
- 一批数据要么全部入库，要么全部拒绝：只要有一条不合法，整批返回 422。

**公共字段**（每个事件都有，见 `_Base`）：

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `event_type` | string | 是 | 判别字段，取 `import_parse` / `review_edit` / `practice_answer` / `app_meta` 之一 |
| `schema_version` | int | 是 | 目前只能是 `1` |
| `client_ts` | string\|null | 否 | ISO 8601，建议带时区（如 `2026-10-22T15:30:00+08:00`） |

服务器还会记录 `received_at`（UTC）、`device_id`、`quarantined`。

**通用类型**
- `Hash`：正则 `^[0-9a-f]{64}$`。必须小写，不能带 `sha256:` 前缀。
- `Score`：浮点数，范围 [0, 1]。
- `RawScore`：浮点数，范围 [-10, 10]。
- `QuestionType`（与仓库 `backend/app/models/question.py` 中的 `QuestionType` 枚举一致，另加 `unknown`）：`single_choice`、`multiple_choice`、`true_false`、`fill_in_the_blank`、`free_response`、`unknown`。
- `Short`：string，≤32 个字符，只能包含 `[A-Za-z0-9._\- ]`。

#### (1) `import_parse`：每道解析出的题各一条

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `doc_id_hash` | Hash | 是 | `sha256(salt + 文档原始字节的 sha256)` 或 `sha256(salt + import_task_id)` |
| `question_index` | int 0–10000 | 是 | 题目在本次抽取结果中的下标 |
| `question_type` | QuestionType | 是 | 题目的 `q_type` 字段；不在枚举里就填 `unknown` |
| `rule_score_q` | Score | 是 | 文档级 Q（现有 `_score` 中的 `quality`） |
| `completeness_c` | Score | 是 | 文档级 C（现有 `_score` 中的 `coverage`，已截断到 1） |
| `combined_s` | Score | 是 | `0.65*Q + 0.35*C` |
| `question_rule_score` | Score | 否 | **单题**规则分（`_score` 循环里的 `score`，最大值 0.45+0.3+0.2+0.05=1.0） |
| `raw_q` | RawScore | 否 | 未截断的 Q |
| `raw_c` | RawScore | 否 | 截断前的覆盖率，即 `len(questions)/expected_count`，可以大于 1 |
| `threshold` | Score | 否，默认 0.75 | 填当时实际使用的 `confidence_threshold` |
| `chosen_strategy` | `"rule"`\|`"ai"` | 是 | 最终采用的是规则结果还是 AI 结果 |
| `ai_called` | bool | 是 | 是否调用了 AI |
| `ai_score` | Score | 否 | 调用了 AI 时，填 AI 结果的 `_score` |
| `latency_ms` | int 0–600000 | 是 | 整个 `extract()` 的耗时 |
| `doc_format` | `docx`\|`pdf`\|`md`\|`txt`\|`image`\|`other` | 是 | 来源格式 |
| `expected_count` | int 0–10000 | 否 | 按题号或标签正则估算出的题数 |
| `extracted_count` | int 0–10000 | 否 | 实际抽取出的题数 |

#### (2) `review_edit`：用户在审核阶段确认或修改一道题时发送

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question_ref_hash` | Hash | 是 | `sha256(salt + question.id)`，必须与 `practice_answer.item_hash` 用**同一规则**，便于关联 |
| `doc_id_hash` | Hash | 否 | 与 import_parse 的值一致，用来关联置信度 |
| `question_index` | int 0–10000 | 否 | 与 import_parse 的值一致 |
| `fields_changed` | list，≤8 项 | 是 | 取值：`content`、`options`、`answer`、`analysis`、`q_type`、`difficulty`、`tags`、`other`；未修改时传 `[]` |
| `edit_category` | enum | 是 | `typo`、`boundary_split`、`boundary_merge`、`option_fix`、`answer_fix`、`type_fix`、`format`、`delete`、`other` |
| `accepted_unchanged` | bool | 是 | 解析结果原样通过时为 true |
| `edit_distance` | int 0–100000 | 否 | 只传数值（编辑距离或长度差），**不传文本** |

注意：`edit_category` 没有"未修改"这个值。`accepted_unchanged=true` 时填 `other`，见第 7 节。

#### (3) `practice_answer`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `item_hash` | Hash | 是 | `sha256(salt + question.id)` |
| `question_type` | QuestionType | 是 | |
| `correct` | bool | 是 | 来自 `PracticeAnswerResult.is_correct`。**为 null 时不上报**（需要自评但尚未自评的情况） |
| `time_ms` | int 0–3600000 | 是 | 从题目显示到提交的时间，由前端计时 |
| `attempt_no` | int 1–1000 | 是 | 本机统计的该题第几次作答 |
| `session_hash` | Hash | 否 | 每次进入练习时生成随机 ID，再做哈希 |

#### (4) `app_meta`：启动时发送一次

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `app_version` | Short | 是 | 填 `backend/app/_version.py` 中的 `__version__`（当前是 `0.1.0`） |
| `os` | `windows`\|`macos`\|`linux`\|`other` | 是 | |
| `os_version` | Short | 否 | 例如 `10.0.22631`，需要先按 `Short` 的字符集过滤 |
| `locale` | Short | 否 | 例如 `zh-CN` |

#### 示例

```json
POST /v1/devices/register
{"consent": true, "app_version": "0.1.0"}

POST /v1/events
Authorization: Bearer <token>
{"events": [
 {"event_type":"app_meta","schema_version":1,"client_ts":"2026-10-22T20:00:00+08:00","app_version":"0.1.0","os":"windows","os_version":"10.0.22631","locale":"zh-CN"},
 {"event_type":"import_parse","schema_version":1,"doc_id_hash":"<64hex>","question_index":3,"question_type":"single_choice",
  "rule_score_q":0.82,"completeness_c":1.0,"combined_s":0.883,"question_rule_score":0.95,"raw_q":0.82,"raw_c":1.05,
  "threshold":0.75,"chosen_strategy":"rule","ai_called":false,"latency_ms":41,"doc_format":"docx","expected_count":20,"extracted_count":21},
 {"event_type":"review_edit","schema_version":1,"question_ref_hash":"<64hex>","doc_id_hash":"<64hex>","question_index":3,
  "fields_changed":["answer"],"edit_category":"answer_fix","accepted_unchanged":false,"edit_distance":1},
 {"event_type":"practice_answer","schema_version":1,"item_hash":"<64hex>","question_type":"true_false","correct":true,"time_ms":5300,"attempt_no":1}
]}
```

### 3.4 限流（默认值见 `app/config.py`，服务器可在 `.env` 中调整）

| 层 | key | 规则 |
|---|---|---|
| nginx | IP | 10 r/s，burst 40，超出返回 429 |
| app 注册 | IP | 桶容量 5，约 1 次/分钟恢复 |
| app 上报 | IP | 桶容量 60，1 次/秒恢复 |
| app 上报 | device | 桶容量 30，0.5 次/秒恢复（约 30 秒 1 批）|
| 隔离 | device | 被设备限流累计 20 次后，该设备 `quarantined=true`。之后数据照收，但会打上标记，响应中 `quarantined: true` |

令牌桶保存在进程内存里，服务重启后清零。

### 3.5 错误码与客户端处理

| 码 | 含义 | 客户端动作 |
|---|---|---|
| 201/202 | 成功 | 从本地队列删除已发送的这一批 |
| 400 | 不是合法 JSON | 属于客户端 bug，处理方式同 422 |
| 401 | 缺少 token 或 token 无效 | 清空本地凭证 → 重新注册（前提是用户仍然同意）→ 用新 token 重发一次；再次 401 就暂停上报到下次启动 |
| 413 | 批次或包体过大 | 把批次对半拆开重发；单条仍然 413 就丢弃并记录日志 |
| 422 | schema 不合法 | **整批丢弃**，在本地日志记录 `detail`（服务端已去掉 input，不含原文），不要重试 |
| 429 | 限流 | 读取 `Retry-After`（上报接口为 30 秒），没有就按指数退避（30s→60s→…，上限 30 分钟，加 ±20% 抖动） |
| 5xx / 超时 / 连接失败 / 证书指纹不符 | | 保留队列，指数退避。**证书指纹不符时不发送任何数据**，记录日志 |

错误体格式：`{"detail": ...}`。

## 4. 客户端需要实现的内容

> 桌面端架构：`backend/run.py` 启动本地 FastAPI，用 pywebview 打开窗口（`webview.create_window`）；前端是 Nuxt（`frontend/app/`）。**所有上报都在 Python 后端完成**（证书固定、密钥保存都在后端），前端只通过本地 API 告诉后端用户同意与否、答题耗时等信息。

### (a) 逐题原始评分：`backend/app/services/importing/extract.py`

现状：`MultiStrategyExtractor._score(result, content)`（classmethod）只返回一个文档级 float。它内部先计算每题的 `score`，求平均得到 `quality`，再计算 `coverage = min(len(questions)/expected_count, 1.0)`，最后返回 `quality*0.65 + coverage*0.35`。`extract()` 的判断逻辑是：`local_score >= self.confidence_threshold`（默认 0.75）就返回规则结果；否则调用 AI，`ai_score > local_score` 时采用 AI 结果。

要做的事：
1. 新增 `_score_details(result, content) -> ScoreDetails`（dataclass：`per_question: list[float]`、`quality`、`coverage`、`raw_coverage`、`expected_count`、`extracted_count`、`combined`），并把计算逻辑原样搬过去。
2. 原来的 `_score` 改为 `return cls._score_details(...).combined`。它的签名和返回值**必须保持不变**，因为 `backend/tests/test_importing_extract.py` 依赖它。
3. `extract()` 的分支逻辑和返回值类型（`ExtractionResult`，定义在 `importing/contracts.py`）都不改。把诊断信息挂在一个可选的旁路上，例如在 `ExtractionResult` 上新增默认为 `None` 的 `diagnostics` 字段，或者由 extractor 设置 `self.last_diagnostics`。诊断内容包括：local 与 ai 两边的 details、`ai_called`、`chosen_strategy`、耗时。
4. `mode != "extract"` 或带图片时会直接走 AI。这种情况的处理方式：`chosen_strategy="ai"`、`ai_called=true`，Q/C/S 用 AI 结果的 details。
5. 补充单测：用同一份输入时，新旧 `_score` 的结果相等；阈值判断行为不变。

### (b) 上报模块：新建 `backend/app/services/telemetry/`

- **配置**：在 `backend/app/core/config.py` 的 `Settings` 中新增以下设置项（也可放进 DATA_DIR 下运行时的 `config.json`）：
  - `TELEMETRY_ENABLED: bool = True`：总开关。即使为 True，也要用户同意后才会上报。
  - `TELEMETRY_ENDPOINT: str = "https://120.26.57.15"`
  - `TELEMETRY_CERT_SHA256: str = "28DE6079ACE8EE8C9B7AABE4C75171EB28DB32932C40A367B978253B4F57FBDC"`
- **知情同意**：前端首次启动时弹窗，**默认不勾选**。设置页提供随时撤回的开关，撤回后清空队列和本地凭证、停止上报。同意状态通过新增的本地 API 写入后端。未同意时，所有 `emit()` 都直接返回，不做任何事。
- **安装盐**：首次同意时用 `secrets.token_bytes(32)` 生成，保存在 `settings.DATA_DIR / "telemetry.json"`，同一文件里也保存 `device_id`、`token`、`consent`。帮助函数 `h(x) = sha256(salt + str(x).encode()).hexdigest()`。
- **本地队列**：使用独立的 SQLite 文件 `DATA_DIR/telemetry_queue.db`（表 `queue(id, json, created_at, tries)`），**不要**放进应用主库。队列上限 10000 条，超出时删除最旧的。
- **发送**：后台 asyncio 任务（在 `backend/app/main.py` 的 `lifespan` 中启动和取消），每 3 分钟或积压满 50 条时发一批，每批 50 条，按 3.5 处理返回码。
- **证书固定**：
```python
import hashlib, socket, ssl, httpx
def verify_pin(host: str, port: int, pin_hex: str) -> None:
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=5) as s, ctx.wrap_socket(s) as t:
        got = hashlib.sha256(t.getpeercert(binary_form=True)).hexdigest().upper()
    if got != pin_hex.replace(":", "").upper():
        raise ssl.SSLError(f"cert pin mismatch: {got}")
# 更推荐：把服务器 certs/server.crt（公开文件）打包进客户端，作为唯一信任根，系统 CA 不参与校验：
client = httpx.AsyncClient(base_url=endpoint, verify=str(bundled_server_crt), timeout=10)
```
  `verify_pin` 只是单独握一次手做比对，和后续请求不是同一个连接。最稳妥的做法是两者都做：`verify=` 用打包的证书，启动时再用 `verify_pin` 校验一次指纹。**禁止** `verify=False`。

### (c) 埋点位置

| 事件 | 挂接点 | 说明 |
|---|---|---|
| `import_parse` | `backend/app/services/doc_processor.py` → `DocProcessor`：`process_markdown`（第 55 行附近）以及其他调用 `self._extractor_for(method).extract(...)` 的方法（第 72、111 行）| 只在 `method == "auto"`，也就是走 `MultiStrategyExtractor` 时上报。`doc_format` 由调用它的方法决定：`process_markdown` 对应 md，docx 对应 docx，image 对应 image。`doc_id_hash` 用 `task_id`。用 (a) 的诊断信息为每道题生成一条事件 |
| `review_edit` | `backend/app/api/v1/endpoints/questions.py`：`update_question`（PUT `/{id}`，capability `question.update`）、`review_question`（POST `/{id}/review`）、`batch_confirm_questions`（POST `/batch-confirm`）、`update_questions_batch`、`delete_questions_batch`；整卷导入：`paper_imports.py` 中的 `commit_paper_import` | 在 capability 执行前读取旧值，执行后与新值比较，得到 `fields_changed`；分类规则自己定。直接确认、未修改的为 `accepted_unchanged=true`。**需要核实**哪条路径对应"导入后审核"（前端：`frontend/app/pages/import/smart.vue`、`frontend/app/components/BatchImportCard.vue`） |
| `practice_answer` | `backend/app/api/v1/endpoints/practice.py` → `submit_practice_answer`（POST `/answers`，第 699 行），结果来自 `_grade_answer` 和 `PracticeAnswerResult` | `PracticeAnswerSubmit`（`backend/app/schemas/practice.py`）**目前没有耗时字段**。需要在 `frontend/app/pages/practice/index.vue` 中计时，并给 schema 新增可选字段 `time_ms: Optional[int] = None`，保持向后兼容。`attempt_no` 由后端上报模块按 `item_hash` 在本地计数 |
| `app_meta` | `backend/app/main.py` 的 `lifespan` 启动阶段 | 用户同意后，每次启动发一条 |

### (d) 配置开关
- 环境变量或配置项 `TELEMETRY_ENABLED=false` 时，上报完全关闭：不注册、不建队列、不发网络请求。
- `TELEMETRY_ENDPOINT` 可配置，本地测试时指向 `http://127.0.0.1:8000`。走 http 时跳过证书固定，**只允许 127.0.0.1 或 localhost 使用 http**。

### (e) 离线与不阻塞
- `emit()` 只写本地队列，不发网络请求，并用 `try/except Exception` 包住全部逻辑。上报模块的任何异常都不能影响导入、审核或练习。
- 网络只由后台任务处理。离线时数据在队列中积压，联网后补发。
- 记录埋点的额外开销应小于 5ms（只是一次本地 SQLite insert）。

## 5. 验收标准与测试方法

**验收标准**
1. 未同意时：抓包或 mock 验证没有任何对外请求，也没有生成 `telemetry.json`。
2. 同意后：四类事件都能到达服务端，并且字段通过 `app/schemas.py` 的校验。
3. 对本地队列和导出的 CSV 用 grep 搜索样例题干的任意片段，**没有命中**。
4. `_score` 的行为不变，`backend/tests/` 下原有测试全部通过。
5. 断网时导入和练习正常进行，联网后补发成功。证书指纹不符时拒绝发送。
6. 撤回同意后：队列被清空，不再发送任何请求。

**本地测试（先做这一步）**
```bash
cd /workspace/telemetry-receiver
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt -i https://mirrors.aliyun.com/pypi/simple/
.venv/bin/python -m pytest -q        # 服务端自带 13 个测试，应全部通过
mkdir -p data && ADMIN_TOKEN=devtoken DATABASE_URL=sqlite+aiosqlite:///./data/dev.db .venv/bin/uvicorn app.main:app --port 8000
# 客户端：TELEMETRY_ENDPOINT=http://127.0.0.1:8000 启动桌面端，导入/审核/练习各操作一次
curl -H "Authorization: Bearer devtoken" "http://127.0.0.1:8000/v1/admin/export.csv" | head
```
客户端单测：用 `httpx.MockTransport` 或上面的本地 receiver，覆盖 401 重注册、422 丢弃、429 退避、离线积压这几种情况。

**连服务器测试**：把 endpoint 改回 `https://120.26.57.15`，用一台测试机走一遍流程。然后由**用户本人**在服务器上导出数据核对（ADMIN_TOKEN 不交给 agent 或客户端）：
```bash
curl -k -H "Authorization: Bearer $ADMIN_TOKEN" "https://127.0.0.1/v1/admin/export.csv?event_type=import_parse" | tail
sqlite3 /opt/telemetry-receiver/data/telemetry.db "select event_type,count(*) from events group by 1"
```
测试数据可以按 device_id 删除（README 中有对应的删除命令），以免污染研究样本。

## 6. 约束与注意

- **AGPL-3.0**：修改后的版本分发给内测用户时，必须同时提供对应的完整源码（包括上报模块）。在关于页或 README 中给出源码地址，保留原作者版权声明。服务端 telemetry-receiver 是独立程序，是否开源由用户决定。
- **个人信息保护法**：同意弹窗中必须写明收集目的、字段清单、保存期限、联系方式和撤回方式。保存期限目前是占位："答辩结束后 6 个月（具体日期待用户确定：____）"。去标识化数据仍按个人信息对待。数据存放在境内，不出境。
- **不要 push**：没有用户明确批准，不得推送到 GitHub，也不得创建 PR 或发布版本。只在本地分支提交。
- **最小改动**：不改变上游原有行为，包括解析阈值、AI 回退逻辑、原有 API 的响应结构。新增的 schema 字段一律可选，带默认值。
- **扩充服务端字段的流程**：
  1. 修改 `/workspace/telemetry-receiver/app/schemas.py`，新增一个 `schema_version: Literal[2]` 的新模型，或把 `Literal[1]` 放宽为 `Literal[1, 2]` 并给新字段加默认值。旧版客户端必须仍能通过校验。
  2. 补充 `tests/test_api.py` 并让测试通过。
  3. 用户打包后上传到服务器，执行 `cd /opt/telemetry-receiver && docker compose up -d --build`。payload 以 JSON 存储，数据库不需要迁移。
  4. 先部署服务端，再发布客户端。服务端更新前，客户端发送新字段会得到 422。

## 7. 待办与已知问题

1. **SPKI pin 尚未确认**（见第 2 节），确认前只用 DER 指纹或打包的证书。
2. `review_edit.edit_category` 没有"未修改"的取值，`accepted_unchanged=true` 时暂时填 `other`。下个 schema 版本可以考虑新增 `none`。
3. `practice_answer.correct` 必填。需要自评、`is_correct` 为 null 的题，在自评之前不上报。如果以后需要记录"不会"（`dont_know`），要扩展 schema。
4. 后端目前没有作答耗时数据，需要前端计时，并给 `PracticeAnswerSubmit` 新增可选字段。
5. "导入后审核"的确切保存路径需要编码 agent 读 `smart.vue`、`BatchImportCard.vue` 后确认（候选的后端接口见 4c）。
6. 服务端令牌桶在进程内，重启后清零；数据库中的 `strikes` 字段会一直累加，不会衰减。
7. 服务端没有设备自助删除数据的接口，目前只能由用户在服务器上手动执行 SQL。
8. nginx 访问日志包含 IP（10MB×3 滚动），应用数据库中不存 IP。
9. 服务端的 Docker 镜像只在 ECS 上构建验证过，本地 box 没有 docker。
