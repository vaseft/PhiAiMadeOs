# PhiAiMadeOs (PAMOs) — Codex 启动与 GitHub 交付指令

**目标仓库**：`https://github.com/vaseft/PhiAiMadeOs.git`（`vaseft/PhiAiMadeOs`）。`main` 为稳定分支，`develop` 为集成分支。

> 仓库目前是**初始化骨架**。完整 V5.1 Agent Kit 尚未全部导入；不能假设后端、训练模型、实时 RPE MCP、前端页面已经存在。

## 每次会话固定操作流程（必须执行）
1. 读取仓库 `AGENTS.md`、`docs/32_VERSION_CONTROL_POLICY.md`、`CHANGELOG.md`、本文件。若 V5.1 Kit 已导入，继续读取 `CODEX_V51_START_HERE.md` 和与当前任务相关的设计与 Schema。
2. 检查 Git：`git remote -v`、`git status -sb`、`git branch -vv`、`git log -5 --oneline --decorate`。**不得在不知工作区是否有用户改动的情况下 reset/clean**。
3. `git fetch origin` 后以最新 `origin/develop` 创建合适的 `feature/`、`fix/` 或 `docs/` 分支。若工作区有未提交修改，先保护或说明，不要覆盖。
4. 实施小步功能，按功能单元添加测试和文档，每个可验证阶段一次 Conventional Commit。修改代码之前先检查依赖许可证、数据来源与 8GB 显存/16GB 内存限制。
5. 每次提交前至少检查 `git diff --check`、`git status`，以及 `git diff --cached --stat`；防止训练音乐、原始谱面、模型权重、密钥、缓存误入 Git。
6. 运行当前仓库适用的测试；缺失或未运行的测试明确写 `NOT RUN`，绝不虚构“全部通过”。
7. 推送功能分支并发起 **PR → develop**，填写 `.github/pull_request_template.md` 的测试、授权和回滚信息。待 CI 绿灯及必要审查完成才合并；不得绕过保护直接推送 `main`。
8. `develop → main` 必须另开里程碑 PR，用户明确授权且完成发布门禁后才创建稳定 tag/release。
9. 每次交付输出分支、commit SHA、PR 链接、测试日志摘要、风险、回滚方法、实机训练/试玩的 `PASS / FAIL / NOT RUN`。

## PAMOs 技术不可变要求
- 游戏端目标：`Phira-Pro/Phira-Pro`，GPL-3.0；编辑器协议参考：`kclg-YSJ/rpe-next`，PolyForm Noncommercial（不能当 GPL 随意复制）。
- 首代不生成、训练或自动修改噪域；已有噪域数据只读保留。常规/异像、多判定线；纯配置是**真正静止的 4K/5K/6K 固定轨道**。
- 训练模型是小型可复现序列模型，特征缓存与顺序训练适应 RTX 5060 8GB、16GB RAM；必须运行实机峰值显存测试，不能只靠估算。
- 生成 → 独立非 AI 音频/几何审计 → 可选 LLM API 后处理（结构化 patch）→ 再审计 → 人工播放、打分 → Phira-Pro 导入试玩。
- LLM/MCP 每次修改谱面之前必须 snapshot + expected hash + diff + 审批；不得直接覆盖原始谱面；写入操作可回滚。
- 追踪 **代码 Git SHA / 谱面 revision / 模型 run_id+权重 hash / 提示词版本 / 上游依赖 SHA**，不能互相混同。

## 首个待办
将用户的 `PhiAiMadeOs V5.1 Agent Kit` 的完整文件导入开发分支（排除内部 `.git`、`__pycache__` 和临时数据），审核同名文件与许可证，确保测试可复现，再分 PR 建立离线 RPE MCP、RPE Next 实时桥接、训练服务、非 AI 审计与人工审核 UI。

**禁止**在只有仓库骨架时宣称“模型已训练好”“RPE MCP 已实时连接”“谱面已在 Phira-Pro 中试玩成功”。
