# 24｜Codex V4 实施任务与验收门禁

## V4 新任务优先级
**不重建既有 V3 项目**：先扫描现有文件/代码/测试，保留已完成模块；只增加 Phira Pro 目标、噪域独立受限通道、可选 LLM 后处理。旧 V3 文档内泛称“Phira”只表示兼容格式，**目标客户端默认改为 Phira Pro**；旧文档“噪域式视觉效果”不等于噪域机制。

### Gate P0：目标源码审计
- 固定 Phira Pro 和 rpe-next 的 commit/许可证，定位格式解析、触控屏蔽、渲染、RPE 导出、运行时加载和 Rhai 插件 API；输出 `docs/adr/V4_UPSTREAM_AUDIT.md`，特别核对当前噪域渲染差异。
- rpe-next 为 PolyForm Noncommercial，不复制代码到 GPL 分支；来源引用和数据许可证分类清楚。

### Gate P1：噪域管控（V1 禁用生成）
- Schema/API/UI 单独展示噪域设置，禁用 V1 创建；读取已存在噪域可保留但警告；通用 AI/LLM 写入路径彻底拒绝 `noise_areas/blockAreaList` 修改。
- 负向测试：anomaly, wildness=100, 可疑 LLM patch 也无法创建噪域。

### Gate P2：Provider 与 prompt
- 存储 provider profile、keyring 引用、费用限额和用户授权。实现 OpenAI-compatible 适配器的 stub/mocked tests；无实际 key 仍需通过集成模拟测试。
- Prompt `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md` 必须整体装入系统消息，不得在实现时删掉关键限制；标记版本/哈希。

### Gate P3：JSON patch 契约与安全
- JSON schema 验证、请求/响应绑定哈希、ID 权限白名单、原谱只读、Copy-On-Write、差分/回滚机制、跨段/跨 Hold 保护；此 Gate 必须包含 prompt injection/SSRF/秘钥泄漏测试。
- 实际实现 patch 应使用 Python Pydantic 强类型模型，不接受任意 JsonPatch path；PATCH_SCHEMA_V4 通过多模式负向 fixture。

### Gate P4：模型→LLM→审计→人工审核
- GUI 对生成候选 v0 / patch 候选 v1 做时序、密度、线运动对比；非 AI DSP、几何、导出/回读在 patch 应用后重新跑；人工评分记录在新版本。
- API LLM 失败能原样导出 v0；`suggest` 不许偷偷应用。

### Gate P5：实际 Phira Pro 导入
- 生成普通、4/5/6K、可验证异像样本，确认目标 Commit app 能导入播放，留版本与真实测试证据；噪域（V1）只检测**读入**既有样本的兼容情况。

### Gate P6：硬件低资源复测
- 不改变 V2 RTX 5060 / 16GB 内存训练预算；LLM 云 API 不吃本地 GPU；正式训练时禁止同时跑 GPU 渲染任务；测 RSS/VRAM。

## 交付清单
源码、README 部署、迁移说明、测试用例、schema 文档、provider 模拟器、可回滚 chart_version 数据结构、用户许可设置、基于实际目标客户端的兼容性测试记录。未实现项标 UNIMPLEMENTED；未经目标机器实测标 UNTESTED。
