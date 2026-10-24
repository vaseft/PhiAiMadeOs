# 27 — PAMOs RPE MCP 工具契约、审批和事务

## 27.1 传输和版本协商
MCP 标准 JSON-RPC，第一代选择 **stdio server**（由 Codex 启动 Python PAMOs MCP entrypoint）。MCP 服务端再调用本地后端，不要求外部云服务器。使用官方 MCP Python SDK；运行时应执行 `tools/list` 检验实际工具集合。MCP 接口版本和谱面 RPEVersion 是不同概念。

服务器引导文本的前 512 字符必须包括：**所有写操作需要用户确认；噪域不可写；pure_keys 判定线静态；每次修改重新审计；不能绕过沙盒路径与版本哈希。**

| Tool | 输入关键字段 | 输出/状态 | 风险 |
|---|---|---|---|
| `rpe_capabilities` | adapter, runtime | 支持矩阵 + pinned SHA | read |
| `rpe_list_projects` | root_id, cursor | 项目 ID/名称（无任意路径） | read |
| `rpe_open_project` | project_id, adapter | session_id/revision | read |
| `rpe_get_segment` | session_id, start_beat, end_beat, include | event list + DSP refs/line sample | read |
| `rpe_get_warnings` | session_id, revision | 独立审计证据 | read |
| `rpe_propose_patch` | source_hash, operations[], constraints | proposal_id/diff | suggestion |
| `rpe_validate_patch` | proposal_id, revision | validation_id/blocked reasons | no write |
| `rpe_preview_diff` | proposal_id | beat windows/diff/preview token | read |
| `rpe_commit_patch` | proposal_id, validation_id, revision, approval_token | new revision/audit_job_id | **write** |
| `rpe_save_project` | session_id, expected_revision, approval_token | saved_revision / error | **write** |
| `rpe_export_project` | revision, target_format, lossy_allowed=false | package id / compatibility report | **write** |
| `rpe_revert_revision` | target_revision, approval_token | new revision preserving history | **write** |
| `rpe_editor_seek` | beat, pause=true | editor state (read/reposition) | state |

`list_projects` 只枚举被注册的项目数据目录，禁止任意系统路径；`open_project` 不接受 `/etc`、`C:\Users` 等外部路径。分页限制与单次响应事件上限必须在服务端实现。

## 27.2 PATCH 语义
可用操作仅从现有 `schemas/llm_patch.schema.json` 中的白名单扩展，具体 API JSON Schema 应避免新增不受控制的 `replace_document`、`execute_script`、`raw_json_merge`、`url_fetch` 类型。`target_id` 是稳定 ID，`expected_revision` CAS；增加 Note 由服务端分配新 ID。其余副作用必须明确列出。

禁止修改：`noise_areas`、`blockAreaList`、`BPMList`、真实判定/分数/Combo、`audio_ref`、`offset`、`chart_mode`、K 值、训练许可证数据、GitHub token。任何 `mode=pure_keys` 的 `TUNE_LINE_EVENT` 被强制拒绝，即使调用方试图绕过 schema。

## 27.3 原子事务
`READ snapshot -> PROPOSE -> VALIDATE -> PREVIEW -> APPROVE -> CAS COMMIT -> AUDIT -> SAVE -> EXPORT`。
- proposal 只含 patch，不编辑任何文件。
- 审批 token 由 PAMOs UI 本机产生，绑定 user/session/proposal/revision/过期时间，MCP Client 不能自行伪造。
- 保存工作副本前写入原始备份。提交必须同时记录内容哈希、作者、时间、模型与 prompt/provider（隐私可用摘要）、target runtime SHA。
- 一处硬性验证失败则整批 rollback；可发出局部拒绝原因供新一轮提议。
- 重复提交同一幂等 key 返回同一 revision，不能重复插音符。
- `apply_safe` 也必须经过明确用户提前授权的受限策略，不等同无审核地覆盖；默认 `suggest`。

## 27.4 格式兼容矩阵
| 特性 | 原版 RPE | RPE Next | PAMOs V1 |
|---|---|---|---|
| 普通 Note | 必须测试 | 必须测试 | 读/改/导出 |
| 判定线静态/运动 | 必须测试 | 必须测试 | 限定 patch |
| Next 曲线轨迹 / 模组事件 | 不保证 | 可见文档支持 | 只读保留，探针后才可编辑 |
| 噪域 | 不兼容/需确认 | 支持独立格式 | **只读保留，禁自动编辑/训练** |
| 编辑器直接实时操作 | 未证实可用接口 | 通过自建模组桥接 | V5 待实施验证 |
| JSON/PEZ 导出 | 按实测 | README 支持 | 拒绝无证据的兼容声明 |

## 27.5 验收样例
- `pure_keys` 4/5/6K：AI 调 MCP 修改 Note 轨道，判定线前后位移/旋转全部恒定；恶意转动态线 100% 拒绝。
- `regular`：安全时间微调完成后能在 rpe-next 中撤销/redo，保存、导出、重新导入与 hash 对照。
- `anomaly`：保留噪域资源与内部事件，不允许自动更改其任何子字段。
- `rpe_original` 原版 JSON 导入 Next，逐项比较 offset/BPM/note/line；导出原版并回读。Next 特有字段的原版导出默认 BLOCK。
- 断线、旧 revision、审批缺失、恶意参数、坏包、同时编辑、AI prompt 注入时不修改工作谱面。
