# Codex：从 PhiAiMadeOs/PAMOs V5.1 继续

先阅读 `AGENTS.md`、`CODEX_START.md`、`docs/32_VERSION_CONTROL_POLICY.md`、`docs/AGENT_V51_DEVELOPMENT.md`，再读 `CODEX_V5_START_HERE.md`、`V5_1_CHANGELOG.md`、`docs/31_V51_RUNNABLE_OFFLINE_MCP.md`。根 Agent 和版本控制规范优先，历史版本说明是技术背景。继承所有 RTX 5060 8GB/16GB、纯配置固定 4/5/6K、噪域首代禁止生成、LLM API 仅局部 patch、传统 DSP 检验+人工审核、Phira-Pro 兼容等要求。

当前分支已导入**离线** MCP 最小核心 `pamos_mcp/core.py` 与 stdio wrapper `pamos_mcp/server.py`。本次在 Windows / Python 3.12 / `mcp==2.3.0` 下运行 `tests/test_stdio_mcp.py`：真实 stdio 子进程列出 8 个工具，open/propose/validate/preview 通过，未经批准的 commit 被拒绝且源文件未变。重新验证时按 `requirements/mcp_v51.txt` 安装 SDK 并安装 Schema 依赖，再执行 `python -m unittest discover -s tests -v` 和 V3/V4/V5 合约。SDK 通信通过不代表 Live Bridge、目标硬件训练或真实客户端验收通过，这些仍为 `NOT RUN`。

下一步按门禁完成：
1. 从上游 `kclg-YSJ/rpe-next` 锁定 Git SHA；核验 README / MOD-PROTOCOL API 1 / schema、PolyForm-NC 许可；只引用公开契约，不复制源码到 GPL 产品。制作 PAMOs 自研 `.rpenmod` + 仅回环地址的受控本地桥。
2. Bridge 通过 PAMOs 运行时鉴权、CAS/审批 + 传统 DSP/几何/格式审计后，调用 `api.editor.commit()`；仅在 editor 实际成功 `await api.editor.save()` 才返回 `SAVED`；必须测可撤销/保存后重开，断线返回 NOT_CONNECTED。
3. 实现原 RPE 和 Next JSON/PEZ 双适配器，不许静默有损；含噪域拒绝 Next→原版无损导出，首代 AI 不编辑噪域。
4. 添加审计信息、人工评分和 Phira-Pro 实际游玩证据。未运行 5060 GPU 训练不得说训练成功。
5. 核实当前 Git 工作区、分支和 `origin` 与用户目标 `https://github.com/vaseft/PhiAiMadeOs.git` 一致；不得重新初始化或覆盖既有提交。基于最新 `develop` 建立 `feature/*`，小步提交并 PR 到 `develop`，保留已有远程改动。任何提交前检查歌曲、谱面、密钥、权重和个人数据未被追踪；CI、分支保护、推送和 PR 状态均以实际查询结果为准。

如需 API LLM 后处理继续沿用 `prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`；MCP 编辑器使用 `prompts/PAMOS_RPE_MCP_EDITOR_SYSTEM_ZH.md`，提交操作绝不能跳过人工批准。
