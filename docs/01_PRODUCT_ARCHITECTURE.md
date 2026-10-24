
# 【V4 最新约束｜2026-10-24，优先于以下 V3 描述】

- 目标客户端以 `Phira-Pro/Phira-Pro` 的锁定 commit 为准，非泛称 Phira。详见 `docs/19_PHIRA_PRO_CODE_INTEGRATION.md`。
- `噪域 noise_area` 是**独立机制**，不是异像类普通特效；V1 **只允许读取/保留与检验已存在噪域，不自动生成、训练或 LLM 修改**。详见 `docs/20_NOISE_AREA_DEFERRED.md`。
- 可选 API LLM 是**模型生成后的修订建议模块**。LLM 提议 patch → 本地硬校验 → **正式非 AI DSP/几何审计重新运行** → 人工评分；默认关闭。详见 `docs/21..24` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。
- rpe-next 源码使用 PolyForm Noncommercial 1.0.0，不因 Phira Pro 为 GPL-3.0 就能复制进 GPL 工程。

---

> **V3 优先级提示（2026-10-24）**：本文件是 v2 通用基础说明。**纯配置模式是固定判定线的真实 4K/5K/6K，不是风格倾向**；新增的条件训练、模式分流、异常演出能力限制与按模式评分请以 `docs/12..18` 为准。若本文与 V3 冲突，以 V3 为准。

# 01｜产品规格与总体架构

## 1. 产品边界

**目标用户**：单机谱面作者/研究者。**输入**：用户有权使用的 music + 原训练谱面；推理时只需新音乐、目标难度与可选节拍人工修正。**输出**：可导入 Phira 的独立 RPE 本地 ZIP、谱面预览、审计报告、人工评分、模型与实验报告。

产品第一代以 Windows + RTX 5060 8GB / 16GB RAM 作为低配参考，桌面浏览器访问 `http://127.0.0.1:5173`。必须支持 CPU 模式跑解析、DSP、审核（速度较慢）。训练可要求 CUDA 并给清晰提示。

### 非目标
- 不负责无授权地抓取/破解官方曲库，不默认发布训练数据和模型权重。
- 不宣称 AI 替代真人谱师；不以自动全连作为真人可玩性的证据。
- 不在第一阶段还原全部不常见的故事板/自定义 shader 特性；必须保留原始事件并显式标示当前覆盖范围。

## 2. 核心工作流和状态机

```
[导入歌曲+谱面] ─> [有效性验证/时间轴对齐] ─> [可追溯数据集]
                                                |
                                              [训练]
                                                |
                                         [模型评估/注册]
                                                |
[新歌曲] ─> [音乐信号特征/节拍网格] ────────────> [谱面推理]
                                                |
                                  [RPE候选及不可变版本号]
                                                |
                           [非 AI 检验（格式+DSP+几何）]
                                 /            |           \
                              BLOCK          WARN         PASS
                              [修复]           \           /
                                               [审核工作台]
                                           [播放/看图/评分/标注]
                                              /          \
                                         [退回/修订]     [人工通过]
                                              |              |
                                        [再推理局部]   [打包/导出]
                                                             |
                                                      [Phira真人试玩]
```

`AUDIT_BLOCKED` 只有修复并重新审计才能进入可批准状态；人工可通过带理由的“忽略 WARN”操作，但不能绕过致命格式错误直接标记成可正常导出的谱面。

## 3. 模块边界

| 模块 | 输入 | 输出 | 约束 |
|---|---|---|---|
| `ingest` | 用户选择目录/ZIP | Manifest、原始文件索引 | zip 目录穿越/zip bomb 防护 |
| `chart_core` | RPE/合规的官方 JSON | IR、timeline、轨迹 | 精确 beat、变速 BPM、父子线、offset |
| `audio_features` | 本地音频 | 传统DSP特征与可缓存神经音频 embedding | **供模型的 embedding 与后续非AI检验进程严格隔离** |
| `training` | 已分组划分样本 | checkpoint、metrics | 可重现、可中断恢复 |
| `generation` | 新音频+难度+checkpoint | candidate IR | 保留种子、版本、谱面生成日志 |
| `audit` | candidate IR+原始音乐 | 结构/DSP/几何问题列表 | 不能调用模型推理 |
| `render` | candidate IR+歌曲时间点 | 可视化帧/时间轴 | 需与 exporter 共用同一套时间与几何函数 |
| `review` | 候选版本+审计 | 人工评分、标注、结论 | 不修改原候选；审阅人记录可追溯 |
| `export` | 审核通过的候选 | RPE + info.yml + assets + ZIP | 自校验，打包根目录无多余嵌套 |

`render` 必须区分两种视图：**实时游玩视角**（包含线的平移/旋转/上下落点）和**事件时间轴视角**（Note/判定线按音乐时刻排列）。仅静态纵向长图不足以审核判定线演出。

## 4. 推荐代码结构

```
PhiAiMadeOs/
  AGENTS.md  README.md  pyproject.toml  .env.example
  src/phiaimadeos/
    main.py
    api/{datasets,train,generation,audits,reviews,exports}.py
    core/{beat_time,chart_ir,chart_transform,chart_validator}.py
    ingest/{packages,rpe,official,manifest,split}.py
    features/{dsp_extract,audio_embeddings,cache}.py
    ml/{dataset,tokenizers,audio_encoder,structure_model,note_model,line_model,train,infer,registry}.py
    audits/{schema_checks,audio_checks,geometry_checks,report}.py
    rendering/{scene,timeline,playback_geometry}.py
    services/{jobs,storage}.py
    db/{models,migrations}.py
  web/src/{pages,components,stores,api,renderers,styles}/
  configs/  schemas/  tests/{unit,integration,e2e,fixtures}/
  data/{raw,derived,features,splits}/  runs/  models/  exports/
  scripts/{dev.ps1,train.ps1,doctor.ps1}
```

大型目录 `data/`、`runs/`、`models/`、`exports/` 默认 `.gitignore`，仅保存 `README/manifest` 和非版权合成 fixture。

## 5. 技术决策

- 时间与几何：确定性的 Python 核心；前端若 JS 复写，则使用共享的 golden fixtures 测试坐标与毫秒一致性，必要时把几何内核移至 Rust/WASM。
- 本地数据：SQLite 保存导入记录、模型实验、审核记录、版本与问题清单；音乐数据引用本地绝对路径、哈希，不把整个音频塞进数据库。
- 视频/音乐播放器：WebAudio 的 `AudioContext.currentTime` 作为主时钟；绘制按照同一“音乐时间→谱面时间”变换，禁止 setInterval 累积作为计时源。
- 大任务：训练/生成/批量分析独立后台 worker，任务状态可重启恢复；模型只由生成器加载，audit worker 不装载模型依赖。
- Python 只为算法后端，不强制 Python 执行前端帧动画。UI 易打包可选 Tauri；先完成 Web 版本再考虑桌面壳。

## 6. 性能预算（目标而非已实现）
- 500 首导入应分批处理、支持暂停续传/续跑，具备每文件错误隔离。
- 浏览器保持音画同步；大谱面按可视时间窗进行索引渲染，不在单帧扫描整曲事件。
- 8GB 显存训练 OOM 时自动采用更短片段/更小批量，必须记录降级情况，不偷偷切 CPU 并假装正常。
- 审阅页面切换版本、跳转问题点能保持帧和声音一致，不修改模型的原始输出。
