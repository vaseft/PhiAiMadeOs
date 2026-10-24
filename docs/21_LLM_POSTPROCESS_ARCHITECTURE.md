# 21｜LLM API 谱面后处理：严格隔离、低成本、版本控制

## 目标
PAMOs 模型生成的草稿谱面先由**可选的外部 API 大模型**提出**受限的结构化修订建议**；系统本地确定性验证建议，并仅以“可回滚的候选版本”应用。之后再进行之前规定的 **非 AI 音频/几何/格式审计**，最后人工审核打分。

```
[音乐与用户参数] → [PAMOs 本地 Note/Line/K 模型] → 候选 v0 (保留原件)
    → [LocalEvidenceBuilder 非 AI DSP、几何风险、局部时间/上下文摘要]
    → [可选 LLM API：只读取经授权脱敏后的证据与片段]
    → [只输出 patch proposals 的 JSON；绝不输出整份覆盖谱面]
    → [StrictPatchSchema + PermissionGuard + ApplyOnCopy]
    → [RPE/Phira Pro 格式和几何硬校验 + 局部听感证据差分]
    → [候选 v1 / 拒绝建议，不覆盖 v0]
    → [独立非 AI 审计：必须执行]
    → [人工审核预览/评分/选择接纳 patch]
    → [导出到经验证的目标客户端]
```

### 重要区分
- LocalEvidenceBuilder 可以在 LLM 之前跑“诊断”，但 **正式的独立审计必须在应用 LLM patch 之后重新运行**；诊断证据来自传统信号处理，不是 LLM 的自证。
- API 模型**没有真正接收到音频时，不得声称‘听了音乐’**。它只依赖 BPM、onset 强度、RMS、段落变化、Note/line 时间轴和现有本地检验警告。如果用户明确启用音频上云且 provider 支持音频，才可扩展多模态适配层；默认禁止上传完整音频。
- 训练得到的模型权重与 LLM API 分开；LLM 后处理 **完全不占用 RTX 5060 GPU，除非用户改为本地 LLM provider**。推荐默认 API 远端推理，但关闭时整套生成/审核必须继续工作。
- LLM 不能被视为检验器，最终安全与可玩性由机器可验证约束及真人决定。

## 运行模式
`off`（默认，完全离线） / `suggest`（仅产生候选修改，不自动写谱） / `apply_safe`（仅自动应用通过所有硬性检查的低风险建议，并生成新版本） / `human_select`（逐条勾选），建议默认 `suggest`。

## 分段协议
- 只按小节/音乐段落调用 LLM：默认 4 小节改写中心段，左右各 1 小节只读上下文；每首生成多个片段提案，按顺序应用与二次校验。
- 为保持整体连贯性，提供曲目级总体计划（难度、拍号/BPM map、统计密度、段落摘要），但不一次性发整份千 Note JSON。
- 任务预算：最多 12 个候选片段、每片段最多 12 个 patch 操作，单次响应限制字符/Token；费用估算，消耗与供应商价目由本地配置，不硬编码“官方价格”。
- 超时/429/内容截断/非 JSON/校验失败时 **fail closed**：保留原候选，报告失败原因，不影响不使用 API 的路径。

## 操作白名单（比任意 JSON Patch 安全）
允许：`MOVE_NOTE_TIME`, `CHANGE_NOTE_KIND`, `MOVE_NOTE_X`, `MOVE_NOTE_LANE`, `CHANGE_HOLD_END`, `ADD_NOTE`, `REMOVE_NOTE`, `TUNE_LINE_EVENT`, `SUGGEST_ONLY`。
- 各操作必须引用稳定 note ID/line ID；时间统一为拍数（整数/有理数），不允许直接改全局 BPM、offset、曲长、素材、判定机制、模型权重、训练参数、noise_areas、原始数据 `raw_payload`。
- 默认只可修改中心片段，边界上下文只读；在固定 K 下不得修改判定线、不允许跨轨/非整数 lane；不允许 4K 变 5K、不允许触碰噪域。
- 执行权限完全由本地 validator 决定，不信任 LLM 自报“合法”或“已检查”；建议与实际差分需要明确记录。
- 对 `ADD_NOTE` 由本地生成 ID，并强制 note 类型、位置、line_id、持续时间及复押/手法阈值；防止不受控复制一千条 Note。
- 每次调用有 `chart_hash + segment_hash + audit_version + condition_hash`；请求/响应的版本不匹配、基线变动、重复操作、未知 ID 一律拒绝。

## 物理时序和可玩性门禁
- 音符时间变动一般不超过 1/8 拍（默认，可在严格模式调低）；前后相邻 Note 的局部顺序、Hold 头尾顺序必须保持；不得依据 onset 置信度低的区域强制吸附。
- 纯配置固定轨道约束永远优先于 LLM；`TUNE_LINE_EVENT` 在 `pure_keys` 永远 422。
- 每次 patch 后按目标客户端真实坐标变换计算屏幕落点与遮挡风险；出现硬错误 `BLOCK`，演出相关低置信度风险 `WARN`，由人工裁决。
- LLM 调整不能悄悄破坏判定线层级、速度连续性、所属线合法性；超出候选片段边界的 Hold/线运动区间改变须阻止或显式扩大可改窗口并要求用户确认。

## 人工评分反馈闭环
- `model_original`、`llm_suggested`、`llm_applied`、`human_edited` 四类版本可追溯，显示几何/节奏/评分对照和修改前后谱面对比。
- 人工评分中标记某建议有效/无效，可用于将来训练 preference reranker；**不要**直接用 LLM 评语给本地生成模型反向传播，也不要将含错误 patch 自动并入 500 首真谱训练集。

## 新 API
- `GET /api/llm/providers`：已配置 provider 的模型能力（不泄露 key）；
- `POST /api/llm/connections/test`：连通性/JSON 输出能力测试（必须显式用户操作）；
- `POST /api/charts/{chart_id}/postprocess`：{version_id, provider_id, mode, segments?, user_instruction?, confirm_external_upload};
- `GET /api/postprocess/jobs/{job_id}`：进度与逐段结果/成本；
- `GET /api/charts/{chart_id}/versions`：版本树；
- `POST /api/postprocess/jobs/{job_id}/apply`：人工选择并应用一组提案；
- `POST /api/postprocess/jobs/{job_id}/rollback`：产生指向历史版本的回退版本，不删除历史。
- API 不可使用任意本地路径注入、文件读写或远程代码执行；自定义 Base URL 需白名单/禁止内网 SSRF / 回环策略按用户配置。
