# 20｜噪域 Noise Area：独立功能、V1 不训练、不自动生成

## 决定（不可混淆）
1. **噪域不等于“特殊异像谱面”模式**。特殊异像 `anomaly` 可选其他已验证的视觉效果；噪域单列 `noise_area` 配置、能力和导出适配器。
2. **首版 NoteRhythmNet / LineMotionNet / PlacementNet/KLanePlacementHead 不学习噪域；首版推理也不生成噪域**。既不能训练噪域事件选择头，也不能通过模板偷偷插入。
3. 此功能仅用于**读入、保存、可视化提示、检验和将来升级准备**；UI 显示“实验性：V1 暂未开放生成”。配置 `noise_area.generation_enabled=false` 是硬门禁，独立于狂野度（100 也不例外）、特殊异像模式和 LLM 后处理开关。
4. Phira Pro 的特定版本已加入 rpe-next 噪域读取与游玩时触点阻挡；**不把“编辑器能画出噪域”当成“客户端精确还原全部视觉效果”**。官方、原生 BlockAreaList、rpe-next 格式不一致，必须版本识别后处理。用户指出渲染尚不完全一致，因此 V1 明确标记视觉还原限制。
5. 噪域 Active 期间覆盖触点可能导致合法 Note 无法被命中。首版不得用“可玩性自修复器”在生成谱面后添加任何噪域。

## 解析与可逆结构
- 在内部 IR 中增加扩展字段 `noise_areas`，不参与通用 Note/判定线训练张量。若解析到噪域，`source_format`、`source_version`、`origin_payload_hash`、原始 JSON 片段、字段变更映射及未识别字段均须保留。
- rpe-next 中 `blockAreaList` 和原生 `BlockAreaList` 可能仅名称相似，判别需检查矩形坐标属性：Next 有 `bottomLeft/topRight`（1350×900 画布）；原生格式有 `bottomLeftPercentage/topRightPercentage`（屏幕百分比）。**不能只依赖 META.RPEVersion**。另需识别 Line2Area。
- rpe-next 噪域生命周期/激活时间采用全谱拍数与 `BPMList`，包含 `activeIntervals`，可能有移动/旋转/缩放独立事件轨道、锚点、反转、预警闪烁和图层。变换/坐标、事件插值严格参照目标源版本及回放 fixture。
- 允许保留未修改的噪域原样（round-trip），但改动后必须显式确认目标格式和是否有损；对无法无损导出的目标 **BLOCK 并解释**，不得丢字段静默导出。
- **单向转换**：对明确支持的 `rpe-next → Phira Pro 内部读取` 通路创建具体 adapter；不能推定任意官方 ↔ Next 互转。需对所有字段逐项比对并报告损失，未知字段按原样保存。

## UI 和非 AI 验证（V1 仅实验性预览/检查）
- 独立设置区 `噪域（实验性）`：支持状态提示（只读导入/兼容性、生成不可用）、来源格式说明、详细警告；创建/生成按钮禁用；LLM 工具中完全排除噪域写权限。
- 若用户导入现成噪域谱面：展示区域时间轴、生命期、Active/Ready 片段、触控拦截近似风险、Note 命中位置与 Active 区域重合报警；要求根据 Phira Pro 当前源代码坐标、触点感染/抬手规则确认实际可玩性。
- 几何检测为传统确定性算法，不调用 AI；渲染一致性需真实客户端截图比对。

## 未来再开放的独立里程碑（本次不实施）
有足够合法的噪域样本、完成 Next vs 原生格式 fixture 和真实触控验收之后，另起 NoiseAreaPlanner、NoiseCollisionAuditor 和模型训练数据集。`noise_area.generation_enabled` 的变更需独立版本升级和人工批准，不得由配置随意打开。

## 参考源
- https://github.com/Phira-Pro/Phira-Pro/blob/main/docs/development/rpe-next-noise.md
- https://github.com/kclg-YSJ/rpe-next
