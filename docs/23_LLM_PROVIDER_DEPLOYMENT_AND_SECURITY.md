# 23｜API Provider 管理、隐私、运行成本与前端

## 安装/部署边界
- 继续使用 V3 的 Windows + WSL2 + Python 3.12 + FastAPI + SQLite + Vue 3。**API LLM 后处理无需在 RTX 5060 8GB 内再部署大模型**。HTTP 调用走后端 asyncio/httpx（在新依赖文件中添加 `httpx`），不走前端 JS；训练时不要再占用 GPU。
- 首版实现 `OpenAICompatibleChatProvider` 适配器（base_url、model、API key、超时、JSON-mode 能力），允许日后扩展厂商原生 Response/Messages API：每个 provider 必须明确实现独立请求/响应转换与 capability probe，**不能假设任何厂商都兼容 OpenAI Chat Completions**。
- 用户可填写自定义 API 地址、模型、Key、最大响应 tokens、温度、预算/调用上限。Key 不进入 Web 响应、SQLite 明文字段、日志、Crash dump 或 ZIP 导出；推荐 OS 密钥库 (`keyring`)；环境变量作为无交互备选方案。服务端启动时 key 缺失应禁用 API，而不是启动失败。
- 新增 `POST /api/llm/connections/test` 使用便宜的 schema 探针，返回能力而不是 echo 密钥。默认 API 后处理 `off`，外部传输前需要明确用户确认并显示即将传输的字段/字符数。
- 限制端点：HTTPS only 默认；开发中显式允许 `127.0.0.1/localhost` 且不能把此例外当成任意内网 SSRF；不跟随跨域重定向；阻止私有/链路本地/云元数据地址和代理误配置；支持可靠供应商 URL allowlist。用户选择 custom host 时明确警告和二次确认，绝不使用由谱面内容提供的 URL。
- 限速、队列、最大并发 1（16GB 内存）、每曲调用预算、每段超时、按 provider 计费预估/原样显示用量；失败退避重试（只重试网络与 429，遵守 Retry-After），相同请求使用幂等 key/cache，并可手动取消。

## 数据出站最小化
默认允许：最小生成条件、局部可编辑音符/线事件列表、传统 DSP 的曲内证据、确定性审计告警、无个人信息的用户批注。默认禁止：原始整首音频、全量谱面包、曲绘、真实文件路径、用户个人标识、API 密钥、训练集素材、未获授权的资源文件。其他字段需要逐项选择和授权。

## UI 草图
```
谱面生成完成（PAMOs 模型：已加载 / 模型版本）
  → [大模型后处理（可选）]  [关闭 | 仅建议 | 自动应用低风险 | 手工勾选]
  → 服务商/模型、API Key 设置（遮掩）、测试连接、请求字段预览与外发确认
  → 选择全曲扫描 / 当前段落 / 仅修复已报告问题
  → 预算上限、预计片段数、开始/取消
  → 左右分屏：PAMOs v0 vs LLM 候选 v1；逐笔 diff 和音画同步预览
  → 审计结论 + 人工评分 + 一键回退 + 保存候选/最终导出
```

## 错误和审计记录
- SQLite 表：`llm_provider_profile`（无明文 Key）、`postprocess_job`、`postprocess_segment`、`patch_proposal`、`patch_decision`、`chart_version`、`external_upload_consent`、`api_usage_record`。
- 重要审计字段：provider_id、model、temperature、prompt_version/hash、input chart_hash、sampled segment IDs、费用使用量、response sha256、schema check、patch outcome、用户授权时间；默认不持久化完整的外发正文（可选脱敏调试模式）；任何异常都可追溯。
- 严格区分 `LLM_REQUEST_FAILED`, `LLM_RESPONSE_INVALID`, `PATCH_REJECTED`, `POSTPATCH_AUDIT_BLOCKED`, `READY_FOR_HUMAN_REVIEW`。

## 与训练反馈隔离
LLM 修改记录不是人工认可的 ground truth。仅人工通过后的新版本可进入可选 feedback pool，附上人工理由、chart/audio 授权、模型与 patch provenance，和原始 500 曲训练集分离；每次纳入训练要重新 split / 去重 / 检查污染。
