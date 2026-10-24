# Windows 本地开发环境

本次在用户指定的 `E:\PhiAiMade` 部署原生 Windows 环境。代码基于 V5.1 导入分支，环境工作使用 `feature/windows-environment-setup`；原导入 PR #2 尚未合并，不能把本地就绪理解为 develop 已更新。

## 使用

双击项目根目录 `Open-PAMOs-Dev.cmd`，在打开的终端运行：

```bat
python scripts/diagnose_hardware.py --require-cuda
python scripts/check_audio_environment.py
python scripts/validate_v3_contracts.py
python scripts/validate_v4_contracts.py
python scripts/validate_v5_contracts.py
python -m unittest discover -s tests -v
```

在已有 CMD 中执行 `call scripts\environment.cmd` 也可启用。脚本只改变当前终端的环境变量，不改系统 PATH。Python、FFmpeg、临时文件、下载缓存、模型缓存和 MCP 本地工作目录均落在项目目录下。

`Open-RPE-Next.cmd` 启动锁定版本的参考编辑器并打开本机页面 `http://127.0.0.1:4173`。关闭它的终端会停止服务；这只是独立编辑器，不表示 PAMOs 已实现实时桥接。

## 目录

| 目录 | 内容 |
|---|---|
| `.venv/` | 项目 Python 虚拟环境 |
| `.runtime/python/` | uv 管理的独立 Python 3.12 |
| `.tools/uv/` | uv 环境管理工具 |
| `.tools/ffmpeg/` | FFmpeg/ffprobe 完整发布包及其许可证 |
| `.downloads/` | 已下载的安装文件和依赖轮子 |
| `.cache/` | uv、音频 JIT、PyTorch 等本地缓存 |
| `.local/charts/` | 默认的空 MCP 本地数据目录 |
| `.local/upstreams/` | 锁定版本的只读参考源码检出 |
| `runs/` | 诊断、测试、安装记录和合成负载报告 |

这些本机目录均排除 Git。用户音乐、谱面和训练权重只在本地管理；没有真实训练数据时不下载或伪造模型权重。

## 安装来源与版本

- Python 3.12.15：Astral uv 管理的 CPython；uv 0.13.5 来自 PyPI。Python 安装使用 `--no-bin --no-registry`，没有注册系统 Python 或替换已有版本。
- PyTorch 2.9.1 + CUDA 12.8：项目已约定的起始基线，下载源为 `https://download.pytorch.org/whl/cu128`，固定在 `requirements/torch-cu128.txt`。普通 PyTorch 使用其自带运行时，不额外安装 CUDA Toolkit。
- CPU/DSP/API/MCP：按 `requirements/base.txt`、`contracts.txt`、`mcp_v51.txt` 安装。实际非 Torch 版本保存为 `requirements/windows-py312.lock.txt`；完整本机 freeze 保存在忽略的 `runs/pip-freeze.txt`。
- FFmpeg/ffprobe 9.0.2 essentials：Gyan 的发布镜像 `GyanD/codexffmpeg`，下载资产 `ffmpeg-9.0.2-essentials_build.zip`；SHA-256 为 `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`，安装前已校验。
- RPE Next 与 Phira-Pro 源码 SHA 服从 `configs/upstreams.lock.json`，独立存放在 `.local/upstreams/`；没有复制进 PAMOs 的公开源码，也没有改动上游。RPE Next 网页模式只需要已有 Node.js，不安装其可选 Electron 打包依赖。
- 已有 Git 和 Node.js 直接使用；付费 LLM API、可选音频大模型与额外训练素材未启用。

在新的同类 Windows 机器上，用 uv 安装 Python 3.12 并创建 `.venv` 后，安装顺序为：

```bat
uv pip install --python .venv\Scripts\python.exe -r requirements\torch-cu128.txt
uv pip install --python .venv\Scripts\python.exe -r requirements\windows-py312.lock.txt
uv pip check --python .venv\Scripts\python.exe
```

不要直接搬运 `.venv` 到另一个路径；应重新创建环境。FFmpeg 和上游源码按上述发布版本、哈希和 lock 单独恢复。

## 验证边界

本机实测（2026-10-24）：

| 检查 | 结果 |
|---|---|
| RTX 5060 Laptop GPU / 驱动 592.54 | CUDA 前后向成功，`sm_120`，支持 BF16 |
| 100 optimizer steps，累积 16，microbatch 1 | PROFILE_PASS，47.53 秒 |
| 3,395,526 参数，音频帧 384，Note 槽 192，d_model 192，decoder 4 层 | reserved 峰值 0.096GiB，allocated 0.089GiB，RSS 1.443GiB |
| FFmpeg → FLAC → SoundFile → librosa 80-bin mel | AUDIO_STACK_PASS，22050Hz，mel 形状 80×44 |
| V3/V4/V5 契约及 MCP 回归 | 全部通过，19 tests / OK，含真实 stdio 子进程 |
| FastAPI、SQLAlchemy、SQLite、safetensors、SciPy、scikit-learn | 导入及 SQLite 内存数据库检查通过 |
| 依赖一致性 | 75 个已安装包兼容；73 个非 Torch 包版本入锁 |
| 独立 RPE Next 网页服务 | 本机 HTTP 200，随后停止测试服务 |

这些是该小型合成配置的结果，不能外推到更大模型、完整歌曲或真实数据集。

`runs/environment.json` 的 `CUDA_READY` 表示实际 GPU 前后向成功；`runs/gpu_profile_synthetic.json` 的 `PROFILE_PASS` 只表示指定的 100 步合成计算图满足显存/RSS 上限。音频测试仅使用临时生成的一秒正弦波。完整 MCP 测试使用合成夹具，不读取用户曲库。

真实数据一轮训练、模型质量、完整双方言转换、实时 Bridge 和 Phira-Pro 真人试玩仍需分别验收。WSL 当前无 Linux 发行版，本次不依赖它；未来切换 WSL 时必须新建 Linux 环境并重新跑硬件和负载检查。
