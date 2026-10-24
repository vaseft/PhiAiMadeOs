# 09｜RTX 5060 8GB + 16GB RAM：单机部署手册（2026-10-24）

## 0. 承诺边界

目标设备：**NVIDIA GeForce RTX 5060 8GB 显存，系统内存 16GB，Windows 主机**；也适用于具有同等显存/内存配置的笔记本，但不能假设实际可用显存完全相同。

- **可设计成在此机器上训练**：小型分阶段模型、短窗口、`micro_batch=1`、混合精度、梯度累积、CPU/Disk 特征缓存。
- **不能在没有目标机基准测试之前保证不 OOM、不爆内存、不出现驱动不兼容，更不能保证 500 首一定训出优质完整谱面。**
- 强制 `doctor → CUDA 反向传播 → 100 step 真实算子 profile → 真数据 1 epoch → 500 曲训练` 的门禁流程。未通过，不许报“支持 5060 已验证”。
- 官方 NVIDIA 规格中的桌面 RTX 5060 标准显存为 8GB： https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5060-family/
- PyTorch 2.7 起引入 Blackwell/CUDA 12.8 支持；安装二进制包须选择支持新 GPU 的 CUDA 发行版： https://pytorch.org/blog/pytorch-2-7/

## 1. 明确使用/不使用的技术

| 层 | 首版使用 | 为什么 | 首版不使用 |
|---|---|---|---|
| 主机操作系统 | Windows 11 + WSL2 Ubuntu 24.04 | 便于 Linux 训练与音频依赖 | 双系统/完整虚拟机 |
| 显卡驱动 | Windows NVIDIA 官方兼容驱动，主机安装 | WSL 透传 GPU | **不在 WSL 装 Linux NVIDIA 驱动** |
| CUDA | PyTorch 自带的 CUDA wheel（如 cu128），运行时验证 | 不要求手动装 CUDA Toolkit 来训练普通 PyTorch 代码 | 从源码构建 CUDA/PyTorch |
| Python | 3.12（Ubuntu 24.04）；用 venv 隔离 | 版本固定，可重复 | 混用系统 Python、Anaconda 全家桶 |
| 深度学习 | PyTorch + AMP + AdamW + safetensors | 适合小型模块模型 | 全参训练 7B/8B 语言模型、SDPA 外部加速扩展的强制依赖 |
| 音频解码 | ffmpeg/ffprobe、SoundFile | 支持常见音乐格式 | 浏览器作为训练数据解码器 |
| 传统分析 | NumPy、SciPy、librosa | CPU 预处理及非 AI 验谱 | 大型音乐理解 LLM；madmom 不作为必需依赖 |
| 聚类/运动原型 | scikit-learn，**仅离线 CPU** | 学习判定线模板字典 | 在 GPU 上跑聚类、边训练边聚类 |
| 服务 API | FastAPI + Uvicorn **单 worker** | 小内存本地服务 | Redis、Celery、Kubernetes、Docker 常驻栈 |
| 元数据 | SQLite + SQLAlchemy | 单机训练/审核版本管理 | PostgreSQL 常驻服务 |
| 前端 | Vue 3 + TS + Vite，Canvas/WebGL + WebAudio | 本地谱面播放器和人工评分 | Electron 大内存壳（首版） |
| 储存 | SSD 上的音频/谱面 + `.npy`/memmap 分片特征 + checkpoint | 流式训练 | 500 首原音频一次载入内存 |

其中 PyTorch `torchvision` **非必须**；`torchaudio` 首版亦非必须。避免装不需要的 GPU 库。

## 2. Windows 端部署（第一次）

1. 确认任务管理器显存确实是 **8GB**，内存 **16GB**；关闭游戏、浏览器大量标签、录屏程序等 GPU 常驻负载；避免边训练边用本地大模型推理。
2. 安装/更新 NVIDIA **Windows** 驱动；在 PowerShell 执行 `nvidia-smi`，查看显卡、驱动与其他占显存的进程。
3. 管理员 PowerShell 执行：

```powershell
wsl --install -d Ubuntu-24.04
wsl --update
wsl --status
```

若提示重启，按系统提示操作。Windows 10 部分版本也支持 WSL2，但首选 Windows 11。WSL CUDA 官方文档：https://docs.nvidia.com/cuda/wsl-user-guide/ 。

4. 控制 WSL 内存。16GB 主机先从 **9GB WSL RAM / 6GB SSD swap** 试起，Windows 留至少约 7GB 名义空间；这只是上限分配，不保证 Windows 真有 7GB 空闲。将下面内容存为 `%UserProfile%\.wslconfig`（不是 Linux 家目录）：

```ini
[wsl2]
memory=9GB
swap=6GB
processors=4
localhostForwarding=true
```

在 PowerShell 执行 `wsl --shutdown`，然后重新打开 Ubuntu。若 Windows 内存经常不足，可将 WSL 限制为 8GB，随后进一步缩小训练窗口并监控 Swap；不能一味增加 swap 来替代物理内存，换页会使训练非常慢。官方说明：https://learn.microsoft.com/windows/wsl/wsl-config 。

> 关键：WSL 不是「白送一套显存」。Windows 桌面和 WSL 训练共享物理 GPU；不要按 8GB + 8GB 计算可用显存。

## 3. Ubuntu/WSL 端部署

**代码和特征缓存放在 Linux 文件系统 `~/PhiAiMadeOs`，不要把大量随机读取的训练 cache 放在 `/mnt/c`。** 外部原音乐可以拷贝/导入到 Linux 文件系统。

```bash
sudo apt update
sudo apt install -y git ffmpeg libsndfile1 python3-venv python3-pip
mkdir -p ~/PhiAiMadeOs
cd ~/PhiAiMadeOs
# 将项目文件解压/拷贝到当前目录，此处不默认连接任何外部仓库
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

先安装明确支持 Blackwell 的 PyTorch CUDA wheel；下面是**经过官方发布列表确认的可复现示例**，不意味着必须永远锁定此版本：

```bash
python -m pip install "torch==2.9.1" --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements/base.txt
```

需要新的 Torch 版本时，按 `https://pytorch.org/get-started/locally/` 获取 Linux + pip + CUDA 官方安装指令，更新 lock 文件并跑完整兼容性测试，**不可同时装多个互不兼容的 CUDA Wheel 集合**。

再运行：

```bash
nvidia-smi
python scripts/diagnose_hardware.py --require-cuda
python scripts/benchmark_tiny_train.py --steps 100 --grad-accum 16 --max-vram-gb 6.2
```

结果会打印 GPU CUDA 信息、样例模型训练最大显存与峰值 RSS。**通过合成数据 profile 只意味着跑通这一规格的计算图**；必须继续完成真实音频数据窗口的一轮训练和峰值测试。

### 如果没有检测到 GPU

按顺序排查：Windows 驱动 → `wsl --update` → WSL 内 `nvidia-smi` → `torch.cuda.is_available()` → CUDA wheel `torch.version.cuda` → `torch.cuda.get_arch_list()` 是否覆盖 GPU 架构。`nvidia-smi` 中显示的 CUDA version 是**驱动支持上限**，不是当前 PyTorch 所带运行时版本；两者不要求字符串完全相等。不在 WSL 安装 Linux GPU 驱动。若算子报 `no kernel image available` / `sm_120 not compatible`，重新安装支持 Blackwell 的官方 CUDA wheel；不靠 CPU 回退伪装 GPU 训练成功。

## 4. 前后端运行（工程代码由 Codex 实现）

训练/特征提取应使用 CLI 或**独立子进程**；API 接到任务后只将作业写 SQLite 队列并启动有限并发 worker。独立 worker 加载 torch，常驻 API 不加载 GPU 模型。

```bash
# WSL 终端 A，已有代码后
source .venv/bin/activate
uvicorn phiaimadeos.api.main:app --host 127.0.0.1 --port 8765 --workers 1

# WSL 终端 B，项目 web/ 初始化并安装依赖后
cd web
npm install
npm run dev -- --host 127.0.0.1
```

Windows 浏览器打开 `http://localhost:5173`（使用 Vite 默认端口时；若被占用以终端输出为准）。训练时**可关闭前端和 API**节省系统内存；若必须保留 UI，禁止同时运行生成 worker 与训练 worker。

Node.js 选择当前受维护的 LTS（例如 22/24 系列），具体版本须在实现时写入 lock 文件。首版不要求 Node 与训练任务共享内存。

## 5. 部署容量与并发策略

| 资源 | 建议控制策略 |
|---|---|
| GPU 8GB | **训练 reserved 峰值目标 ≤6.2 GiB**（工程安全阈值，不能当物理保证）；运行前检查实时 free memory，余量不足时拒绝启动 |
| WSL 9GB RAM | Python 工作进程 RSS 目标 ≤5~6 GiB；1 个进程、DataLoader `num_workers=0`，避免多份数据副本 |
| Windows 16GB | 前端浏览器少标签、避免同时启用本地其他 AI 模型；如 Host 发生内存压力暂停训练 |
| SSD | 建议**至少留出 50GB 空间**，根据素材规模动态评估；音频不打包到 checkpoint |
| 常驻服务 | 单 API worker、训练独占 GPU、审计/播放器 CPU；训练和生成不可并行 |
| 特征缓存 | float16 存盘、按小窗口 memmap 加载；避免全数据 `np.stack` 到内存 |

换设备时重新做 GPU 预检与 100 step profile，不能把一次机器通过当作所有 RTX 5060 都通过。

## 6. 运行目录

```text
PhiAiMadeOs/
  data/raw/               # 获得许可的歌曲和原谱面
  data/normalized/        # 标准化事件 IR；保留来源 hash
  data/features/          # 音频及节拍特征分片, float16
  data/segments/          # 轻量元信息索引，不复制所有音频
  data/phiaimadeos.sqlite3
  models/registry/        # 各阶段独立 checkpoint
  runs/                   # metrics、显存和内存监控、profile
  exports/                # 经审核导出的 ZIP
  src/phiaimadeos/        # 服务+训练+审计源码
  web/                    # 前端
```

## 7. 交付状态标签

- `HARDWARE_UNTESTED`：未在用户的 RTX 5060 上执行。
- `CUDA_READY`：CUDA forward/backward 实际可用。
- `PROFILE_PASS`：指定的 100 steps 合成负载未溢出且显存/内存满足限额。
- `REAL_DATA_EPOCH_PASS`：真实数据 1 epoch 通过且无 OOM。
- `TRAINING_DONE`：真实训练、验证、checkpoint 加载测试完成。
- `CHART_PLAYTEST_PASS`：真实 Phira 导入及真人试玩确认。

这些状态独立存在，绝不能合并写成「已经保证模型训练成功」。
