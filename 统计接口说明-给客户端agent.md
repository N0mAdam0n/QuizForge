# 公开统计接口 `/v1/stats/public`（客户端展示"累计用户数"）

> 服务端实现：`/workspace/telemetry-receiver/app/main.py` 中的 `public_stats` 和 `_core_stats`；限流参数见 `app/config.py`（`STATS_*`）；nginx 配置见 `nginx/nginx.conf` 中的 `location = /v1/stats/public`。

**请求**
```
GET https://120.26.57.15/v1/stats/public
Authorization: Bearer <device token>     # 可选。不带也行；带了无效 token 也不会报 401，按匿名处理
```
证书固定方式与上报接口相同（第 4(b) 节）。

**响应 200**
```json
{"total_devices": 128, "active_devices_7d": 31, "active_devices_30d": 77,
 "total_events": 45210, "generated_at": "2026-10-23T01:20:00.123456Z"}
```

| 字段 | 含义 |
|---|---|
| `total_devices` | 已注册且未被隔离的设备数。注册时必须 `consent=true`，所以这个数等于"同意参与的安装数" |
| `active_devices_7d` / `active_devices_30d` | 近 7 天 / 30 天内服务器收到过事件的去重设备数，不含被隔离的设备 |
| `total_events` | 累计收到的事件数，不含被隔离的数据 |
| `generated_at` | 统计时间，UTC ISO 8601 |

响应里只有这几个粗粒度计数，不含任何设备 ID 或单设备数据。客户端只能依赖上表中的字段，**遇到未知字段要忽略**。

**缓存语义**
- 服务端在进程内缓存 60 秒（`STATS_CACHE_SECONDS`）。60 秒内的所有请求返回同一份结果，`generated_at` 也不变。响应头带 `Cache-Control: public, max-age=60`。
- 客户端建议在启动时请求一次；打开"关于"或首页时，如果距离上次请求超过 10 分钟再请求。**不要轮询**。结果可以缓存到本地，离线时显示上次的值。

**限流**
- nginx：每 IP 每分钟 30 次，burst 10。
- app：令牌桶容量 10，每 5 秒恢复 1 个。带有效设备 token 时按设备计桶，否则按 IP 计桶。
- 超出返回 429，响应头 `Retry-After: 60`。

**含义与展示**
- "用户"指**同意参与的注册设备，也就是安装数，不是自然人**。同一个人重装或换电脑会被算成多台；撤回同意、重新注册也会产生新设备。
- 展示文案建议："累计 N 位用户参与"或"已有 N 台设备参与研究"，N 取 `total_devices`。可以在副标题显示"近 30 天活跃 M"。数字较小时（比如 < 5），可以不显示，或只显示"内测中"。
- 是否显示统计数字与是否同意上报无关。但如果用户没有同意上报，客户端**不带 token**。可以考虑在关闭上报时连统计也不请求，由产品决定。

**失败处理**
- 任何失败（网络、超时、证书不符、429、5xx、JSON 解析失败）都**静默处理**：不弹窗，不阻塞 UI；有本地缓存就显示缓存值，没有就隐藏这个数字。只写一行 debug 日志。
- 超时建议设为 5 秒。

**禁止事项**
- **绝不**在客户端嵌入 `ADMIN_TOKEN`，也不要调用 `/v1/admin/*`。研究者另有 `/v1/admin/stats`（按事件类型和版本分组、近 30 天每日新增、隔离计数），只供研究者在服务器侧使用。
