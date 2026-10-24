# Changelog

此文件记录 PAMOs 项目**可核实**的改动。使用 Conventional Commits 与 SemVer；未完成的功能不写成已发布能力。

## [Unreleased]

### Added
- Windows 本地开发终端、音频栈检查、独立 CUDA 依赖清单及部署文档；本机工具/缓存/参考源码排除 Git。
- 从原始 V5.1 ZIP 导入完整 Agent 技术规范、31 篇设计文档、训练配置、Schema、示例、两套 LLM 提示词及离线 RPE MCP 原型；保留现有 GitHub 版本控制规范与 GPL-3.0 许可证。
- 增加来源哈希/文件映射、合成夹具来源说明、真实 stdio 测试；CI 必须运行三代契约和全部测试。
- GitHub Agent 分支 / PR / 发布规范，模型与谱面修订溯源要求。
- GitHub PR 模板，明确低显存测试、双格式兼容及版权检查。

### Fixed
- 离线提交再次核对源/结果哈希与批准值；独占创建候选，避免覆盖。
- 固定 K 轨道拒绝跨事件跳变及与 K 不匹配的轨道映射；ZIP 路径拒绝 Windows 非法路径。
- 旧初始化/直推 main 指令改为从 develop 新建 feature 分支并提交 PR。

### Pending
- RPE Next 实时 MCP 编辑器桥接和 GitHub CI 端到端测试。
- RTX 5060 实机训练、Phira-Pro 实际游玩验收。

## [0.0.0-bootstrap] - 2026-10-24
- 建立基础仓库：README、AGENTS、Codex 引导、GPL-3.0、gitignore、CI 初始化检查及 develop 分支。
