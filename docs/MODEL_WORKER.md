# 本地学习式模型工作进程

本页描述实现契约；本地数据准备及真实初训的独立记录见 [数据准备流程](LOCAL_TRAINING_PREPARATION.md)。所有训练产物默认 `experimental`，完成优化不等于模型可玩或已经过验收。推理、恢复与客户端验收须分别报告，不能从训练结果推断。

## 入口与隔离

- `training.run_training(request, project_root, progress)`：请求字段为 ADR 0001 的 `manifest_path,stage,epochs,seed,grad_accum,device,resume_run_id?`，另接受 worker 的 `job_id` 与可选 `max_lines`（64/128/512，默认64）。返回包含 `run_id,training_state,models,bundle` 的 JSON 对象。
- `inference.generate_learned(analysis, conditions, bundle, project_root, progress=None)`：返回 RPE chart，`pamos` 保存权重哈希、训练 run、特征哈希、条件哈希、种子和约束修复记录。
- `progress` 接收单个 JSON dict，含 `phase,progress,message`；训练登记后尽早报告 `run_id`。
- 导入这些模块不导入 torch。只有独占 worker 调用训练、推理或模型工厂时才导入 torch。GPU互斥和取消进程由 root worker 负责，三个阶段不会同时驻留 GPU；纯配置始终旁路线运动阶段。

## 模型与目标

`models.py` 实现 192 维、4头、两层音频 Transformer；Note decoder 四层，Line/Placement decoder 各三层，FFN 768。输入是传统 DSP 的104维、25Hz特征；不下载或安装大型音频编码器。

架构版本为 `pamos-transformer-192-v2`，旧 v1 权重不能直接加载。主干宽度、层数与音频窗口保持不变。41维条件向量保留模式、K、难度类别与数值、独立演出强度和狂野度、风格、优先级，以及缺失标签掩码。训练允许 canonical 难度类别/数值同时缺失，独立编码 `conditions.source_level` 对象中的 `source_difficulty_class` 与原始小数 `source_difficulty_value`（含各自掩码），不舍入或回写原标签。源类别支持 EZ/HD/IN/AT/SP/Legacy/BND，未知类别为缺失；数值仅作连续来源观测。生成入口仍必须提供规范范围内的整数难度。常规与纯配置有不同放置目标；4K/5K/6K head 对超过 K 的类别做掩码。条件标签缺失不能通过猜测歌曲难度补齐。

- Note：32个连续时间单元，每单元6个事件槽，共192槽；学习事件存在、Tap/Hold/Drag/Flick、连续时间残差、log Hold持续时间及纯K列辅助目标。未强制吸附到节拍网格，6个槽可表达同时多押或单元内不同时间。
- Line：默认学习1..64条线，可显式配置128或512线；所有线归属、父线和上下文归一化使用同一容量。父线采用32维 query/key 因子化头及拓扑掩码，避免增加一个512×513×192参数的全连接头。运动槽为判定线容量×5，默认320槽，能够表达47条线五种属性同时初始化；不扩大192维主干。Placement上下文最多包含同容量的当前事件与每线五种属性的延续状态。128/512是可配置表达能力，不表示已通过8GB显存实测；运行仍受6.2GiB峰值reserved门限约束。
- Line学习事件的存在/所属线/事件类型/缓动/裁切缓动边界/持续时间/起止值。仅在训练歌曲拟合最多64个运动端点原型；每类事件的8192条reservoir仅限制原型拟合内存，全部有效音频域内事件仍参与监督。原型混合加连续残差重建端点，原始来源、缓动及边界分别保留。
- Placement：学习自由线归属、X、上下侧、速度、Y偏移，或独立固定K列；自由音符X统一用 `POSITION_X_SCALE=1350` 归一化并写入模型配置，保留局部坐标超出±675但仍在±1350内的有效音符。推理反归一化、局部占用距离和候选修复边界使用同一尺度；纯配置列中心仍使用原675半宽，判定线运动坐标的独立尺度也不改变。损失包含分类、回归与局部同时占用的软约束。

第二/三阶段目前以真实上游标签训练；整曲推理使用预测上游。误差累积、模式/难度/风格控制强度尚未验收；未实现联合优化或将人工评分伪造为音符标签。

## 数据拒绝与拆窗

manifest 所有使用样本须为 `license_status=explicit_permitted` 且 `allowed_actions` 字符串数组包含 `training`。来源标签只记录出处，不自动授予许可；批量导入仍默认 unknown，仅在用户明确确认训练授权后另行登记本地证据。对齐须人工确认，或有绑定当前原谱/转换谱/音频哈希与素材ID的游戏导出来源、时钟和音符范围检查记录；后者不等于人工听音，human标志保持false。模型只读取 manifest 中的相对路径；拒绝越界路径、未授权数据、噪域、同歌跨 split、缓存/谱面哈希不符和特征版本混用。`chart_file_sha256` 校验文件字节，`chart_sha256` 可校验规范化谱面；训练记录二者。实际训练不打开测试集文件，测试集指标不用于调参；数据准备在分配拆分前进行全库适配检查。

必须有独立的 train 与 val 歌曲簇。使用单歌曲解析缓存和 NPY mmap，按歌曲打乱并在曲内打乱窗口。窗口上限为384帧、192音符槽、`5*max_lines`线事件；超过容量或每时间单元超过6事件时递归拆窗并报告 `additional_splits`。Hold以起点归属窗口，持续时间不因窗边界丢失。无法进一步表达的同时事件明确失败，不删标签。窗口索引用排序时间数组与二分查询，线状态按属性缓存，避免每窗反复扫描整首烘焙事件。

`audio-domain-exact-easing-bpm-v2` 训练投影不改原谱：音频域为 `[0,特征帧数/25)`；负时间和歌曲结束后的事件保留源JSON指针与源文件SHA，通过来源报告解释其有效域。跨域事件在边界精确计算端点，保留原 easing 及其子区间；跨BPM边界再拆段，使段内秒数与拍数成线性关系。开始前事件的延续状态、全在未来事件在歌曲开始时的初值均显式建立边界状态。相同起点被后项覆盖和交叠被新事件接管均按渲染时序记录来源，不能当成静默清洗。窗口上下文继续精确求值与裁切，监督仍引用音频域内原事件片段。退化而无法等价表示的裁切缓动明确拒绝，不用线性代替。音符一份也不裁，域外音符仍明确拒绝。`song.training_projection` 与 `build_windows` 每谱报告保存操作、来源指针、投影版本及哈希，可在本地准备产物与运行manifest中审阅。

当前有意拒绝：异像/特殊机制、假音符、超过所选线容量、多运动层、扩展颜色/纹理/UI绑定、贝塞尔、linkgroup、非1的bpmfactor、域外音符、歌内有限显现/透明度/音符缩放目标。纯配置需单条静止无父线、真列标签、上侧/零音符偏移/音符速度1；静线Y与滚动速度可为恒定值，不错误要求其为0或1。被拒绝的源文件不会修改。

## 优化、验证与记录

基准microbatch1、累积16、AdamW、warmup+cosine、梯度裁剪1。用户要求调优后，可使用本机校准的8×2或16×1等档位；同曲窗口掩码合批、逐窗损失归一、有界CPU预取和运行批量变更约束见 [吞吐调整](40_TRAINING_THROUGHPUT.md)。CUDA优先BF16，否则FP16+GradScaler；CPU为FP32。损失在FP32计算；非有限损失或梯度立即失败。尾部按实际窗口数归一。三个阶段串行训练，阶段间释放模型与优化器。

验证 loss 先在各歌曲簇内求平均，再对歌曲簇求平均；只有该真实验证loss用于best checkpoint和patience8早停。日志中的loss并非可玩性评分。当前实现不宣称提供已验收的时间容差F1、各类型召回、几何质量、客户端成功率、基线对比或冻结测试集结果；这些评测仍需补齐并实际执行。

每个优化器步写真实损失分量、累积窗数、学习率、裁剪前梯度范数、GPU allocated/reserved/peak 和进程 RSS。超过6.2GiB reserved 或6GiB当前RSS会停止并记录；这些是运行时门限，不保证5060上不会OOM。记录Git SHA/dirty、实现文件哈希、Python/torch/CUDA/驱动/架构、manifest/拆分/输入内容/配置/原型字典/权重哈希、seed、特征版本和解析器版本。没有测量的字段保持null。

## 磁盘产物与恢复

产物位于 `data/training/<run_id>/`：

```text
run_manifest.json
metrics.jsonl
note_rhythm/weights-<step>-<nonce>.pt
note_rhythm/resume-<step>-<nonce>.pt
line_motion/...
placement/...
```

JSON、权重、完整状态采用临时文件、flush/fsync与原子重命名。checkpoint使用CPU tensor和普通dict/list/tuple/标量，不保存自定义类或可执行对象；读取一律 `torch.load(weights_only=True)`，不使用`weights_only=False`。权重与恢复文件都先校验安全路径和SHA。恢复状态包含optimizer/scheduler/scaler、Python/NumPy/torch/CUDA随机状态、epoch、打乱后的窗口序列与下一窗位置；只在完整优化器步保存，不在半个累积批次恢复。

初始状态、每50个优化器步与每轮末保存恢复点；完整状态文件以不可变名称写入，再原子更新manifest引用，最后仅清理本阶段的上一恢复点。best权重保留，避免破坏旧registry的引用。恢复可以增加epochs；其他配置、输入和拆分须保持一致，配置/环境变化历史单独记录。

失败写 `training_state=failed`；worker强制取消时可能保留 `running`，应结合其`job_id`在工作台显示cancelled/interrupted。最末原子断点可供恢复。请求在授权或标签预检阶段拒绝时没有创建run，错误由job保存。单阶段训练不会虚构完整bundle能力；只有各必需阶段都有train/val模式覆盖才列入bundle支持模式。

## 推理约束与剩余验收

缺权重、架构/特征版本不符、阶段未完成或SHA不符返回 `MODEL_UNAVAILABLE`；模型预测空谱返回 `GENERATION_EMPTY`，不会用规则填成学习结果。整曲音频分窗依次执行Note、Line、Placement，保留连续时间和全曲尾部。

确定性修复会记录越界投影、运动事件重复/交叠/边界连续性处理，以及音符局部占用投影。纯K按模型列排序选可用列，全部列被Hold占用时明确失败；常规按预测线排序与邻近X位置解除局部冲突，失败不删音符。Hold必须有正持续时间且尾部在歌曲内。没有预测的线属性使用静态渲染默认值并显式标注，不能称为已学会该运动。复杂父线变换与运动过程的屏幕碰撞由独立非AI审计判定。

本轮遵照用户要求不新增或主动运行测试，也不运行合成profile。真实训练及从完整/部分完成阶段续训的实际路径见 [第2轮记录](39_SECOND_EPOCH.md)，资源按实际日志报告；全面异常/跨环境恢复回归、整曲模型推理、RPE/Next往返和Phira-Pro试玩仍 **NOT RUN**。candidate/stable提升继续要求独立审核与人工验收。
