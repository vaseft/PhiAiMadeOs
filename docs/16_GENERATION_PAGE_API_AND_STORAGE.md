
# 【V4 最新约束｜2026-10-24，优先于以下 V3 描述】

- 目标客户端以 `Phira-Pro/Phira-Pro` 的锁定 commit 为准，非泛称 Phira。详见 `docs/19_PHIRA_PRO_CODE_INTEGRATION.md`。
- `噪域 noise_area` 是**独立机制**，不是异像类普通特效；V1 **只允许读取/保留与检验已存在噪域，不自动生成、训练或 LLM 修改**。详见 `docs/20_NOISE_AREA_DEFERRED.md`。
- 可选 API LLM 是**模型生成后的修订建议模块**。LLM 提议 patch → 本地硬校验 → **正式非 AI DSP/几何审计重新运行** → 人工评分；默认关闭。详见 `docs/21..24` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。
- rpe-next 源码使用 PolyForm Noncommercial 1.0.0，不因 Phira Pro 为 GPL-3.0 就能复制进 GPL 工程。

---

# 16｜生成页面、接口、状态机、数据库升级规范

## 1. 核心用户路径
① 上传音频得到安全 `music_asset_id` → ② 本地 DSP 探测 BPM/offset 并允许校正 → ③ 获取模型列表/能力矩阵 → ④ 选择模式、难度、演出、狂野度 → ⑤ 提交生成、查看阶段日志 → ⑥ 生成结果进入**独立非 AI 审计** → ⑦ 浏览器同步预览/打分/标记问题 → ⑧ 退回/局部重生成或导出 ZIP → ⑨ 本地 Phira 试玩记录。

## 2. 前端组件
- `MusicUploader.vue`：格式/时长/路径受限，使用上传资产 ID，不接受外部任意路径。
- `DifficultySelector.vue`：EZ(0–10)/HD(11–14)/IN(14–17)/AT(15–18)；数值选择器随类别切换，不自动猜重叠等级大类。
- `ModeSelector.vue`：常规/纯配置/特殊异像，三者**互斥**。
- `KeyCountSelector.vue`：仅 pure_keys 展示 4/5/6K；显眼注明**固定轨道、判定线不动**。
- `PerformanceControls.vue`：regular/anomaly 演出强度/风格；pure_keys 禁用并提示原因。
- `WildnessSlider.vue`：0..100，每模式有提示：纯配置只更改键位 pattern；不更改列数/线动画。
- `CapabilityFeaturePicker.vue`：仅 anomaly 能选，需获取目标 Phira 版本的 capability registry，`unsupported` 显示不可用原因。
- `GenerationSummary.vue`：提交前显示 normalized conditions 和覆盖项，任务中显示 checkpoints 与 fallback 来源。
- `ModeAwarePreview.vue`：`ChartIR.chart_mode` 路由纯配置 K-lane renderer 或动态线 renderer；两者共用音频时钟。
- `AuditPanel.vue`：非 AI 证据、音符/线定位、严格显示 BLOCK/WARN。
- `ReviewScorePanel.vue`：真人评分 + 标签 + 通过/退回 + 分模式评分量表，默认不代填分数。

## 3. API（版本 v1 保持 REST 语义）

| 方法 | 路径 | 请求/响应 | 权限边界 |
|---|---|---|---|
| POST | `/api/v1/assets/music` | multipart 音频 → `music_asset_id`, 探测结果 | 本地安全沙箱 |
| GET | `/api/v1/models` | bundle 及 `modes_supported` / `key_counts_supported` | 无假 bundle |
| GET | `/api/v1/capabilities?engine=phira&version=x` | special feature 支持状况与证据 | 不支持不可选 |
| POST | `/api/v1/generation-conditions/normalize` | `GenerationRequest` → `effective_conditions`, `overrides`, `errors` | 前后端一致 |
| POST | `/api/v1/generations` | `GenerationRequest` → `job_id`,`effective_conditions` | 独立 worker + GPU 队列锁 |
| GET | `/api/v1/generations/{job_id}` | 状态、进度、log、fallback 信息 | 只报告事实 |
| GET | `/api/v1/candidates/{id}` | 版本化候选 & IR + model bundle | 不覆盖旧版本 |
| GET | `/api/v1/candidates/{id}/timeline` | 分页音符/轨道/线事件/波形 | 防巨包、精确同步 |
| POST | `/api/v1/candidates/{id}/audit` | 非 AI CPU 审计 | 不可调用 torch |
| POST | `/api/v1/candidates/{id}/reviews` | 真人多维分数、时间标记 | 当前 candidate_version FK |
| POST | `/api/v1/candidates/{id}/revisions` | 2/4/8 小节重生成 + patch manifest | 保留模式不变式 |
| POST | `/api/v1/candidates/{id}/exports` | Phira ZIP 本地导出 | 校验 + 回读 + 审核状态 |
| POST | `/api/v1/candidates/{id}/playtests` | Phira 真机版本/平台/成功/视频或备注 | 人工证据 |

生成请求与能力矩阵见 `schemas/generation_request.schema.json`、`schemas/capability_matrix.schema.json`。**禁止**直接信任前端、客户端路径或未认证本机以外的接口。

## 4. 后端标准化时必须可解释
```text
request: chart_mode=pure_keys, key_count=5, performance_intensity=98, wildness=90
response: effective.chart_mode=pure_keys
          effective.key_count=5
          effective.performance_intensity=0
          effective.performance_style=none
          effective.special_features=[]
          overrides=[{field:'performance_intensity',requested:98,effective:0,reason:'STATIC_LANE_MODE'}]
```
不支持 K、非法 difficulty/class、纯配置携带 anomaly features 时 422，避免掩盖用户严重错误；可解释的“UI 残留演出强度”才采用覆盖并返回。

## 5. 数据库迁移
新增/扩展表：
- `generation_requests`: id, music_asset_fk, model_bundle_fk, request_json, effective_json, condition_schema_version, seed, created_at。
- `generation_jobs`: id, request_fk, state, started_at, finished_at, error_json, fallback_used, worker_memory_report。
- `candidate_versions`: id, generation_fk, ordinal, chart_mode, key_count_nullable, chart_ir_hash, export_status, created_at。
- `model_bundles`: bundle_id, feature_schema_version, condition_schema_version, checkpoints_json, supported_modes_json, supported_key_counts_json, evaluated_engine_versions, validation_level。
- `capability_probes`: engine, version, feature_id, capability_state, evidence_uri, tested_at, fixture_sha256, note。
- `audit_reports`: candidate_version_fk, audit_engine_version, issues_json, metrics_json, created_at。
- `reviews`: candidate_version_fk, reviewer, rubric_version, review_json, score_total, decision, playtested, created_at。
- `revisions`: source_version_fk, target_version_fk, segment_range, requested_condition_delta, locked_fields, patch_json。
- `training_labels`: chart_fk, mode, key_count, difficulty_class, difficulty_value, source_confidence_json, tags_json, reviewed_at。

约束：`chart_mode == pure_keys` ↔ `key_count ∈(4,5,6)`；在 application + DB 可执行 CHECK；迁移不能丢弃 v2 的原评分、候选及 model registry。SQLite 开启 FK/WAL，迁移使用 Alembic；不得同步启动多个本地训练 worker。

## 6. 状态机
`UPLOADED → CONDITIONS_VALIDATED → QUEUED → GENERATING → GENERATED → AUDITING → (AUDIT_BLOCKED | READY_FOR_REVIEW) → REVIEWING → (APPROVED | REVISION_REQUESTED | REJECTED) → EXPORTED → PLAYTEST_CONFIRMED`。真实 `AUDIT_BLOCKED` 不能自动跳入 APPROVED。单独的 `GENERATION_FAILED`、`MODEL_UNAVAILABLE`、`CAPABILITY_UNAVAILABLE`、`OUT_OF_MEMORY` 显示原因与恢复动作。

## 7. 生成结果溯源（必须）
`candidate_manifest.json` 含请求/生效条件、bundle 和 3 阶段哈希、音频 hash、DSP 版本、训练集版本、随机 seed、模型/模板/人工来源比例、IR 版本、导出适配目标、fallback 清单。只存当前机器安全本地引用，不把有版权的音乐放进公开日志。

## 8. UI 评分表按模式变更
权重保持 v2 100 分：节奏25、可玩性25、可读性20、表现15、难度10、完整5。
- regular/anomaly 的 15 分是“判定线/异像演出”。
- pure_keys 的 15 分为“键位配置变化与音乐表现”，**不能因为判定线不动而扣分**。
- 若 `anomaly` 中 unsupported 功能被请求，应在生成前错误提示，不让它成为后期审核才发现的遗漏。
- `score_total` 仅由真人输入的分项计算，并记录 `rubric_version=3`；评审可事后登记 Phira 试玩结果，但不反写评分历史。

## 9. 用户体验/性能
Vue3+TS+Vite+Pinia+Element Plus；谱面渲染可用 PixiJS（经性能对比确定）；音频由 WebAudio/AudioContext 作为唯一播放时钟；渲染 RAF 与音频时间同步。接口在 localhost；长任务由本地子进程及 SQLite 任务表驱动，GPU 同时一个任务；浏览器不传任意服务器可读路径；波形按范围分页/LOD，避免 16GB RAM 压力。
