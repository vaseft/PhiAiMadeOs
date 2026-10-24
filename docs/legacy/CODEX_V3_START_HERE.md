# 原 V5.1 包内 CODEX_START 技术清单（V3/V4 历史入口）

本文件保留原包 `CODEX_START.md` 的技术任务与实现要求，供后续开发参考；已纠正其入口优先级和无条件开始训练的歧义。**当前执行入口是根 `CODEX_START.md` 与 `CODEX_V51_START_HERE.md`。** 本文不能覆盖根 `AGENTS.md`、`docs/32_VERSION_CONTROL_POLICY.md` 或用户当前授权的工作范围，代码路径均相对仓库根目录。未实现功能和未运行的验收应明确标记。

## V4 对 V3 技术描述的纠正（2026-10-24）

- 目标客户端以 `Phira-Pro/Phira-Pro` 的锁定 commit 为准，非泛称 Phira。详见 `docs/19_PHIRA_PRO_CODE_INTEGRATION.md`。
- `噪域 noise_area` 是**独立机制**，不是异像类普通特效；V1 **只允许读取/保留与检验已存在噪域，不自动生成、训练或 LLM 修改**。详见 `docs/20_NOISE_AREA_DEFERRED.md`。
- 可选 API LLM 是**模型生成后的修订建议模块**。LLM 提议 patch → 本地硬校验 → **正式非 AI DSP/几何审计重新运行** → 人工评分；默认关闭。详见 `docs/21..24` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。
- rpe-next 源码使用 PolyForm Noncommercial 1.0.0，不因 Phira Pro 为 GPL-3.0 就能复制进 GPL 工程。

---

## 原包 V3 技术执行清单

你现在负责 **PhiAiMadeOs** 整套 Windows/WSL2 本地音游 AI 谱面训练与生成工作台，必须**真实编写代码**，不只是编写提案或静态页面。你接手的仓库包含之前的 v2 规范和最新 v3 设计，**技术要求按 V5.1 入口及现有根规则整合执行**。

## 必须先理解的纠正
“纯配置”就是 Phira 社区实际存在的**正常固定 4K、5K、6K 轨道谱面**，判定线不会动；不是“4k 风格”“四指风格”“4k 交互复杂度”。
系统的生成模式只有三条：
1. `regular`：常规 Phigros 式动态判定线谱面；
2. `pure_keys`：真实 4K/5K/6K 固定列，纯配置无任何判定线动画，AI 学习键位/手法；
3. `anomaly`：可玩的特殊异像，但引擎特性须被实测确认；局内“变化连击数”等先明确区分**视觉改变**和**真实判定/统计规则修改**，绝不可承诺不支持的原生能力。

三种模式支持：EZ 0–10、HD 11–14、IN 14–17、AT 15–18；可设置演出强度与风格（纯配置禁用）、狂野度 0–100（不能破坏静线）、可玩性优先级，以及版本化的训练模型选择。所有条件必须真正进入模型数据标注、训练、推理、导出与审计。若 K 模式数据不足，使用标记明确的 baseline/hybrid，**不允许**把规则谱包装成训练模型输出。

## 开始工作之前依次阅读
`AGENTS.md` → `README.md` → `docs/12_GENERATION_MODES_AND_CONDITIONING.md` → `docs/13_LANE_MODE_4K5K6K.md` → `docs/14_ANOMALY_FEATURES_AND_COMPATIBILITY.md` → `docs/15_CONDITIONAL_TRAINING_AND_DATA_LABELS.md` → `docs/16_GENERATION_PAGE_API_AND_STORAGE.md` → `docs/17_V3_VALIDATION_AND_MODE_MATRIX.md` → `docs/18_AGENT_V3_EXECUTION_PLAN.md`。再读 v2 的 `docs/01..11`、schema、配置和脚本。运行 `python scripts/validate_v3_contracts.py`。

## 硬件与部署
必须以 **RTX 5060 8GB 显存、16GB 主存**作为约束，Windows11 + WSL2 Ubuntu24.04 + Python3.12/PyTorch CUDA + FastAPI + SQLite + Vue3/TS + Vite + WebAudio。GPU 训练/推理任务串行，microbatch=1、梯度累积=16、CPU 音频特征缓存和 mmap、单模型分阶段训练，按 `configs/rtx5060_8gb.yaml` 执行。真机先跑 `python scripts/diagnose_hardware.py --require-cuda` 和 `python scripts/benchmark_tiny_train.py --steps 100 --grad-accum 16 --max-vram-gb 6.2`。无法访问目标机时标记 UNTESTED，严禁虚构测试结果。

## 实施任务（必须实际写代码、测试、汇报）
按 `docs/18_AGENT_V3_EXECUTION_PLAN.md` 的 M0–M8 编码；先修正 v2 误解并实现最小纵向切片：`GenerationRequestV3` → 条件规范化 → FixedLaneBaseline(4/5/6) → 纯配置静态线 IR → RPE ZIP → 重新解析 → CPU 非 AI 审计 → 同步预览与人工评分持久化。然后真实训练 Note 模型、静态 K-lane head、常规动态线模型，接入模型 bundle；最终实现常规、纯配置、异像三个模式的实际生成。

生成 API 必须包含 `POST /api/v1/generation-conditions/normalize`、`POST /api/v1/generations`、`GET /api/v1/models`、`GET /api/v1/capabilities`、审计/评论/修订/导出。前端切换到纯配置时必须只显示 4/5/6K 固定轨道，禁用演出和异像；wildness 只调整合法手法复杂度。

审计独立于模型，不调用 torch/LLM：传统 DSP、RPE 格式、BPM/offset、几何和固定线约束，AUDIT BLOCK/WARN 分级，进入前端真人评分。输出 Phira 本地 ZIP，至少分别实机验收 regular、4K、5K、6K，异像每个声称支持的特性也要有真机证明。

## 执行纪律
- 无授权素材不能自行批量破解/抓取官方谱面，也不能把别人音乐放入公开仓库；没有真实素材时用**合成测试样本**验证功能，不得伪造“已完成 500 首训练”。
- 不要将空训练权重注册为“可用模型”，也不要把只有规则生成的谱面声称 AI 生成。每项能力给出 `learned/hybrid/baseline_only/unsupported` 标签。
- 每完成一步都运行单测、真实可用性测试并保存环境、日志、证据；不能只做 UI 原型。
- 模型性能不足时先解决事件表示、样本标注、分窗口拼接/类别塌缩，再考虑增大参数；不能超出 8GB 显存预算。
- 不能因一步失败而跳到“已完成”状态；可实现剩余独立功能并按测试结果标记状态。

**本技术清单用于已授权的后续产品开发：先检查现有文件、运行静态 Schema 测试，按任务推进 M0/M1；训练阶段再运行 GPU 门禁。仅导入开发包不表示获得运行训练的要求。交付说明实际修改、运行命令、结果与未完成/未验证部分。**
