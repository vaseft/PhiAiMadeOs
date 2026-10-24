# Codex 启动 Agent：PhiAiMadeOs / PAMOs V5

你现在继承 PhiAiMadeOs V4 全部 Agent 规范，**新增 RPE Next MCP、原/Next 双格式、GitHub 管理**。当前统一入口为 CODEX_START.md / CODEX_V51_START_HERE.md。先读 AGENTS.md → docs/32_VERSION_CONTROL_POLICY.md → docs/AGENT_V51_DEVELOPMENT.md → V5_CHANGELOG.md → docs/26-30 → 新的 MCP 编辑提示词 → V4 docs/19-25、LLM ChartRefiner 提示词，再执行 v3/v4/v5 contract tests。根 Agent 与 docs/32 的版本控制和安全规则优先。不要声称设计文档即运行成功。

**优先实施一个真正的最小纵向切片：**
- 审计 `kclg-YSJ/rpe-next` pinned commit 的 API 1 模组协议及完整许可（Noncommercial），记录 MOD-PROTOCOL/API types。**没有验证到上游现成 MCP，自己实现本地 stdio MCP server**。
- 实现原 RPE + Next JSON/PEZ 适配器，最先做 round-trip 与预览。原 RPE 文件可以改，不等于能实时操作旧版 GUI。
- 在 PAMOs 后端实现 `rpe_capabilities/list_projects/open_project/get_segment/propose_patch/validate_patch/preview_diff/commit_patch/save/export/revert` 工具，并加入 approval token 与 revision CAS、静态 pure_keys、噪域只读的负面测试。
- 编写可手动启用的 rpe-next `.rpenmod`（通过 API 1 `api.editor.commit`/`await save`）和本地配对 bridge；先用 1 个合法测试 Note 的移动操作验证 `改动→撤销→保存→重开`。没有桥连通就返回 `LIVE_EDITOR_NOT_CONNECTED`。
- 在 PAMOs 生成页加“RPE 编辑器连接状态 / 原版与 Next 导出 / 查看差异 / MCP 可编辑区间”与“调用外部 LLM 后处理”入口；外部 LLM 默认关闭、只输出局部 PATCH、首次发送要预览数据并同意。
- 保留 RTX5060 8GB/16GB 分阶段训练、常规/静态 4/5/6K/其他异像条件生成、**独立噪域禁自动生成**。所有模型或 LLM 修改后仍须走非 AI 审计和人工评分，再导出到 pinned Phira-Pro 实际试玩。
- 使用现有仓库 `https://github.com/vaseft/PhiAiMadeOs.git`，核对 Git 工作区和远端，检查 .gitignore/CI；基于最新 develop 创建 feature branch，小步提交并发起 PR 到 develop，不覆盖远程改动、不直推 main。不要推送到其他个人仓库或第三方上游。
- 每一阶段出真实日志、测试、文件与未完成列表；不调用付费 API、不提交训练音乐，不伪造训练成功或 MCP 连接成功。

最终必须报告：文件清单、运行步骤、MCP tools/list、Next API 1 兼容证据、原/Next 导入导出 roundtrip diff、CLI/本地后端审计、实际 Git remote/commit/PR 证据（如果配置成功）、未验收项。不要只重复本说明。
