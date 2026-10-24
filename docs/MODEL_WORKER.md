# 本地学习式模型工作进程

本页描述本轮写入的实现，训练、推理、恢复、GPU峰值与客户端试玩均为 **NOT RUN**。没有生成权重、训练日志或评测数字；以下文件在用户随后实际启动训练时才会产生。所有训练产物默认 `experimental`，完成优化不等于模型可玩或已经过验收。

## 入口与隔离

- `training.run_training(request, project_root, progress)`：请求字段为 ADR 0001 的 `manifest_path,stage,epochs,seed,grad_accum,device,resume_run_id?`，另接受 worker 的 `job_id`。返回包含 `run_id,training_state,models,bundle` 的 JSON 对象。
- `inference.generate_learned(analysis, conditions, bundle, project_root, progress=None)`：返回 RPE chart，`pamos` 保存权重哈希、训练 run、特征哈希、条件哈希、种子和约束修复记录。
- `progress` 接收单个 JSON dict，含 `phase,progress,message`；训练登记后尽早报告 `run_id`。
- 导入这些模块不导入 torch。只有独占 worker 调用训练、推理或模型工厂时才导入 torch。GPU互斥和取消进程由 root worker 负责，三个阶段不会同时驻留 GPU；纯配置始终旁路线运动阶段。

## 模型与目标

`models.py` 实现 192 维、4头、两层音频 Transformer；Note decoder 四层，Line/Placement decoder 各三层，FFN 768。输入是传统 DSP 的104维、25Hz特征；不下载或安装大型音频编码器。

条件向量保留模式、K、难度类别与数值、独立演出强度和狂野度、风格、优先级，以及缺失标签掩码。常规与纯配置有不同放置目标；4K/5K/6K head 对超过 K 的类别做掩码。条件标签缺失不能通过猜测歌曲难度补齐。

- Note：32个连续时间单元，每单元6个事件槽，共192槽；学习事件存在、Tap/Hold/Drag/Flick、连续时间残差、log Hold持续时间及纯K列辅助目标。未强制吸附到节拍网格，6个槽可表达同时多押或单元内不同时间。
- Line：学习1..8条线、父线DAG、64个事件的存在/所属线/事件类型/缓动/边界/持续时间/起止值。仅在训练歌曲拟合最多64个运动端点原型；每类事件的8192条reservoir仅限制原型拟合内存，全部原事件仍参与监督。原型混合加连续残差重建端点，原始缓动与边界分别保留为目标。Placement的线条件包含最多64个当前事件加40个延续状态token，保留缓动和边界。
- Placement：学习自由线归属、X、上下侧、速度、Y偏移，或独立固定K列；损失包含分类、回归与局部同时占用的软约束。

第二/三阶段目前以真实上游标签训练；整曲推理使用预测上游。误差累积、模式/难度/风格控制强度尚未验收；未实现联合优化或将人工评分伪造为音符标签。

## 数据拒绝与拆窗

manifest 所有使用样本须为 `license_status=explicit_permitted` 且 `allowed_actions` 字符串数组包含 `training`。来源标签只记录出处，不自动授予许可；用户提供的官谱库默认仍为 unknown 且无 training 权限。模型只读取 manifest 中的相对路径；拒绝越界路径、未授权数据、噪域、同歌跨 split、缓存/谱面哈希不符和特征版本混用。`chart_file_sha256` 校验文件字节，`chart_sha256` 可校验规范化谱面；训练记录二者。测试集文件不打开，测试集指标不用于调参。

必须有独立的 train 与 val 歌曲簇。使用单歌曲解析缓存和 NPY mmap，按歌曲打乱并在曲内打乱窗口。窗口上限为384帧、192音符槽、64线事件；超过容量或每时间单元超过6事件时递归拆窗并报告 `additional_splits`。Hold以起点归属窗口，持续时间不因窗边界丢失。无法进一步表达的同时事件明确失败，不删标签。

当前有意拒绝：异像/特殊机制、假音符、超过8线、多运动层、扩展颜色/纹理/UI绑定、贝塞尔或裁切缓动、非1的bpmfactor、负音频时间运动、音频结束后才开始的事件、歌内有限显现/透明度/音符缩放目标。纯配置需单条静止无父线、真列标签、上侧/零音符偏移/音符速度1；静线Y与滚动速度可为恒定值，不错误要求其为0或1。被拒绝的源文件不会修改。

## 优化、验证与记录

默认 microbatch1、累积16、AdamW、warmup+cosine、梯度裁剪1。CUDA优先BF16，否则FP16+GradScaler；CPU为FP32。损失在FP32计算；非有限损失或梯度立即失败。尾部不足16窗按实际数量归一。三个阶段串行训练，阶段间释放模型与优化器。

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

本轮仅完成源码静态语法解析和人工契约复查。测试、合成profile、真实训练/恢复、整曲模型推理、RTX5060峰值、RPE/Next往返和Phira-Pro试玩均 **NOT RUN**。没有产生任何可选择的训练完成权重或candidate/stable模型。
