# PhiAiMadeOs V5.1 增量

- 在 V5 **Agent 文档包**基础上，新增 `pamos_mcp/core.py`、`server.py`、`approve.py`，实现离线 JSON/PEZ 解析、7 个 MCP 工具包装函数、CAS patch 提议/验证、独立终端人工批准、只写新候选 JSON。
- 6 项真实执行的核心单元测试（原创 JSON/PEZ、固定 K、噪域禁写、过期修订、路径遍历、人工批准、未知字段保留）。
- GitHub Actions 追加无 GPU 单元测试；本地 Git 初始化脚本，不伪造 GitHub 远端连接。已连接的 GitHub 登录 `vaseft` 未找到 PhiAiMadeOs 专用仓库。
- MCP SDK v2 与配置示例，**当前环境未安装 SDK，stdio/tools-list 仍为 UNTESTED**。
- **未实现** RPE Next 实时桥接插件，也未执行音频 DSP/真实 Phira Pro 验收；别把文件级候选修改当作在 RPE Next 编辑器里修改成功。
# 原包历史记录说明

下文保留 V5.1 Kit 生成时的状态。现有专用仓库为 `vaseft/PhiAiMadeOs`；当前分支流程以根 `AGENTS.md` 和 `docs/32_VERSION_CONTROL_POLICY.md` 为准，本次导入及测试见 `CHANGELOG.md` 与 `docs/33_V51_IMPORT_RECORD.md`。
