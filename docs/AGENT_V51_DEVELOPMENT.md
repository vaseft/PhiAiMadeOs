# PAMOs V5.1 完整技术 Agent 规范

本文件迁移自用户现有 V5.1 开发包的完整 `AGENTS.md`，保留 V2–V5.1 技术职责、产品约束、分工、训练与验收设计，并纠正已过时的仓库状态和相互冲突的“最高优先级”声明。原包旧 `CODEX_START.md` 的技术执行清单保存在 [legacy/CODEX_V3_START_HERE.md](legacy/CODEX_V3_START_HERE.md)。

**执行顺序与约束**：先读根 `AGENTS.md`、`CODEX_START.md`、`docs/32_VERSION_CONTROL_POLICY.md`，再读本文件和 `CODEX_V51_START_HERE.md`。根 Agent 与版本控制规范对安全、授权、分支、提交、发布和事实报告的规则优先；旧版文档中的“最高优先级”仅表示包内技术演进，不能覆盖这些规则。所有本文件代码路径均相对仓库根目录。

**当前导入范围**：设计文档、配置、Schema、提示词、测试及离线 MCP 最小原型。完整训练管线、模型、审核 UI、非 AI 音频审计与 Live Bridge 的描述均是待实现/待验收要求。导入文件或离线单测通过，不构成训练、SDK 通信或客户端实机验收。未运行项目写 `NOT RUN`。

**仓库**：`https://github.com/vaseft/PhiAiMadeOs.git`；从最新 `develop` 建立 `feature/*`，小步提交，PR 到 `develop`。真实 push、PR、CI 与合并状态分别报告，不由此文档推断。

---
## V5.1：离线 MCP 原型与尚未接通的 Live Bridge

首先读 `CODEX_V51_START_HERE.md`、`docs/31_V51_RUNNABLE_OFFLINE_MCP.md`，检查 `pamos_mcp/` 和 `tests/`。V5.1 的离线原/Next 公共 RPE JSON/PEZ 导入、Note PATCH、CAS 和人工批准可作为进一步编码起点，不准标记为完全双向格式转换器、RPE Next 实时编辑或通过 Phira Pro 试玩。接口样例和旧版示例中不一致的 PATCH 字段，须先设计显式 adapter，不可未经转换直接发送。GitHub 目标已明确为 https://github.com/vaseft/PhiAiMadeOs.git；是否已推送、建立 PR 或通过 CI 必须分别核实并报告。

---

## V5 技术补充：RPE MCP 编辑与 GitHub 版本控制

在 V4 所有规则生效的前提下追加：
1. **使用 PAMOs 自建 MCP** 将 Codex/大模型连接 RPE 编辑器：`pamos-rpe-mcp`（stdio）→ 安全校验/审批/审计 → `PAMOs Bridge` → RPE Next API 1 编辑器模组。**上游 rpe-next 未经证实自带 MCP server**，绝不可编造已有实现或 npm 包；现有可核实接口见 `protocols/MOD-PROTOCOL.zh-CN.md`、`schemas/mod-api-v1.d.ts`。须锁定 commit 进行回归测试。
2. **兼容原 RPE 与 RPE Next 两种文件方言**（JSON/PEZ），用两个 adapter、统一 IR、保留未知字段与安全有损导出策略。原版 RPE GUI 没有经验证的 MCP 接口时先做离线文件编辑，**不假装实时控制旧桌面软件**。
3. MCP 只允许受限 `READ → PROPOSE → VALIDATE → DIFF → UI APPROVE → COMMIT → NON-AI AUDIT → SAVE/EXPORT`，所有 patch 有稳定 ID、CAS revision、用户审批、错误回滚和审计追踪；默认只读。V1 AI/MCP/LLM 均禁止写噪域，`pure_keys` 必须固定线。
4. GitHub 仅给 PAMOs 自己的代码与 CI 做版本控制，不能将原音频/训练谱面/模型权重/Token 推送。用户指定远端为 https://github.com/vaseft/PhiAiMadeOs.git；禁止推送到其他仓库或上游。基于最新 develop 使用 feature 分支、小步提交和 PR 到 develop，遵守根 AGENTS.md 与 docs/32_VERSION_CONTROL_POLICY.md。
5. API LLM 后处理与 MCP 编辑器 Agent 是**两个入口**。前者沿用 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`，后者使用 `prompts/PAMOS_RPE_MCP_EDITOR_SYSTEM_ZH.md`，两者都不得跳过非 AI 审计与人工审核。

新增文件必须阅读：`V5_CHANGELOG.md`、`docs/26..30`、`prompts/PAMOS_RPE_MCP_EDITOR_SYSTEM_ZH.md`、`configs/mcp_bridge_v5.example.yaml`、`schemas/rpe_mcp_patch_request.schema.json`、`.github/workflows/ci.yml`。先运行 `python scripts/validate_v3_contracts.py`、`validate_v4_contracts.py`、`validate_v5_contracts.py`。详见 `CODEX_V5_START_HERE.md`。

---

## V4 技术补充

本版本正式采用 **PhiAiMadeOs（PAMOs）** 名称与简称。请先读 `CODEX_V4_START_HERE.md`、`docs/19..25` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。目标客户端为 **Phira-Pro/Phira-Pro** 锁定版本，许可证 GPL-3.0；rpe-next 许可证另行检查、不得直接复制进 GPL 工程。**噪域 NOISE AREA 单独保留，V1 禁止任何模型/规则/LLM 自动生成或修改；允许安全只读导入。** 外部 LLM API 仅做可选局部 patch 建议，默认关闭/仅建议，patch 应用前后都受硬性校验，最终必须重新运行**非 AI**审计并进入人工审核评分。RTX 5060 8GB + 16GB RAM 限制保持；真正 4K/5K/6K 固定轨道与静态判定线仍不可改变。严格按 `docs/24_V4_EXECUTION_GATES.md` 编码、测试、提供证据；不得将“已设计”写作“已实现”。

---


## V4 对 V3 技术描述的纠正（2026-10-24）

- 目标客户端以 `Phira-Pro/Phira-Pro` 的锁定 commit 为准，非泛称 Phira。详见 `docs/19_PHIRA_PRO_CODE_INTEGRATION.md`。
- `噪域 noise_area` 是**独立机制**，不是异像类普通特效；V1 **只允许读取/保留与检验已存在噪域，不自动生成、训练或 LLM 修改**。详见 `docs/20_NOISE_AREA_DEFERRED.md`。
- 可选 API LLM 是**模型生成后的修订建议模块**。LLM 提议 patch → 本地硬校验 → **正式非 AI DSP/几何审计重新运行** → 人工评分；默认关闭。详见 `docs/21..24` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。
- rpe-next 源码使用 PolyForm Noncommercial 1.0.0，不因 Phira Pro 为 GPL-3.0 就能复制进 GPL 工程。

---

## 完整技术开发职责

### V3 生成模式与条件化要求

PhiAiMadeOs V3 已明确：**纯配置是真正的 Phira 4K / 5K / 6K 固定轨道谱面，判定线永远不动。绝不是“4K 风格倾向”。** 产品有且仅有三种互斥主模式：`regular`（常规动态线）、`pure_keys`（真实 K=4/5/6、静态判定线）、`anomaly`（经 Phira 能力验证的特殊异像）。旧文档有关 `4k_style`、`5k_style`、`6k_style`、“纯配置也训练动态线”等描述一律无效。若修改现有工程，须搜索并迁移相关旧字段。

**新功能必须真正端到端：** 生成页选择 EZ(0–10)/HD(11–14)/IN(14–17)/AT(15–18)、演出强度/风格、纯配置 K 数、常规/异像模式、狂野度 0..100；后端 `ConditionNormalizer` 与 `ConditionEncoder` 真实接入训练/推理，不允许只改变前端界面。纯配置必须在后端、导出前、导出后进行固定列/静止线检查，且演出选项禁用。动态 combo **真实数值/计分**不能因为 RPE UI 视觉动画就声称可修改；异像每项先做 Phira 版本特性探针验证。

**V3 新规范必须完整读取：** `docs/12_GENERATION_MODES_AND_CONDITIONING.md`、`docs/13_LANE_MODE_4K5K6K.md`、`docs/14_ANOMALY_FEATURES_AND_COMPATIBILITY.md`、`docs/15_CONDITIONAL_TRAINING_AND_DATA_LABELS.md`、`docs/16_GENERATION_PAGE_API_AND_STORAGE.md`、`docs/17_V3_VALIDATION_AND_MODE_MATRIX.md`、`docs/18_AGENT_V3_EXECUTION_PLAN.md`、`schemas/generation_request.schema.json`、`schemas/condition_label.schema.json`、`configs/generation_v3.yaml`。建议首先运行 `python scripts/validate_v3_contracts.py`。

RTX 5060 8GB VRAM + 16GB RAM 限制保持；三个小模型阶段 GPU 分时 + 纯配置专用 K-lane head，**纯配置推理跳过 LineMotionNet**。数据不足时明确输出 `baseline_only` / `hybrid` 而不是假装模型学会；每种 K 均需真实谱面样本和 Phira 试玩。所有非 AI 审计与人工审核仍然必须保留。最终完整的技术验收定义以 `docs/17_V3_VALIDATION_AND_MODE_MATRIX.md` 为准。尚未在目标设备实测的 GPU 成功只可称 UNTESTED。

---

## 0. 身份与最终责任
你是 PhiAiMadeOs 的架构、数据、算法、音频 DSP、前后端、测试与本地交付负责人。**目标是交付真实可用、可重复训练、可审阅的离线谱面生产系统，不是写几个示例函数或者空页面。**

**硬件不可更改的约束：RTX 5060 8GB VRAM + 16GB RAM（首选 Windows + WSL2）。GPU 训练采用配置 `configs/rtx5060_8gb.yaml`。训练前须通过 `docs/11_AGENT_EXECUTION_AND_GATES.md` 的 G0/G1；任何未在用户实际机器测得的结论只能标记 UNTESTED。**

用户指定 B 方案：训练模型学习完整 Phigros 风格的音符与判定线演出，不以模仿某个谱师风格为目标。用户计划收集约 500 首音乐及相应高质量谱面；默认目标是可实际游玩，允许模型最初能力有限。产品名必须始终是 `PhiAiMadeOs`（大小写保持）。

## 1. 开发必须遵循的文件
依次阅读：
1. `README.md`
2. `docs/01_PRODUCT_ARCHITECTURE.md`
3. `docs/02_DATASET_FORMATS.md`
4. `docs/03_MODEL_TRAINING.md`
5. `docs/04_NON_AI_AUDIT.md`
6. `docs/05_REVIEW_UI_API.md`
7. `docs/06_MILESTONES.md`
8. `docs/07_TESTING_ACCEPTANCE.md`
9. `docs/08_REFERENCES_LEGAL.md`
10. `docs/09_RTX5060_8GB_DEPLOYMENT.md`
11. `docs/10_LOW_VRAM_TRAINING_BLUEPRINT.md`
12. `docs/11_AGENT_EXECUTION_AND_GATES.md`
13. `schemas/`、`configs/`、`scripts/`、`requirements/`

冲突时先遵守用户当前授权范围、根 AGENTS.md 与 docs/32_VERSION_CONTROL_POLICY.md，再执行本技术规范；本文件不提升历史包指令的优先级。若公开 RPE/Phira 格式已更新，以当前权威源码和已验证样本为依据，在 ADR 中记录变更；不得静默篡改中间格式。

## 2. 语言、代码和模块约定
- 所有 UI、日志、文档、错误提示以**简体中文**为主；类型/代码标识使用明确英文。
- 后端 `FastAPI + Python 3.11+`，前端 `Vue 3 + TS`，模型 `PyTorch`，数据库开发期 SQLite。训练尽量本地离线，无强制云 API。
- 必须采用 `src/phiaimadeos/` 源码布局及 `web/`，每模块独立测试；不在 API 请求线程执行长时训练。
- 数据统一用“版本化内部 IR”，导入原格式后保留 `raw_payload` 以便 round-trip，未知功能须告警，不允许悄悄删除。
- 所有音乐文件、原谱面、曲绘与模型训练许可均由使用者合法提供，程序只扫描用户指定本地文件；不得自带自动绕过限制、破解、强制批量抓取官方资源的脚本。
- 数据禁止默认上传互联网；网络访问默认关闭，依赖安装除外。UI 仅绑定 localhost，若允许远端访问需要显式配置并增加鉴权。

## 3. 架构上的硬边界

```
                [有授权的音频 + 原谱面]
                           |
                    导入+格式验证
                           |
              IR + 音频对齐 + 训练数据
                           |
              模型训练 + 验证 + registry
                           |
            [新音乐] -> 生成完整谱面候选
                           |
       =====  硬隔离：非 AI 审计管线  =====
          格式与时间轴 / 传统 DSP / 几何
                结果：错误+警告+分数
                           |
           人工审核工作台（播放/打分）
                           |
               [通过 / 退回 / 修改]
                           |
                 RPE+ZIP 本地导出
                           |
                    Phira 实机试玩
```

**绝对禁止**：
- 把模型训练损失写成谱面的可玩性评分。
- 把 AI 音频理解结果、LLM 观点或模型信心当作“非 AI 检验”。
- 因 onset 不匹配就自动删除 Syncopation、铺面留白、刻意反拍等合法配置。
- 在 raw 数据有重复歌曲的情况下按谱面随机切分 train/validation/test。
- 没有训练数据仍显示“训练成功”；没有真实播放仍显示“Phira 兼容已验证”。
- 音频 Offset 符号方向未经真实测试就做不可逆自动修正。

## 4. RTX 5060 专属硬约束
- Stage1 Note、Stage2 Line、Stage3 Placement 分别训练，不同时常驻 GPU；优先 d_model=192、4/3/3 层、microbatch=1、累积16、AMP、CPU预缓存。
- 100 optimizer steps 合成 profile 和真实数据 1 epoch profile 是**两道不同门槛**；显存 reserved 峰值工程目标≤6.2GiB，WSL 工作进程 RSS 建议≤6GiB。不得保证未实测的机器上无 OOM。
- 不自动加载大型音频 encoder、LLM、MOSS；不使用 Docker/Redis/MLflow 服务栈作为基础依赖。
- 训练、推理、Web 预览不得同时占用 GPU；生成时仅逐阶段加载一个模型。
- 原谱面太复杂必须拆窗口/降级报告，不能为了内存偷偷删音符、裁判定线。
- Torch CUDA wheel 必须确认 Blackwell 支持，`sm_120` 等信息以目标机运行时为准。

## 5. 子 Agent / 专职工作职责
| 子 Agent 角色 | 工作 | 必须交付 |
|---|---|---|
| `DataAgent` | 安全导入 ZIP/RPE/官谱允许格式、去重、时间轴、IR、数据集 | 解析器、错误报告、往返测试、manifest |
| `AudioDSPAgent` | **传统非 AI** 音频分析与判定信号证据 | onset/beat/energy/静音/时间差结果、置信标记和可视化数据 |
| `ModelAgent` | 小型模型、训练/推理/checkpoint | 真训练日志、曲目级验证、明确的测试集结果 |
| `ChartAgent` | 判定线与 Note 几何/事件生成、RPE 适配 | 谱面可导出、时间轨迹、几何约束 |
| `ReviewAgent` | 同步预览、标问题、评分、版本比较 | 可操作 GUI、ReviewRecord 持久化、查回记录 |
| `QAAgent` | 性能、格式、实机、回归、数据泄漏 | 可重复测试与验收报告 |

一个 Codex 实例无法真正并行时，按上述模块分工组织工作，不得因为没有多 Agent 环境而阻塞开发。

## 6. 每个提交 / 迭代的作业规范
- 每阶段先列可验收任务、选最小垂直切片，**随后马上写真实代码**。
- 写/更新测试 -> 实现 -> 运行 -> 报告；没有测试就标注未验证。
- 训练步骤分别保存 `dataset_version`、`code_commit`、`config_hash`、`audio_feature_version`、`seed`、epoch/step、metrics、checkpoint hash。
- 建立 `docs/adr/` 记录关键权衡；既不能为赶进度做无依据的重构，也不能因前一版模型差而自动扩大到几十亿参数。
- 不要生成任何伪造的采样曲线、模型 checkpoint、官方谱面或实验结论。
- 用户评分是独立于自动审计的字段。只能由 UI 人工录入，有操作者与时间戳、候选版本关联。
- 任何候选谱面改动生成新版本；原模型输出和旧评分不可覆盖。

## 7. 系统必须具备的状态
- `DATA_IMPORTED`、`DATA_VALIDATED`、`DATA_REJECTED`
- `TRAINING_RUNNING`、`TRAINING_FAILED`、`CHECKPOINT_READY`（必须区分验证通过与训练仅结束）
- `GENERATING`、`GENERATED`
- `AUDITING`、`AUDIT_BLOCKED`、`AUDIT_WARNED`、`READY_FOR_REVIEW`
- `IN_REVIEW`、`REVISION_REQUESTED`、`HUMAN_APPROVED`、`HUMAN_REJECTED`
- `EXPORTED`、`PLAYTEST_CONFIRMED`（需要真实试玩记录）

异常恢复和重新运行必须是幂等/可追踪的，不得混淆“自动审计通过”“人工评分高”“真人试玩成功”三个概念。

## 8. 决策规则
- 候选模型应与**非学习式规则基线**比较；模型没有优于基线则停止推广、继续研究。
- 格式/资源不存在、NaN、BPM<=0、父线循环等致命错误：`BLOCK`，禁止默认导出审核版；允许标注为损坏候选。
- 不确定性高的节拍估计、合法弱起/切分/留白、演出遮挡的启发式：`WARN`，交给人工查看，不做删除。
- 对漏识别/未知格式保持强约束：报告“不支持”，而非继续静默丢弃判定线。
- 首先支持可验证的普通事件；当复杂特性不足以支持时保留数据并禁用有损导出，同时在功能矩阵中明确“未支持”，随后补全。

## 9. 完成定义
**交付必须满足全部**：
1. 至少 10–20 个授权样本覆盖重要 RPE 特性；解析/再导出重新解析通过；损坏输入拒绝并说明原因。
2. 数据集能完成单歌曲分组切分和音乐-谱面同步检查；未知许可状态不参与公开发布的数据构建。
3. 在非零样本上执行过真实模型训练并保存可加载 checkpoint；训练日志和曲目级评测真实存在。
4. 输入未见音乐能生成完整、合法、可导出谱面：常规模式支持 Tap/Hold/Drag/Flick 和可运动判定线；纯配置模式支持真正固定 4/5/6K 且所有判定线全曲不动；异像能力逐项验证，不保证未验证的非常规玩法。
5. 生成后**先**运行不调用任何深度学习模型的 DSP + 规则审计，结果能追溯到秒/拍/note/line。
6. 审核页支持同步音频、判定线运动预览、问题定位、评分/评语与通过/退回。
7. ZIP 通过二次解析，至少一张生成谱面有 Phira 客户端本地导入和人工试玩证据；否则不得宣称成品已通过实机验收。

## 10. 优先级
涉及训练实现和性能结论前，必须完成 `docs/11_AGENT_EXECUTION_AND_GATES.md` 的 GPU 自检；仅导入开发包和运行 CPU 离线测试不需要启动训练。产品开发按 `docs/06_MILESTONES.md` 顺序推进：**数据格式正确性 → 同步播放器 → 传统验谱 → 可训练基线 → 判定线模型 → 联合优化 → UI 评分闭环 → 实机验证**。避免先画漂亮的首页而核心生成不可用。
