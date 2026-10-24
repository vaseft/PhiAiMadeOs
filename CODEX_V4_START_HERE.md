# 给 Codex 的启动 Agent —— PAMOs / PhiAiMadeOs V4

你正在已有 PhiAiMadeOs V3 规划的基础上开发 V4。**先读取根目录 AGENTS.md / README.md / V4_CHANGELOG.md 和 docs/19..25、prompts/LLM_CHART_REFINER_SYSTEM_ZH.md、schemas/llm_*.json，再读取 V3 既有 docs/09..18。**不要重做已经验证的模块或把规范误当成已实现软件。

核心用户需求：
- 软件名 PhiAiMadeOs，简称 PAMOs；目标运行时为开源 GPL-3.0 `https://github.com/Phira-Pro/Phira-Pro`，先审计锁定 commit 的源码再写适配。
- 约 500 首合法谱面，RTX 5060 8GB VRAM + 16GB RAM 做低显存分阶段训练，接常规谱面/4K5K6K 静态纯配置/其他已验证的特殊异像。
- **噪域单独选项，V1 训练和推理都禁止生成**。若导入有噪域谱面，允许只读保留/格式鉴别与可玩性风险告警；把 rpe-next 与官方原生结构区别清楚。不得通过狂野度/大模型绕过。
- 新增 **外部 LLM API 对 PAMOs 模型结果做二次后处理**：提供服务商/模型/API Key/费用/隐私开关；提供详尽的已有中文 system prompt；仅允许局部 schema 结构 patch，不能整谱覆盖；默认仅建议，不自动应用。
- 任何 LLM 修改之后仍需要原先的非 AI DSP/几何/格式校验，人工能同步听歌、看谱、看 diff、打分、选择采纳、回滚、导出可游玩的 Phira Pro 谱面。
- rpe-next 仓库采用 PolyForm Noncommercial 许可证，不能直接复制代码并假装兼容 GPL-3.0。以协议观察与独立适配器为首选。

实施：
1. 扫描当前项目树、测试结果和最新 upstream Git SHA，生成 `docs/adr/V4_UPSTREAM_AUDIT.md`，列可用 API 和兼容边界。
2. 执行 `python scripts/validate_v4_contracts.py` 和既有 V3 测试；修复契约冲突。
3. 实现噪域独立封禁和 read-only roundtrip 的最小功能，覆盖负向用例。
4. 实现 Provider、API Key 安全存储、用户同意、字段预览和网络模拟测试，不依赖实际付费 API 才能跑测试。
5. 实现严格 JSON patch 提议、权限校验、版本化原子应用、回退；输入资料注入防御和 API 失败回退。
6. 连接 `生成候选→可选 LLM→正式非 AI 审计→人工审核评分→导出 Phira Pro` 的真实端到端路径。
7. 用合法 fixture 和实际目标 Phira Pro 构建进行试玩，不得伪造通过结论。

本轮先交付一个可以执行测试的垂直切片，同时输出真实文件/代码/测试日志和未完成清单。不准用假训练权重、硬编码返回高分或伪造 API 审计记录。
