# PhiAiMadeOs（PAMOs）— Codex 总工程 Agent

> **当前分支已导入用户现有 V5.1 Agent Kit 的开发规范、配置、Schema、提示词、测试及离线 MCP 最小原型。** 导入不表示完整产品、训练模型、审核 UI 或实时编辑器桥接已经实现，也不表示已经推送或合并。每次启动必须先核对仓库树、分支、远端与测试结果；不得凭文档虚构代码或模型。

> 功能分支 `feature/local-workbench` 追加了 `src/phiaimadeos/`、`web/` 与 `extensions/rpe-next-bridge/` alpha 实现。以 [交付记录](docs/36_WORKBENCH_DELIVERY.md) 和真实 Git/PR 状态为准；本轮用户明确要求完成测试以外的工作，因此没有新增或主动运行测试，保留既有 CI，新功能仍需后续专门验收，不能自动合并或宣称已验证。下一轮若未继续豁免，应补本文件要求的自动测试与客户端验收。

## 0. 项目与仓库标识
- 产品名：PhiAiMadeOs，简称 PAMOs；GitHub：`vaseft/PhiAiMadeOs`。
- 远端：`https://github.com/vaseft/PhiAiMadeOs.git`；默认稳定分支：`main`。
- 目标客户端：[Phira-Pro](https://github.com/Phira-Pro/Phira-Pro)，GPL-3.0。
- 编辑器与格式协议参考：[rpe-next](https://github.com/kclg-YSJ/rpe-next)，**PolyForm-Noncommercial-1.0.0**。仅对公开协议做独立兼容实现，不擅自复制其受限代码或重新授权；记录上游 commit SHA，升级前运行契约测试。
- 用户硬件基线：**RTX 5060 8GB VRAM / 16GB RAM**。所有训练设计应支持冻结音频编码器、磁盘特征缓存、短窗口、micro-batch 1、梯度累积、单模型顺序训练和实测资源上限。不得保证未经实机验证的显存数字。

## 1. 不可破坏的产品约束
1. 谱面生成模式：常规 Phigros、多判定线演出；真正的**静态 4K/5K/6K** 纯配置（判定线不动）；特殊异像模式。
2. 难度可条件控制：EZ 0–10 / HD 11–14 / IN 14–17 / AT 15–18，另有演出强度、狂野度、可玩性优先级。
3. **噪域独立延期**：V1 只读保存、不训练、不自动生成、不允许 LLM/MCP 修改；即使原始格式含噪域也不得静默丢弃。
4. AI 生成结果必须经过**与生成模型独立的非 AI 音频、数学与几何检验**，人工预览和评分，再作为可发布候选；不能以“格式通过”冒充“真人可玩”。
5. 外部大模型 API 仅能提交**局部、可审计、带版本哈希的结构化 patch 建议**。应用前检查权限、Schema、范围、版号、diff、无噪域改动、可玩性与兼容性；默认需人工批准，可回滚。
6. RPE/RPE Next 格式转换要保留未识别字段并列出不兼容项；RPE Next 编辑器使用正式模组 API 的 `commit()`、`save()`、撤销机制。严禁把未经证实的编辑器联通称为“已实现”。
7. 训练数据需有使用授权；音乐、谱面源文件和任何凭证**不得随源代码公开上传**。GPL-3.0 的代码授权与训练集、音乐及模型权重的授权分别核实。

## 2. GitHub 版本控制：必须执行（不是建议）

详细见 [docs/32_VERSION_CONTROL_POLICY.md](docs/32_VERSION_CONTROL_POLICY.md)，与本文件同等约束力。

### 2.1 分支与工作树
- `main`：经确认的稳定里程碑；禁止普通开发直推。
- `develop`：已通过检查的集成基线。
- `feature/<domain>-<short-name>`：功能开发；`fix/<short-name>`：普通修复；`docs/<short-name>`：文档；`hotfix/<short-name>`：经批准的紧急修复。
- 正常流程：从最新 `develop` 新建短命分支 → 小步提交 → 推送 → PR 指向 `develop` → CI + 人工检查 → 合并；里程碑 `develop -> main` 单独 PR。
- **禁止自动推送 main、force push、覆盖他人提交、删除他人分支或跳过 CI**。PR 合并前先查看 diff 和检查状态；信息不全则保留 PR 待审。
- GitHub connector 权限不足或认证失效时，仅保存本地 commit，报告原因；不得谎称远程已同步。
- 若用户明确让 Agent 持续开发：可自主管理功能分支与 PR，但**发布 main、远端 release、公开训练资产**须遵守用户明确授权及仓库保护规则。

### 2.2 提交规范与版本号
- 使用 Conventional Commits：`feat(model): ...`、`fix(rpe): ...`、`docs(agent): ...`、`test(audit): ...`、`chore(ci): ...`。
- 一次提交只包含可解释的相关修改；不可将“新增接口”“修改训练策略”“重写格式转换”混成无法回滚的巨大提交。
- 首次可运行 alpha 使用 `v0.x.y`；稳定可兼容 API 发布后使用 SemVer。破坏性格式/API 变更应提高相应版本并提供迁移说明。
- 每次 PR 更新 `CHANGELOG.md` 的 **Unreleased** 区段；正式发布时将已验证项目移动到版本标题，创建 annotated tag，关联 commit、验收记录。
- 代码版本和模型版本分离：模型权重可采用 `model-note-v0.1.0` 之类命名，不得只靠文件名当作训练来源证明。

### 2.3 合并门禁
- 检查 `git status`、`git diff --check`、`git diff --stat`；确定未误入数据、权重、token。
- PR 必须写清：目的、修改文件、风险、测试命令与**真实输出**、GPU 实测状态、兼容矩阵、回退方法、是否触及版权/许可证。
- 本仓库现有 CI 可能仅为**初始化检查**；“绿色”不代表已测试 GPU 训练或 Phira-Pro 实机可玩。所有未运行测试必须标为 **NOT RUN**，不能标成 PASS。
- 增加模型、格式或 MCP 功能时，必须补充自动测试：格式往返/字段保留、4K/5K/6K 静止约束、patch 版本冲突、权限与不安全路径、噪域只读、导出再导入。
- 发现断言失败时保持该分支未合并，优先修复测试；禁止删测试、篡改阈值来凑绿灯。

### 2.4 防数据污染与秘密泄露
- 不提交 `datasets/`、音乐、原始谱面、`*.pez`、授权不明素材、`.env`、Key、`*.safetensors`、`*.pt`、cache、数据库和日志。
- 用仓库 `.gitignore` 加**提交前扫描**双重防线；不允许使用 `git add -f` 绕过忽略。
- 训练元数据可提交**去标识化汇总与哈希**，不能提交训练音乐本体或受限制的文件名/路径/个人数据。
- 如密钥误提交，应视为已泄露：暂停合并、撤销/轮换密钥，按团队流程清理历史；不要仅删除当前文件就宣称安全。

## 3. 多层版本追踪与可回滚规则

### 3.1 谱面版本（和 Git 代码版本区分）
- 原始导入谱面只读；每一次 PAMOs 生成和 LLM/MCP 修改均建立不可变 `chart_revision`，记 `parent_revision`、输入 SHA-256、输出 SHA-256、生成条件、模型版本、变更操作、审计报告 ID、人工评分。
- 每次 patch 应基于调用前的 `expected_chart_sha256` / `base_revision`；不匹配一律拒绝，不得静默覆盖。
- 更新流程：snapshot → propose → validate → diff → human approve → commit → audit → review → export；失败回到上一版本，不更改原始文件。
- RPE Next 内置版本控制（本地谱面快照、分支、合并、撤销）与 GitHub 代码历史是不同系统；通过明确导出归档和哈希关联，不应视为自动同步到 GitHub。

### 3.2 模型与训练版本
- 每次训练保存 `run_id`、Git commit SHA / dirty 状态、训练配置哈希、数据 manifest 哈希、去重/分组拆分版本、随机种子、特征抽取版本、音频编码器名称/哈希、RPE 解析器版本、torch/CUDA/驱动信息、显卡/显存、checkpoint SHA-256、指标与人工评测引用。
- 最优权重仅在验证指标 + 真实谱面回放 + 人工可玩性验收后才能提升为 `candidate` / `stable`；默认训练结果是 `experimental`。
- 权重和个人训练集存本地或有授权的私有工件库；GitHub 只保存小型元数据、Schema、代码、匿名指标。回滚要能加载上一 stable 权重。
- 禁止训练/测试泄漏：同一歌曲的多个难度与重剪辑/高度相似版本必须在同一数据拆分组。

### 3.3 上游依赖与接口版本
- `Phira-Pro`、`rpe-next` 的 commit SHA、许可证、接口契约、兼容结果固定在 `configs/upstreams.lock.json` 或相应 manifest；不能盲追 `main`。
- 升级第三方版本走独立 PR：更新 lock → 运行兼容回归 → 记录行为差异与回退 commit。
- 外部 API 调用保存 `provider/model/prompt_template_version/schema_version`（不保存 API token）；后处理提示词更改需同步修改测试与版本记录。

## 4. 本轮执行原则与质量门槛
1. 开工先读：`AGENTS.md`、`CODEX_START.md`、`docs/32_VERSION_CONTROL_POLICY.md`；再读 `docs/AGENT_V51_DEVELOPMENT.md`、`CODEX_V51_START_HERE.md` 和与任务相关的 MCP/训练/审计文档。
2. 建立 feature 分支前确保基于正确的 `develop`，不得覆盖本地未提交变更；先查看 status/log/remote。
3. 当前阶段优先：核对 V5.1 导入、依赖/许可证和离线测试 → 按独立功能 PR 推进 live editor bridge、训练与审核 UI。功能实现与文档“计划”严格区分；后续实现不能由一次包导入或静态检查宣称完成。
4. 最后汇报必须包含：分支、提交 SHA、PR 地址、被修改文件、已运行的具体测试及其结果、未完成部分、与目标硬件的实测情况。
5. 一切写操作要求可撤销、可审计、可追踪；不要让 AI 在未审阅的情况下批量覆盖谱面、改写训练标签或推送生产主分支。

## 5. V5.1 技术规范入口与优先级

完整技术 Agent 已整合至 [docs/AGENT_V51_DEVELOPMENT.md](docs/AGENT_V51_DEVELOPMENT.md)，原包启动技术清单保存在 [docs/legacy/CODEX_V3_START_HERE.md](docs/legacy/CODEX_V3_START_HERE.md)。当前执行入口为 [CODEX_START.md](CODEX_START.md) 与 [CODEX_V51_START_HERE.md](CODEX_V51_START_HERE.md)。

本文件全部产品、安全、版本控制及回滚规则继续生效；[docs/32_VERSION_CONTROL_POLICY.md](docs/32_VERSION_CONTROL_POLICY.md) 保持同等约束力。历史 V3/V4/V5 文档中的“最高优先级”、初始化仓库、远端缺失或可选 develop 描述均不得覆盖本文件和版本控制规范；技术冲突按 V5.1 → V5 → V4 → V3 的演进解释，无法兼容时报告并通过测试/ADR 处理。

**离线候选编辑原型、MCP SDK 通信、实时编辑器桥接、模型训练、非 AI 音频审计、人工审核 UI 和 Phira-Pro 试玩是不同验收项，必须分别给出真实结果。**
