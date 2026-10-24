> **V3 优先级提示（2026-10-24）**：本文件是 v2 通用基础说明。**纯配置模式是固定判定线的真实 4K/5K/6K，不是风格倾向**；新增的条件训练、模式分流、异常演出能力限制与按模式评分请以 `docs/12..18` 为准。若本文与 V3 冲突，以 V3 为准。

# 07｜测试矩阵、基线与真实验收

## 0. 新增 5060 硬件门禁（先于真实训练）
- 在目标 RTX 5060 + 16GB RAM 系统运行 `scripts/diagnose_hardware.py --require-cuda`，必须完成 CUDA forward/backward 并记录 device/SM、torch/CUDA/驱动。
- 按 `configs/rtx5060_8gb.yaml` 运行 `scripts/benchmark_tiny_train.py` 100 个 optimizer steps，报告 reserved/allocated GPU 峰值、Python RSS、耗时；engineering budget 显存 ≤6.2 GiB、RSS ≤6 GiB（均需真机核验，且允许更严格的实时 free memory 检查）。
- 训练数据最长样本窗口再进行 1 epoch 真数据 profile，检测意外峰值；G0/G1 只是兼容性测试，不是质量保证。
- 本文件规范的任何功能未在目标机实测，则显示 `UNTESTED`。

## 1. 金标准 fixtures

必须制作合成且无版权争议的测试素材（用纯音频合成节拍 click/空白/不同频率 tones）；RPE/PHIRA 包可由代码生成：

1. 120 BPM、4/4、正拍纯 Tap，1 拍 = 500ms。
2. 180 BPM + 120 BPM 两段 BPM 变化，跨变化的 Hold、独立旋转事件。
3. 3/4、1/3/1/5 分拍事件，非 2 次幂分音。
4. `META.offset` 和 `info.yml.offset` 正负方向差异（须通过当前客户端源码/实机证实规则）。
5. 多条线 `father`、移动+旋转+透明度+速度叠加、分层事件、缓动曲线、同线重叠事件。
6. 四种 Note type 编码、上下侧、FakeNote、Hold、相同时间多押。
7. 无声前奏、长静音、延迟起音、不规则节奏、半拍/倍拍候选。
8. 非法 ZIP 路径、zip bomb、NaN、BPM=0、倒序 Hold、父线循环、事件越界、缺音乐。

## 2. 时间与渲染准确性

- 对 120 BPM fixture，beats `[0,1,2,3,4]` 的 chart time 必须 `[0,.5,1,1.5,2]`（无 offset）。
- 任意多 BPM 正常样本 `beat->seconds->beat` 误差 < 1e-6 beat（float 表示允许合理误差，内部采用有理数/高精度计算）。
- Round-trip 前后 note 数量、类型和 ID 映射、关键音符绝对音频时间偏差在预设阈值内（首期目标 < 1ms）；RPE 不支持保留原始 ID 时用稳定内容哈希对齐。
- 前端预览与 Python 几何求值在 golden timepoints：位置相差 < 1 像素或明确的 scale-aware tolerance，方向/alpha 相等。注意屏幕宽高适配。
- 相同 seed+模型+输入音频/config 条件下，推理逻辑可复现；不同设备浮点或随机内核可容忍轻微输出差异，必须记录可重复模式参数。

## 3. 非 AI 审计测试

对合成 click-track + 完美对齐谱面：`BLOCK=0`，节拍时间差合理。对整体移动 +100ms，输出持续 offset WARN 和异常分布。对故意静音位置新增 80 个 Tap，给出密度/静音风险 WARN（不能将单个静音中的演出 note 误判 BLOCK）。对合法反拍、弱起、无鼓演奏、长 Hold、同拍双押，**不得单纯因 onset 不对应而 BLOCK**。对 NaN、父线循环、缺文件必须 BLOCK。

测试期间 monkeypatch 注入任何模型推理调用到 audit namespace，必须失败；audit 的依赖不得包括模型 checkpoint 读取 API。测试误报率要按**真实授权高质量谱面**计算并在报告里记录，阈值尚未校准前只显示实验性。

## 4. 模型真实训练与评估

- 使用合成数据只能标记 `pipeline_smoke_test`，不能标记 `trained_on_real_charts`。
- 在真实授权训练样本存在时，观察 loss 有限、参数实际更新、checkpoint 恢复后继续优化、验证曲目未见过、非训练歌曲可以推理。
- 参照 `docs/03_MODEL_TRAINING.md` 的 E0-E5 消融，按 song-group 计算指标；脚本必须检查 split 无重叠。
- Note 简单全预测 Tap/一线静止的模型应因类别塌缩与目标功能不达标而被标记 experiment，而非 stable。
- 几何校验与 RPE round-trip 必须独立于模型质量通过。

## 5. UI E2E

1. 新建生成候选 → 非 AI 审计输出 3 条 WARN。
2. 打开预览，按播放可在同一 `AudioContext` 时钟播放音乐和画面。
3. 点击 WARN 自动跳至对应秒数、支持放慢/暂停/拖动。
4. 六项评分、在 54.2 秒标记“判定线遮挡”、点击退回，数据库存一条不可变 review。
5. 选择 50–58 秒区域局部再生成 → `candidate_v2`，v1 的审计及评分不变；v2 再审计。
6. v2 人工批准并导出→ZIP 解包有根目录 info.yml/chart/music/illustration，内部路径正确，谱面能再导入；实机未验不得显示“试玩已通过”。

## 6. 真实验收口径

| 层次 | 满足什么 | 不可宣称什么 |
|---|---|---|
| `FORMAT_VALID` | JSON/ZIP 可解析、关键事件 round-trip | 音乐好听、谱面可玩 |
| `AUDIT_PASS` | 非 AI 结构+DSP+几何规则检查完成且无 BLOCK | 手感优质、没有其他错误 |
| `HUMAN_APPROVED` | 人在播放器中检查并完成评分 | 已经在 Phira 实机通关 |
| `PLAYTEST_CONFIRMED` | 真人实际在 Phira 成功导入、游玩并提交记录 | 所有玩家都会觉得谱面好 |

报告必须提供 build hash、Phira 客户端版本、测试设备、测试音频哈希、谱面哈希和 issue 清单。没有证据就表述为“未验证”。
