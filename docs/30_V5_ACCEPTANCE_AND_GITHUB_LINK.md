# 30 — V5/V5.1 实施任务及完成门槛

本文件描述产品后续验收目标，不是本次导入已完成的结果。当前入口为根 `CODEX_START.md` 与 `CODEX_V51_START_HERE.md`；根 `AGENTS.md` 和 `docs/32_VERSION_CONTROL_POLICY.md` 的安全、分支与发布规则优先。V5.1 离线原型具体边界见 `docs/31_V51_RUNNABLE_OFFLINE_MCP.md`。

## G0：锁定仓库与许可
Codex 输出当前 upstream SHA、License、API 1 mod protocol、原/Next JSON/PEZ 兼容差异，并复核 Phira-Pro 的噪域功能。**明确标注上游未发现可证实的现成 MCP server**；为 PAMOs 开发自己的。核实当前 origin 为用户指定的 `https://github.com/vaseft/PhiAiMadeOs.git`，保留现有历史与本地修改，基于最新 develop 使用 feature 分支，不向无关仓库推送。

## G1：本地 RPE MCP（stdio + sandbox）
- `tools/list` 确实列出全部规定工具；至少可读取一份示例 RPE JSON，完成 patch 提议、validate、diff、经人工批准后提交、undo、导出并重新导入。
- API 能拒绝路径遍历、过期审批、未知操作、旧 revision、破坏 Hold、写噪域、pure_keys 线运动。
- Tool schema 有 JSON 负向测试；未接实时编辑器时明确输出 `LIVE_EDITOR_NOT_CONNECTED`。

## G2：Live editor bridge
- 编写 PAMOs 自有 `.rpenmod`，手动启用本地 RPE Next 0.12.2 pinned；手工配对，探针读取编辑器当前 chart revision。
- 在另一个窗口用 MCP 提议安全 Note 修改→批准→使用 `api.editor.commit` 后预览能变→撤销→重做→`await save`→导出 Next JSON/PEZ。
- 当编辑器有未保存改动、断线、联机锁、session 改变、错误 SHA/权限时拒绝写入。
- 原版 RPE 通过离线 JSON/PEZ 兼容路径验收，禁止冒充“原 RPE 客户端实时 MCP 已支持”。

## G3：模型/API/人工闭环
PAMOs 5060 逐模型生成→LLM 提议（离线 mock 先测试）→MCP 补丁验证与可视化 diff→**正式非 AI**审计→人工评分→导出→目标 Phira-Pro pinned 客户端试玩。原模型输出始终可回滚；可视 UI 列出两个谱面版本的事件变化和模型/提示词 hash。

## G4：GitHub
CI YAML 已纳入工程。交付需记录实际 feature 分支、commit SHA、PR 到 develop 的 URL、CI 检查结果及回滚方法；推送、PR、检查、审查和合并状态分别报告，未完成注明原因，不因源码存在而假定成功。不要上传音频、训练谱面、权重或个人数据；GitHub Actions 不运行 GPU 训练。稳定 tag/release 须另获用户明确授权并通过发布门禁，不是导入包 PR 的必需验收项。

## 明确不属于本版已实现的内容
当前分支包含用户原 V5.1 开发包的完整设计材料和离线 MCP 最小原型、合约及单元测试。离线原型只处理共同 RPE 结构并写独立候选 JSON，不能视为完整双方言转换与 PEZ 导出。Windows / Python 3.12 / mcp 2.3.0 的真实 stdio 子进程测试已验证 8 个工具及无审批提交拒绝，见 `tests/test_stdio_mcp.py`。Live Bridge、训练模型、正式 DSP/几何审计、人工审核 UI 及 Phira-Pro 试玩仍需分别提供证据；未执行写 `NOT RUN`。真实 GitHub push/PR/CI 状态只能由执行记录确认，不能从本文件推断。
