# 29 — API LLM 后处理与 RPE MCP 直接编辑：职责划分

存在两个独立的 LLM 使用入口，不要混为一个服务：

**A. PAMOs 后处理 ChartRefiner**：用户在 PAMOs 生成页主动启用外部 API（默认关闭）。调用 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`，只输入授权裁剪的谱面局部窗口、DSP 警告和模型条件，返回 `schemas/llm_postprocess_proposal.schema.json` 的 JSON PATCH。经本地约束与人工确认后，才进入 MCP commit。该功能不要求 RPE Next 处于运行状态，离线文件适配也可运行。

**B. RPE MCP Editor Agent**：用户在 Codex 或其他 MCP 客户端输入自然语言“把 48—52 小节的 6K 重复音调整得更舒服”，AI 通过 `rpe_get_segment → rpe_propose_patch → rpe_validate_patch → rpe_preview_diff → 用户确认 → rpe_commit_patch → rpe_save_project` 对已经打开的 RPE 谱面做实际编辑。专用系统提示词见 `prompts/PAMOS_RPE_MCP_EDITOR_SYSTEM_ZH.md`。它必须尊重当前 IR、目标 runtime 和独立非 AI 审计，不得使用任意文件写入代替受控 patch。

两条路径共同的保底策略：
- 不得把音乐特征统计当作“AI 已亲耳听到音乐”，不能凭 DSP 峰值硬吸附合法反拍。
- 不得将 RPE Next 程序可编辑的噪域视为第一代模型/LLM 可以自动制作的噪域。**V1 noise area 始终禁写**。
- 禁止真实修改 combo/得分/判定逻辑；视觉 UI 也需要特性矩阵验证。
- 纯配置是真正 4K/5K/6K 固定轨道，判定线整曲静态；高狂野度只影响配置。
- LLM 无法自行批准其提议的写操作；人类批准 token 由后端 UI 生成，不能出现在 LLM 提示词输入中。
- 网络不可达、非法 JSON、返回超时、低置信度时，保留 PAMOs 原始候选，并显式呈现失败原因。
- LLM 再处理**不计入非 AI 审计的质量打分**。正式 DSP/几何审计永远在提案应用后独立重新执行。

### Prompt 配置（建议）
1. 系统提示词版本及 SHA 写入每次 postprocess job。
2. `max_tokens` 以各 API 能力为准；始终使用服务器端强制 JSON Schema/结构校验。
3. 在 5060 8GB + 16GB 内存设备上避免同时加载本地大模型；大模型二次加工通过可配置 API，默认不上传原始音频，仅送本地 DSP 摘要和有限音符/运动事件。
4. 提示词和 tool 结果有字符/对象数量上限，用户评论、曲名、文件名均视为不可信材料。
