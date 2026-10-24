# 28 — GitHub 代码版本控制、CI 和训练追溯

本文件保留 V5 的技术追溯设计；执行流程以根 [AGENTS.md](../AGENTS.md) 与 [32_VERSION_CONTROL_POLICY.md](32_VERSION_CONTROL_POLICY.md) 为准。

## 28.1 指定仓库与实际状态

用户指定仓库为 `vaseft/PhiAiMadeOs`，远端为 `https://github.com/vaseft/PhiAiMadeOs.git`。本分支已整合原 V5.1 开发包文档和离线原型；**文件存在不代表已经 push、创建 PR、CI 通过或合并**。这些状态需要通过 Git/GitHub 的真实结果逐项报告。旧包“没有发现专用远端”的描述已过时，不再作为执行指令。

## 28.2 分仓与目录

PAMOs 使用上述独立仓库。`Phira-Pro/Phira-Pro` 与 `kclg-YSJ/rpe-next` 是只读上游参考，记录固定 Git SHA，不向它们推送 PAMOs 代码，也不将 rpe-next 的受限源码复制或重新授权为 GPL。

目标产品目录：`src/phiaimadeos/`、`web/`、`mcp/`、`rpe-next-bridge/`、`prompts/`、`docs/`、`schemas/`、`scripts/`、`.github/workflows/`、`tests/`；这是架构规划，不能由目录清单推断均已实现。V5.1 实际离线原型位于 `pamos_mcp/`。

Git 只存：源代码、Agent 文档、Schema、合成或获授权的小型 fixture、CI 配置、精简匿名指标。**不存**：500 首音乐、原始训练谱面、歌曲原包、模型 checkpoint、含 API key 的配置、本地 IndexedDB 导出、个人评分数据库、敏感日志。大模型 API 日志只留匿名摘要和 patch hash。

## 28.3 在现有仓库开展工作

先核实工作区、未提交改动与 origin，再获取最新 develop；不得重新初始化、覆盖既有历史或为了导入开发包直接推送 main。

```bash
git remote -v
git status -sb
git branch -vv
git log -5 --oneline --decorate
git fetch origin
# 确认工作区已妥善保护，且 origin 指向用户指定仓库后：
git switch -c feature/rpe-mcp-bridge origin/develop
# 实施、测试、审查 diff，再按相关功能小步提交
git diff --check
# 仅推送已审查的功能分支，创建 PR 到 develop
git push -u origin feature/rpe-mcp-bridge
```

以上是后续功能分支的操作示例，不能作为已执行记录；已处于正确功能分支时不重复创建。认证或权限不足时保留本地成果并报告原因，不要求用户在聊天中发送 PAT，不谎称远程已同步。

## 28.4 分支与评审

- `main` 保存经确认的稳定里程碑；禁止普通开发直推。服务器端保护是否启用须单独查询，不能从文档约定推断。
- `develop` 是必需的集成基线；功能开发走 `feature/* → develop` PR，稳定里程碑另开 `develop → main` PR。
- 分支示例：`feature/rpe-mcp-bridge`、`feature/dual-rpe-adapters`、`feature/llm-refiner`、`feature/note-training`、`fix/rpen-roundtrip`；一事一支。
- Conventional Commits 示例：`feat(mcp): ...`、`fix(adapter): ...`、`test(audit): ...`、`docs(agent): ...`。
- 每次 PR 更新 CHANGELOG 的 Unreleased，并说明功能/文件变更、迁移和兼容风险、测试命令与真实结果、是否涉及许可或媒体、目标 runtime SHA、训练性能实测状态、回滚方法；不拿“代码写完”替代客户端实测。
- 合并前检查 CI、diff 与必要人工审查，不绕过规则。发布 tag/release 不是导入开发包的必需步骤；仅在用户明确授权且满足发布门禁后创建，说明模型/IR/MCP/格式 Schema 兼容性，重大格式变化提供迁移说明。

## 28.5 CI：无 GPU 环境也要能测

以 `.github/workflows/ci.yml` 的实际执行为准。仓库安全检查、V3/V4/V5 Schema 合约和离线单元测试应覆盖当前源码范围；新加入的 MCP 输入校验、非法噪域写入、版本冲突和路径负例需要真实测试记录。后续功能增加相应测试，不能用静态合同证明运行时功能完成。

CI 不下载未授权音频、不调用付费模型 API、不导出真实用户文件。GitHub CI 通过不代表 RTX 5060 训练、RPE Next 实时编辑或 Phira-Pro 游玩已通过；未执行项目写 `NOT RUN`，端到端客户端与目标硬件测试单独记录。

## 28.6 模型与谱面版本

训练 registry 每个 checkpoint 关联 `code_commit_sha`、`dataset_manifest_hash`、`split_hash`、`label_schema_version`、`feature_extractor_hash`、`random_seed`、CUDA/PyTorch 版本、训练配置、评估分数、文件 SHA-256。权重在本地或经授权的独立制品服务归档，不直接进入 Git。完整字段和状态晋升规则见 docs/32。

谱面候选 `ChartRevision` 独立于 Git commit。每次 PAMOs 模型输出、LLM 补丁、MCP 编辑器提交、人工修改均生成不可变谱面 revision 及 parent/reason/audit/report；修改前验证 expected hash/revision。RPE Next 内置“谱面工具 → 版本控制”是编辑器作品历史，不会自动将 PAMOs 源码或谱面推到 GitHub；通过 `pamos_revision_id`、哈希和兼容素材清单关联。

## 28.7 维护上游

参考版本统一记录于 `configs/upstreams.lock.json`，包括 repository、commit、license，以及适用的 observed_version 和核验依据。锁定 SHA 只是源码参考，不是实机兼容证明；原包曾列出的 `UNSET_VERIFY` 示例不能覆盖已存在的 lock 文件。

升级时独立提交兼容性 PR，不盲追 main；回归覆盖格式、模组接口、噪域只读、RPE 往返、提示词权限，并记录行为差异和回退 commit。
