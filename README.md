# PhiAiMadeOs (PAMOs)

**用于 Phira-Pro 的 AI 音游谱面生成、校验、编辑与人工审核系统。**

> **V5.1 开发包与 Windows 环境已整合到 develop；本功能分支增加本地工作台 alpha 源码。** 包含数据、DSP、规则生成、小模型训练/推理、独立审计、人工审核、版本修订、导出与编辑器模组。按用户本轮要求没有新增或主动运行测试；代码实现、生产打包、真实训练与客户端验收分别记录，尚不构成稳定产品或已训练模型。

Windows 已部署目录可双击 `Start-PAMOs.cmd`，在 `http://127.0.0.1:8765` 使用本机工作台。恢复依赖与界面构建使用 `Install-PAMOs.cmd`。参见 [本地工作台使用与边界](docs/35_LOCAL_WORKBENCH.md)、[本轮交付记录](docs/36_WORKBENCH_DELIVERY.md) 和 [Windows 环境](docs/34_WINDOWS_ENVIRONMENT.md)。

用户明确提供的本机谱面库可通过 [批量导入入口](docs/37_LOCAL_LIBRARY_IMPORT.md) 登记：支持原生 Phigros v1/v3 向工作台结构转换，音乐精确哈希去重，原始 JSON/媒体与小数/特殊难度保留。超出转换能力的项目单独标记仅存档；导入不自动授权训练、不开始训练或认证客户端兼容。

用户另行确认当前批次训练授权和游戏导出来源后，可执行 [本地训练数据准备](docs/LOCAL_TRAINING_PREPARATION.md)：保留人工听音状态、检查来源哈希和时钟、歌曲簇拆分并登记实验初训队列。实际训练结果与尚未完成的验收分别记录。

## 产品目标

选择本地授权音乐 → 提取音频特征 → 加载本地训练模型并按条件生成谱面 → 传统信号处理与几何规则检查 → （可选）通过大模型 API 进行受控局部修订 → 人工试听、预览和评分 → 导出可在 Phira-Pro 中测试的谱面。

设计目标（实现状态见下方）：

- **条件生成**：EZ 0–10、HD 11–14、IN 14–17、AT 15–18，演出强度、狂野度和常规／异像模式。
- **纯配置模式**：真正固定判定线的 4K、5K、6K 轨道谱面，不是“4K 风格”多判定线谱。
- **训练部署**：面向 RTX 5060 8GB 显存 + 16GB RAM 的小模型、顺序训练、特征缓存和显存自测；具体可运行性以实机测试为准。
- **RPE 双格式编辑**：原 RPE 和 RPE Next 的文件适配；通过独立 MCP 服务及编辑器模组实现受控谱面修改。
- **大模型后处理**：仅生成结构化修改建议，版本校验与确定性复查后方可应用，不允许直接覆盖原谱面。
- **非 AI 审计 + 人工审核**：音频起音、节拍、事件冲突、轨迹几何、可读性风险、人工评分和修改版本记录。
- **噪域**：独立预留功能。首代生成模型不训练、不生成、不修改噪域；已有内容只读保留。

## 上游与许可

- 目标游戏：[Phira-Pro](https://github.com/Phira-Pro/Phira-Pro)，GPL-3.0。
- 编辑器参考：[rpe-next](https://github.com/kclg-YSJ/rpe-next)，**PolyForm Noncommercial 1.0.0**；仅依据公开协议开发独立适配器，不将其源码重新标注为 GPL。
- PAMOs 自有源码采用 **GPL-3.0**；训练数据、音频、素材及模型权重的授权需独立确认。

## 开发与版本控制

`main` 保存经过验证的稳定基线，`develop` 用于日常集成，功能开发使用 `feature/*` 分支并通过 Pull Request 合入。

不要向仓库提交训练歌曲、未授权谱面、API 密钥、`.env`、检查点、GPU 缓存等私人或大体积数据。

## 当前实现与验收边界

- **已导入源码**：`pamos_mcp/` 离线原型，支持共同 RPE JSON 结构及 PEZ 中的谱面 JSON 读取、受限 Note patch、哈希版本校验、差异预览、独立人工批准与新候选 JSON 写入。源文件不直接覆盖。
- **本次 SDK 实测**：Windows / Python 3.12 / `mcp==2.3.0` 下，`tests/test_stdio_mcp.py` 通过真实 stdio 子进程列出 8 个工具，读取合成谱面、提议/校验/预览 patch，并确认未经批准的提交被拒绝、源文件未变。
- **新增代码**：`src/phiaimadeos/` 为本地 API/任务进程、共同 RPE IR/DSP/规则/审计、训练/推理/检查点、人工评分和修订服务；`web/` 为 Vue 3 工作台；`extensions/rpe-next-bridge/` 为独立编写的 API-1 模组。规则基线明确显示 `baseline_only`，训练结果默认 `experimental`。
- **新增边界**：本轮未运行上述新代码的功能、回归、安全、模型训练或客户端测试（`NOT RUN`），既有 CI 保留。纯 K 以代码实现静线和列约束，仍待实机验收；复杂扩展/父子线仅保留并报告不确定项。异像特性尚无实机能力证据，生成入口关闭；噪域只读。桥接代码只有收到真实保存 ACK 才登记保存，但本轮未实际配对编辑器。原/Next 完整无损转换未认证。
- **测试证据**：以本次分支/PR 的运行日志和 CI 结果为准。原包历史测试记录不是本次运行结果；未执行测试标 `NOT RUN`。硬件门禁脚本存在不表示已在 RTX 5060 上运行。
- **来源与版本**：`configs/upstreams.lock.json` 记录上游源码参考版本，不能替代运行兼容证明。V3/V4/V5/V5.1 变更记录描述设计演进。

## 从哪里开始

1. 先读 [AGENTS.md](AGENTS.md)、[CODEX_START.md](CODEX_START.md)、[版本控制规范](docs/32_VERSION_CONTROL_POLICY.md)。
2. 读取 [完整 V5.1 技术 Agent](docs/AGENT_V51_DEVELOPMENT.md)、[V5.1 执行入口](CODEX_V51_START_HERE.md) 和 [离线原型范围](docs/31_V51_RUNNABLE_OFFLINE_MCP.md)。原包 CODEX_START 技术清单保存在 [历史启动文档](docs/legacy/CODEX_V3_START_HERE.md)，不覆盖当前入口。
3. 用现有仓库从最新 `develop` 建立 `feature/*`，按功能小步提交，PR 到 `develop`。先做离线格式与安全测试，再按独立任务推进 Live Bridge、训练和审核闭环。

可先运行 CPU 合约与单元测试。Schema 合约需要 `jsonschema`、`PyYAML`；包含真实 SDK stdio 测试时还需先安装 `requirements/mcp_v51.txt`：

```bash
python scripts/validate_v3_contracts.py
python scripts/validate_v4_contracts.py
python scripts/validate_v5_contracts.py
python -m unittest discover -s tests -v
```

V5 新增 MCP 设计在 `docs/26_RPE_NEXT_MCP_ARCHITECTURE.md`、`docs/27_RPE_MCP_TOOL_CONTRACTS.md`、`docs/28_GITHUB_VERSION_CONTROL.md`、`docs/29_LLM_MCP_INTERACTION_GUIDE.md`、`docs/30_V5_ACCEPTANCE_AND_GITHUB_LINK.md`。MCP 编辑器使用 `prompts/PAMOS_RPE_MCP_EDITOR_SYSTEM_ZH.md`；可选外部 API 后处理沿用 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`，默认关闭、仅提议局部 patch，应用后必须重新非 AI 审计并人工审核。

V4 将目标客户端明确为锁定版本的 Phira-Pro，独立噪域只读保留，禁止首代模型、LLM 和 MCP 自动生成或修改噪域；完整说明见 `CODEX_V4_START_HERE.md`、`docs/19..25`。这些技术设计均受根 Agent 与版本控制规范约束。
## V3 更新（2026-10-24）
**重要纠正**：“纯配置”是可在 Phira 中玩的**真正固定 4K/5K/6K**，判定线不运动，不是 4K/5K/6K 的“风格倾向”。新 Agent 增加 `regular/pure_keys/anomaly` 模式路由、EZ/HD/IN/AT 难度范围、演出开关、狂野度控制、条件化训练、K 轨道专用布局模型、特殊机制引擎能力验证、完整生成页 API、按模式审核与测试。

**V3 技术背景**：当前 Codex 起点见上方统一入口，模式和条件规范位于 `docs/12..18`。 `scripts/validate_v3_contracts.py` 用于检验 V3 示例及 JSON Schema；它并不代表模型已实现。V3 设计保留 v2 的 5060 低显存训练和非 AI 审计要求。版本的正式训练与 Phira 真机兼容性尚未得到验证。

### V3 新增的关键文件
- `docs/12_GENERATION_MODES_AND_CONDITIONING.md` 三模式与条件契约
- `docs/13_LANE_MODE_4K5K6K.md` 静线固定 K 轨道设计与强制不变式
- `docs/14_ANOMALY_FEATURES_AND_COMPATIBILITY.md` 异像效果/动态 combo 视觉与真实逻辑区别
- `docs/15_CONDITIONAL_TRAINING_AND_DATA_LABELS.md` 条件训练、500 曲分层标注、低显存 K-head
- `docs/16_GENERATION_PAGE_API_AND_STORAGE.md` 页面、API、SQLite、状态机
- `docs/17_V3_VALIDATION_AND_MODE_MATRIX.md` 4/5/6K、regular、anomaly 验收用例
- `docs/18_AGENT_V3_EXECUTION_PLAN.md` Codex 分阶段真实编码与测试执行单
- `schemas/generation_request.schema.json`、`schemas/condition_label.schema.json`、`schemas/capability_matrix.schema.json`
- `configs/generation_v3.yaml`、`examples/generation_*.json`、`scripts/validate_v3_contracts.py`

## V2 基础：5060 8GB 显存 / 16GB 内存适配
加入可操作的 WSL2 + PyTorch CUDA wheel 安装、GPU/CPU 内存预算、三段小模型顺序训练的详细规格，以及真实 CUDA 反向传播和 100-step 显存压力测试脚本。**当前没有在用户 RTX 5060 上执行测试，因此绝不保证一定不会 OOM**；模型品质也依赖数据质量和实测验证。首选使用 `configs/rtx5060_8gb.yaml`，不再默认使用通用配置。

## 产品目标
输入授权的音乐 → 使用训练好的本地模型生成 Phigros 风格完整谱面 → **先用传统数字信号处理 + 几何/格式算法进行非 AI 审核** → 在本地页面按音乐同步预览、打分、标注问题、选择通过/退回 → 导出可以本地导入 Phira 的 ZIP 谱面包。

项目名称固定为 **PhiAiMadeOs**，不随意修改拼写。使用大约 500 首不同歌曲、每首一至多张授权谱面作为首期研究数据，**不承诺 500 首即可达到人工优秀谱师水平**。

## 文件说明

| 文件 | 给谁看 | 功能 |
|---|---|---|
| `AGENTS.md` / `docs/AGENT_V51_DEVELOPMENT.md` | **Codex 首先读取** | 根规则与完整技术 Agent：职责、约束、逐步实现规则、完成定义 |
| `CODEX_START.md` | 使用者 | 开始执行的提示词，可直接发送给 Codex |
| `docs/01_PRODUCT_ARCHITECTURE.md` | 前后端与架构 Agent | 全系统流程、服务边界、状态机 |
| `docs/02_DATASET_FORMATS.md` | 数据工程 Agent | 500 首素材导入、格式兼容、时间同步、划分及版权 |
| `docs/03_MODEL_TRAINING.md` | 算法 Agent | 模型结构、训练流程、实验与模型注册 |
| `docs/04_NON_AI_AUDIT.md` | 数字信号处理/验谱 Agent | **模型生成后、人工审核前**的非 AI 审核规则 |
| `docs/05_REVIEW_UI_API.md` | 界面/API Agent | 可同步播放的谱面预览、人工评分与问题回填 |
| `docs/06_MILESTONES.md` | 项目管理 Agent | 开发顺序与每阶段验收 |
| `docs/07_TESTING_ACCEPTANCE.md` | 测试 Agent | 数据、格式、DSP、几何、端到端测试 |
| `docs/08_REFERENCES_LEGAL.md` | 全部 Agent | 规范链接、许可证与数据来源约束 |
| `docs/09_RTX5060_8GB_DEPLOYMENT.md` | 用户/部署 Agent | **逐条部署 Windows/WSL、CUDA、PyTorch、音频、API/前端** |
| `docs/10_LOW_VRAM_TRAINING_BLUEPRINT.md` | 模型 Agent | **三阶段网络、张量尺寸、loss、缓存、优化、OOM 降级** |
| `docs/11_AGENT_EXECUTION_AND_GATES.md` | Codex/QA | **G0-G9 每一步可执行验收门禁** |
| `configs/example.yaml` | 全部 Agent | 通用示例；**本机使用 `configs/rtx5060_8gb.yaml`** |
| `requirements/base.txt` | 开发/部署 Agent | 只含 CPU/DSP/API 依赖；PyTorch CUDA 单独安装 |
| `scripts/diagnose_hardware.py` | 部署 Agent | GPU 驱动和 CUDA forward/backward 检查 |
| `scripts/benchmark_tiny_train.py` | 模型 Agent | 真梯度、AMP、AdamW、累积的**合成负载**峰值 profile |
| `schemas/*.json` | 数据/API Agent | 标准化谱面、审计报告、人工评分的基础 JSON Schema |
| `examples/review_example.json` | 前端/测试 Agent | 审核记录示例 |

## 推荐技术栈
- 后端：Python 3.11+、FastAPI、Pydantic、SQLAlchemy + SQLite（单机）
- 训练：PyTorch、音频特征离线缓存，优先适配 **RTX 5060 8GB** 的量化/混合精度、梯度累积、短窗口训练。
- 非 AI 审核：NumPy、SciPy、librosa、SoundFile、ffmpeg/ffprobe；**不得调用神经网络模型判断节奏是否合格**。
- 前端：Vue 3 + Vite + TypeScript，Canvas 2D / WebGL 渲染，WebAudio 作为时钟。
- 谱面：内部版本化 IR → 目标 RPE JSON + Phira 本地导入 ZIP。
- 后台任务：先用进程/SQLite 作业队列，后期按需换 Redis/RQ；模型训练单独进程，不能堵塞 API。

## 建议操作
1. 使用本仓库已有克隆及 develop/feature 流程，不重新初始化仓库。训练开发阶段阅读 `docs/09_RTX5060_8GB_DEPLOYMENT.md`，再在目标机配置 WSL2 + CUDA PyTorch。
2. 从当前 `CODEX_START.md` 和 `CODEX_V51_START_HERE.md` 开始，按授权任务逐阶段编码、写测试、实际运行。
3. 先拿**有权使用的** 10–20 张复杂程度不同的谱面验证读写与预览，再接入 500 首。
4. 允许训练数据目录为空；未提供训练集时 UI 应显示未训练状态，不能伪装已有模型。

## 软件最终工作流
`导入数据 → 数据审查 → 构建数据集 → 训练 → 验证/登记 checkpoint → 输入新音乐 → 生成谱面 → 非 AI 审计 → 预览/评分/问题标注 → 局部修改/再生成 → 人工通过 → 本地导出/Phira 试玩`

**关键原则**：音频检查只提供确定性证据和风险提示，不能宣布“谱面已经可玩”；真正的可玩性需要在模拟器与真人试玩中验证。人工评分是独立数据，不能直接当成模型训练标签而不清洗。
