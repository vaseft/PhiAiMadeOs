# 25｜V4 依据与许可证重点

查阅日期：2026-10-24。开发前须重新核实最新 commit 和 LICENSE，以下为当前设计依据：

- Phira Pro： https://github.com/Phira-Pro/Phira-Pro — Phira v0.8.2 改版、GPL-3.0、Rust；README 声明 pro.16 已包含分层噪域兼容、素材、输入拦截、插件 API 和构建说明。
- 噪域兼容专项： https://github.com/Phira-Pro/Phira-Pro/blob/main/docs/development/rpe-next-noise.md — 可追溯格式识别、BPM 转换、运动/遮罩、触点拦截、fixture、采样与真机限制。文档以 rpe-next 特定历史版本测试，不能假设以后版本无变化。
- Re:PhiEdit Next：https://github.com/kclg-YSJ/rpe-next — 原生 Next 噪域编辑、JSON/PEZ、渲染等；其仓库许可证为 **PolyForm Noncommercial 1.0.0**，非 GPL，默认不得复制其源码进 GPL 发布物。
- Phira Pro 中 Rhai 插件接口：https://github.com/Phira-Pro/Phira-Pro/blob/main/docs/plugins/README.md；该 API 不等于 Python 模型执行环境。
- GPL-3.0：https://www.gnu.org/licenses/gpl-3.0.en.html ，发布源码修改需要满足相应条款。GPL 项目可以按规则调用独立的网络服务，但这**并不自动解决第三方客户端/代码/音乐/谱面各自许可**。

如 README 与源代码不一致，优先实际锁定 commit 下的源码与测试。不要在项目中声称官方 Phigros/Phira 或 rpe-next 全面兼容。
