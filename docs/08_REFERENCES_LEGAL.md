
# 【V4 最新约束｜2026-10-24，优先于以下 V3 描述】

- 目标客户端以 `Phira-Pro/Phira-Pro` 的锁定 commit 为准，非泛称 Phira。详见 `docs/19_PHIRA_PRO_CODE_INTEGRATION.md`。
- `噪域 noise_area` 是**独立机制**，不是异像类普通特效；V1 **只允许读取/保留与检验已存在噪域，不自动生成、训练或 LLM 修改**。详见 `docs/20_NOISE_AREA_DEFERRED.md`。
- 可选 API LLM 是**模型生成后的修订建议模块**。LLM 提议 patch → 本地硬校验 → **正式非 AI DSP/几何审计重新运行** → 人工评分；默认关闭。详见 `docs/21..24` 和 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`。
- rpe-next 源码使用 PolyForm Noncommercial 1.0.0，不因 Phira Pro 为 GPL-3.0 就能复制进 GPL 工程。

---

# 08｜工程参考与数据合规

> 信息检索日期：2026-10-24。RPE/Phira 公开文档有一部分内容以早期版本为基础，实施时应同时检查当前 Phira 客户端源码和实际导入样本；**尤其留意网页文档中 BPM 公式的可能笔误**。音频里一拍时长必须是 `60/BPM` 秒。

## 格式与播放器

- [Phira 谱面包结构](https://yuevuwu.github.io/phira-docs/en/chart-standard/index.html)：ZIP 根目录 `info.yml` 与它引用的文件。
- [Phira ChartInfo 字段](https://yuevuwu.github.io/phira-docs/en/chart-standard/chartinfo.html)：`chart`、`music`、`illustration`、`offset`、`difficulty` 等。
- [RPE 根结构](https://yuevuwu.github.io/phira-docs/en/chart-standard/chart-format/rpe/root.html)：BPMList/META/judgeLineList。
- [RPE note 字段](https://yuevuwu.github.io/phira-docs/en/chart-standard/chart-format/rpe/note.html)：type 1 Tap、2 Hold、3 Flick、4 Drag。
- [RPE judgeLine](https://yuevuwu.github.io/phira-docs/en/chart-standard/chart-format/rpe/judgeLine.html)：eventLayers/father/notes。
- [RPE events](https://yuevuwu.github.io/phira-docs/en/chart-standard/chart-format/rpe/event.html)：moveX/moveY/rotate/alpha/speed 与 easing。
- [Phira 常见问题与官方资源上传限制](https://docs.phira.link/help/)。
- [PhigrosChartRender](https://github.com/Temmie0125/PhigrosChartRender)：有 RPE/官谱纵向预览图渲染思路（注意其 GPL-3.0 许可证，不能不考虑兼容性直接复制代码）；不能代替实时运动线播放器。

## 训练与非 AI 音频分析参考

- [Transfer Learning for Rhythm Game Chart Generation from Music Transcription and Across Games](https://arxiv.org/abs/2610.14955)：2026 音频转录预训练特征迁移音游谱面生成研究，可指导小样本冻结 encoder。
- [AutoOsu](https://issyun.github.io/autoosu/)：约千张谱面训练可跑通自动谱面，但其任务远比动态多线 Phigros 简单。
- [Time-based Chart Partitioning](https://ojs.aaai.org/index.php/AIIDE/article/view/36808)：时间分区与局部配置一致性。
- [rhythm-chart-diffusion](https://github.com/qxxiit/rhythm-chart-diffusion)：离散扩散与自回归方案对比的研究项目，不能假定它已支持 Phigros。
- [librosa onset](https://librosa.org/doc/latest/generated/librosa.onset.onset_strength.html)：经典频谱通量起音强度；非 AI 审计要记录算法参数。
- [librosa beat](https://librosa.org/doc/latest/generated/librosa.beat.beat_track.html)：传统节拍跟踪，但具有倍拍/半拍歧义，不能绝对化。

## 数据源与版权规则

1. 开放下载、个人拥有、可在 Phira 游玩，**均不自动意味着可以用来训练或重新分发**。逐首/逐谱确认许可；`license_status=unknown` 的样本需单独隔离，禁止未经核实上传/公开数据或生成模型权重。
2. 音乐、谱面、曲绘是独立版权项，分别存授权来源/链接/许可证明及允许的用途。
3. Phira 文档禁止上传 Phigros 独占曲、原创曲绘和官方谱面/强化谱面；不要将本地测试 ZIP 默认上传社区。不能加入绕过加密、破解防护、批量规避限制的自动下载器。
4. 如果引用 GPL 等开源渲染器源代码，必须核对相应许可证义务；更推荐只参考接口/思路、自行实现适配层并保留许可声明。
5. 本项目默认本机离线处理；如以后公开训练数据/模型，在发布前单独做法律与作品许可检查。

## 给 Agent 的查证任务

- 检查用户本地 Phira/RPE 目标版本；记录目标客户端版本、谱面 sample、打包布局和每个事件字段的实际行为。
- 对 `META.offset` / `info.yml.offset` 语义用音频合成 click fixture + 导入测试确认，统一到 `time_mapping`，不要沿用没有验证的网络代码。
- 对不支持的新版本事件采取保守拒绝有损导出；更新 adapter 版本后增加新 golden fixtures。
