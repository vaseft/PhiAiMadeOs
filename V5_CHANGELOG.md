# PhiAiMadeOs / PAMOs — V5 变更日志（2026-10-24）

本版在 V4 全部约束基础上追加 **RPE 编辑 MCP / 双格式适配 / GitHub 版本控制**，不会取消 V4 的 API LLM 后处理与非 AI 审计。

- 新建 PAMOs 自有 `pamos-rpe-mcp`（MCP stdio），配套 `PAMOs Bridge` 与独立 `pamos-rpe-bridge` RPE Next 模组。**没有验证 rpe-next 仓库内已有可直接使用的 MCP 服务**；已验证它提供 API 1 模组协议，包含 `editor.commit()`、`editor.save()` 等接口，故本版明确要求自己实现 MCP 桥接，不得编造上游 MCP 名称或 npm 包名。
- 双格式：`rpe_original` 和 `rpe_next` 分别导入、校验、编辑、输出；AI 通过统一 IR 和 adapter 实现增量操作。RPE Next 特有事件跨格式导出时要显式阻断或人工确认有损导出，不能静默删除噪域。
- Live edit 通过 RPE Next 自有模组 API 1 和已明确配对的本地 bridge 完成；原版 RPE 没有经过验证的 live API，先提供原版 JSON/PEZ 离线编辑闭环，不得把离线文件适配宣称为原版 RPE 窗口控制。
- MCP 绝不绕过本地补丁校验、正式**非 AI**审计、人工审核；分 read/propose/validate/apply/save/export 权限，写入工具默认需人为批准。
- GitHub 负责**代码**版本、CI、PR、发布；RPE Next 内置谱面 VCS 和 PAMOs 自己的候选版本历史各自独立。模型权重/500 首音频/私人 API Key 不上传 GitHub；每个训练 checkpoint 记录对应代码 commit。
- 维护授权边界：Phira Pro GPL-3.0；rpe-next PolyForm Noncommercial 1.0.0，不能以 GPL 许可覆盖/合并搬运 rpe-next 代码。
- API 二次优化提示词沿用 V4，增加 MCP 可操作 Agent 的独立严格提示词。
