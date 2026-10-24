# 19｜Phira Pro 源码级集成与 PhiAiMadeOs (PAMOs) 系统边界

## 身份与依赖
- 本系统全称 **PhiAiMadeOs**，简称 **PAMOs**；不能在应用界面/日志中误称为 Phira 官方功能。
- 验证目标为 `https://github.com/Phira-Pro/Phira-Pro`，GPL-3.0 的 Phira v0.8.2 衍生项目。**实际开始编码前固定具体 commit SHA**，阅读根 `LICENSE`、`README.md`、`Cargo.toml`、`rust-toolchain.toml`、`docs/development/rpe-next-noise.md`、`docs/plugins/README.md` 和工作区内现有 UI / 图表载入 / 渲染 / 判定 / 导入模块。
- **不要**克隆后粗暴重写整个 Rust 客户端，也不能未经核实将 Rhai Plugin API v1 当作允许装入 PyTorch 或运行任意 HTTP 服务的接口。插件文档需按具体 API 核对；如插件不足以承载生成页面，采用“本地 Web 工具生成谱面 + Phira Pro 原生客户端导入/调试”分层集成；如确需客户端内置页面，仅使用源代码明确支持的桥接方案。
- 推荐两个独立工作区：`upstream/Phira-Pro` 为 GPL 源码和客户端测试；`PhiAiMadeOs/` 为本地训练、生成、审核的 Python+Vue 工具。仅在经审计确认正确时实现 Rust 桥接，保持改动可回溯。

## 真实集成路线（先证据后修改）
1. `git clone https://github.com/Phira-Pro/Phira-Pro upstream/Phira-Pro`；记录 HEAD SHA / 分支 / 版本标签，核对 `git status`。
2. 运行其 README 当前构建及 Rust 单测，记录平台差异。不声称 UI 内置前已经展示在 Phira Pro 客户端里。
3. 确认已有谱面包输入和运行时渲染路径，制作已知 RPE、PEZ、带 Next 噪域 fixture 的输入/输出对照。
4. 最小集成采用本地 Loopback FastAPI 服务 + 浏览器操作台：`音乐 → PAMOs 生成 → 传统 DSP 审计 → 人工审核 → 导出 RPE/PEZ → Phira Pro 加载`。自动化可通过用户明确配置的本地导入目录完成；不可假设存在未经证实的 HTTP 导入 API。
5. 如需嵌入客户端，先提交 ADR 记录原生 UI、WebView、插件 API 3 条路径的差异/兼容性，再实现受控文件桥接。客户端使用 Rust，不应被迫链接 Python/CUDA。
6. 使用真实客户端验证：谱面加载、音画 offset、固定 4/5/6K、判定线变化、UI 事件和噪域行为；提交 commit / 截图 / 录像 / 测试版本，不允许仅凭浏览器渲染通过验收。

## 许可证与资产
- Phira Pro 声明 GPL-3.0；复用或修改其代码时保留 SPDX、著作权和 LICENSE；发布二改构建时履行对应源代码提供义务，不引入与 GPL 不兼容的代码。
- `rpe-next` 当前仓库 LICENSE **不是 GPL-3.0**，而是 **PolyForm Noncommercial 1.0.0**（禁止商业用途的许可）。不能因它“源码开放”就声称与 GPL 自动兼容。优先仅按公开格式和自写代码实现独立 JSON/PEZ 适配器，不直接搬运 rpe-next 源码；若需要复制其实现，先取得相应授权并审计冲突。
- 谱面、歌曲、曲绘授权与程序 GPL 许可分开处理。是否能用于训练/再发布，需按各个作者/来源确认。
- 外部 API 后处理时禁止未经用户许可上传完整音乐、谱面正文或含版权受限的曲目资料。

## 验收要求
- 任何 `compatible_with_phira_pro` 必须附目标 commit / app build / 真实导入测试。
- `client_build_status` 和 `chart_playtested` 必须分别记录。
- 自动审计在 Python 本地运行；模型/LLM 必须和运行时判定逻辑隔离。
