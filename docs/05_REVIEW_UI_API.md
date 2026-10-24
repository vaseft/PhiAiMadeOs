
# 【V4 最新约束｜2026-10-24，优先于以下 V3 描述】

- 目标客户端以 `Phira-Pro/Phira-Pro` 的锁定 commit 为准，非泛称 Phira。详见 `docs/19_PHIRA_PRO_CODE_INTEGRATION.md`。
- `噪域 noise_area` 是**独立机制**，不是异像类普通特效；V1 **只允许读取/保留与检验已存在噪域，不自动生成、训练或 LLM 修改**。详见 `docs/20_NOISE_AREA_DEFERRED.md`。
- 可选 API LLM 是**模型生成后的修订建议模块**。LLM 提议 patch → 本地硬校验 → **正式非 AI DSP/几何审计重新运行** → 人工评分；默认关闭。详见 `docs/21..24` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。
- rpe-next 源码使用 PolyForm Noncommercial 1.0.0，不因 Phira Pro 为 GPL-3.0 就能复制进 GPL 工程。

---

> **V3 优先级提示（2026-10-24）**：本文件是 v2 通用基础说明。**纯配置模式是固定判定线的真实 4K/5K/6K，不是风格倾向**；新增的条件训练、模式分流、异常演出能力限制与按模式评分请以 `docs/12..18` 为准。若本文与 V3 冲突，以 V3 为准。

# 05｜人工审核工作台：可视化、听音、打分与 API

## 1. 四个主要页面

**A 数据集管理**：本地选择训练目录→自动识别 ZIP/RPE/官方兼容格式→显示授权信息/采样率/长度/音画 offset/解析告警→按歌曲分组/去重→导入进度。无法识别格式不入训练集。

**B 模型训练**：训练数据版本选择、配置编辑、显卡/显存检查、开始/暂停/恢复、loss 曲线、validation 事件指标、checkpoint 注册、模型选择与真实运行日志。必须显示“当前有没有有效训练好的模型”。

**C 新音乐生成**：音乐上传/本地引用、难度/强度/输出随机 seed、可选人工调整 BPM/offset、当前 checkpoint、生成进度，生成版本列表；完成后自动排队执行非 AI Audit，直到审计结束才可操作正式评分状态。

**D 审核工作台（最重要）**：

```
┌────────────────────────────────────────────────────────────────────────┐
│ PhiAiMadeOs  歌曲 / 候选 v4  模型 abc123  [▶] [0.5x][1x] 00:54.230 │
├───────────────────────┬────────────────────────┬───────────────────────┤
│ 实时 Phigros 视角      │ 时间轴/波形/谱图        │ 审核与诊断            │
│ [动态判定线+四种Note]  │ [波形+onset+beat网格]   │ BLOCK 0 WARN 3        │
│ [可选显示线 ID/触点]   │ [Note轨+Line事件]      │ OFFSET_SUSPECT 54s    │
│ [可选自动游玩展示]     │ [选择/框选/跳转/缩放]   │ [点击跳转]            │
├───────────────────────┴────────────────────────┼───────────────────────┤
│ 分项评分  节奏[0..5]  手感[0..5]  可读性[0..5]  演出[0..5]       │
│ 难度[0..5]  完整性[0..5]  总分 xx/100（只由人工输入计算）         │
│ [在 54.2s 标记问题] [通过] [退回修改] [拒绝] [导出试玩包]        │
└────────────────────────────────────────────────────────────────────────┘
```

必须支持：暂停/播放、1/2 倍速（保持画面与音频同步）、按小节跳转、拖动进度条、精准到毫秒显示；音频波形与 onset 柱、音符和线运动事件分轨，独立隐藏/显示；按 Issue 点击跳转、查看临近 2 小节。

真实判定线演出预览需复用 `chart_core` 的时间/几何逻辑；测试预览与 Phira 实机差异。当浏览器未获取音频播放授权时，明确显示“需用户点击播放”。“Autoplay 演示”不等于真实可玩性验证。

## 2. 人工评分（六维 0..5，权重合计 100）

| 维度 | 权重 | 审核含义 |
|---|---:|---|
| 节奏契合（rhythm） | 25 | 音符选择与节奏、音乐结构是否合理 |
| 手感与可玩性（playability） | 25 | 交互是否符合触控手感、无明显反人类配置 |
| 可读性（readability） | 20 | Note 和线移动是否看得清、预判是否合理 |
| 演出设计（line_motion） | 15 | 多线运动是否配合音乐、有逻辑 |
| 难度匹配（difficulty_fit） | 10 | 实际密度、技术要求是否符合选定难度 |
| 完整性（completeness） | 5 | 结构完整、结尾合理、无明显缺段 |

`total = Σ (dimension_score / 5 * weight)`，四舍五入到 1 位小数。人工每项必填，不允许默认全 5；用户实际没玩过时可以填 `not_playtested` 标识，评分无法冒充试玩证明。

评分记录包括：`review_id`、`candidate_id`、`candidate_version`、`reviewer`（本地用户名）、`created_at`、`scores`、`total`、`decision`（APPROVED/REVISION_REQUESTED/REJECTED）、`playtested`、`comment`、`annotations[]`。一次审核结论和所审核候选版本绑定，不可被后续生成覆盖；多轮审核可并列存在。

## 3. 人工问题标注

点击任意时间点标记 `NOTE_TIMING`、`NOTE_TYPE`、`HOLD_OVERLAP`、`PLAYABILITY`、`LINE_MOTION`、`VISUAL_OCCLUSION`、`DIFFICULTY`、`OTHER`；添加起止毫秒、note/line ids、文字备注、严重程度 `LOW/MEDIUM/HIGH`、建议 `REGENERATE_SEGMENT/MANUAL_EDIT/IGNORE`。支持对选定 2/4/8 小节局部再生成，保存差异 diff；不应覆盖评分记录。

## 4. 版本和工作流规则
- 先生成 `candidate_v1`；独立调用审计→审计报告 `audit_v1`；用户评分→`review_v1`。
- `REVISION_REQUESTED` 后选择区域生成新候选 `candidate_v2`，重做审计（不沿用 v1 的自动评分），旧版继续可查看。
- `APPROVED` 但 `playtested=false` 时允许导出**标记待试玩的本地 ZIP**，不得显示“通过实机试玩”。实机 Phira 导入与试玩后上传/登记结果，可升至 `PLAYTEST_CONFIRMED`。
- `BLOCK` 的候选只能在调试页面预览，默认不能人工批准。WARN 可有理由忽略并记录。

## 5. 建议 API（草案，可迭代但应保留语义）

| 方法/路径 | 功能 |
|---|---|
| `POST /api/v1/datasets/import` | 选择本地待导入任务；返回 job_id |
| `GET /api/v1/datasets/{id}/quality` | 查看解析、许可、分组与时间轴校验结果 |
| `POST /api/v1/datasets/{id}/split` | 固定分组划分，生成 dataset_version |
| `POST /api/v1/train/jobs` | 启动实验，记录 config 与 dataset_version |
| `GET /api/v1/train/jobs/{id}` | 训练状态和日志 |
| `GET /api/v1/models` | 查询实验模型与可用状态 |
| `POST /api/v1/generations` | 新音乐 + 模型 + 难度/seed，异步生成 |
| `GET /api/v1/candidates/{id}` | 读取候选、版本与统计 |
| `POST /api/v1/candidates/{id}/audit` | 执行独立非 AI 审计，写不可变报告 |
| `GET /api/v1/candidates/{id}/audit/latest` | 获取 issues + metrics + 音频叠加数据 |
| `GET /api/v1/candidates/{id}/timeline?from_ms=&to_ms=` | 分页返回可视事件 |
| `POST /api/v1/candidates/{id}/reviews` | 提交真人分数/意见/结论 |
| `POST /api/v1/candidates/{id}/revisions` | 局部再生成并建立新版本 |
| `POST /api/v1/candidates/{id}/export` | 生成 Phira 本地测试 ZIP |
| `POST /api/v1/candidates/{id}/playtests` | 登记客户端版本/导入/试玩结果 |

文件浏览必须限制预先配置的允许目录，阻断任意路径读取；上传音频做 MIME/解码校验和资源配额。评分提交校验每项 0..5、人工 reviewer、关联版本的完整性。持久化用 SQLite，不允许仅前端 localStorage 存分数。

## 6. 数据表
`datasets`、`songs`、`charts`、`licenses`、`splits`、`experiments`、`model_registry`、`generations`、`candidates`、`candidate_versions`、`audit_reports`、`audit_issues`、`reviews`、`review_annotations`、`playtests`、`jobs`。外键/唯一约束：候选不可变 ID + 版本、数据集哈希 + 实验号、review→candidate_version、audit→candidate_version。
