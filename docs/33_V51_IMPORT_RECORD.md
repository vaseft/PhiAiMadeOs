# V5.1 原包导入记录

本次工作只整合用户已生成的完整 Agent 开发包及离线原型，并修复导入审查发现的缺陷。原包从关联会话的原下载入口取回，没有按聊天摘要重造源文件。

## 来源与覆盖范围

- 原 ZIP：`PhiAiMadeOs_PAMOs_V5_1_RPE_MCP_GitHub_Kit.zip`，215,933 字节。
- SHA-256：`0bffed618fc456d9fcac2400bbb59f72d98ad12499a53e53d215e1f483946494`。
- 共 96 文件；原 `MANIFEST.sha256` 列出其余 95 文件，95/95 哈希全部匹配。
- 原清单保存在 [imports/V51_SOURCE_MANIFEST.sha256](imports/V51_SOURCE_MANIFEST.sha256)，逐文件来源与整合目标见 [imports/V51_SOURCE_MAP.json](imports/V51_SOURCE_MAP.json)。这些哈希只验证原 ZIP，不是整合后工作树校验值；整合后的版本由 Git 追踪。
- 同批 Git Bundle 已取回，SHA-256 为 `3f11053488780e12256c1cfc0fdd085db7fb1898c60ad879d4f1e6a8828120d6`，所列初始提交为 `0d8ba29530f67437037682728769cec97ad653dc`。Bundle、内部历史及标签不导入现有仓库，避免引入未经审查的历史或替换远程提交。
- 从现有 `develop` 的 `6ad13fd4f2dfa6cd9dc79ad86828687ffa8f7f82` 建立 `feature/agent-v51-kit-import`；交付通过 PR 指向 `develop`，不直推稳定分支。

## 同名文件处理

- 保留现有根 `AGENTS.md` 的全部版本控制/安全规则，技术 Agent 整合到 `docs/AGENT_V51_DEVELOPMENT.md`；`docs/32_VERSION_CONTROL_POLICY.md` 保持不变。
- 保留根 `CODEX_START.md` 的交付流程，原技术执行清单迁至 `docs/legacy/CODEX_V3_START_HERE.md`；README 与 V5/V5.1 入口纠正旧的“无远端”和初始化直推说明。
- `.gitignore` 合并额外缓存/私有配置排除规则；CI 保留 `repository-safety`、`contract-tests` 名称，完整包导入后改为必跑契约及 stdio 测试。
- 保留现有 `LICENSE`；与原包 GPL v3 文本去除换行和末尾空白差异后相同。没有复制 rpe-next 源码；锁定上游的 PolyForm Noncommercial/GPL 许可边界保持。
- 未上传 ZIP、Git Bundle、`.git`、密钥、个人数据、模型权重、音频或社区原始谱面。唯一谱面夹具是原包的两音符合成 JSON，来源见 `fixtures/README.md`。

## 导入时的最小修复

- 候选提交重新核对源哈希与实际结果哈希是否匹配人工批准值；独占创建，拒绝覆盖已有候选。
- 固定 K 模式拒绝跨事件位置跳变，要求 K 个互异的显式列坐标，并拒绝不在列上的音符。
- ZIP 拒绝遍历、Windows 盘符/UNC/ADS、保留名称和歧义路径；保留正常中文相对路径。
- 保留原有 6 测试，增加审批竞态、候选防覆盖、固定 K 和字段保留回归；新增真实 SDK stdio 子进程测试。

## 实际验证与边界

本地环境：Windows、Python 3.12.14、mcp 2.3.0、jsonschema 4.26.0、PyYAML 6.0.3。依赖安装在仓库外的隔离环境；没有安装模型训练依赖或调用付费 API。

| 检查 | 结果 |
|---|---|
| `python scripts/validate_v3_contracts.py` | PASS：五种有效请求、负例及 Schema |
| `python scripts/validate_v4_contracts.py` | PASS：离线 Schema/示例/负例 |
| `python scripts/validate_v5_contracts.py` | PASS：MCP/提示词/GitHub 静态契约 |
| `python -m unittest discover -s tests -v` | 19 tests / OK：18 核心 + 1 stdio |
| stdio `tools/list` | 8 工具；读取/提议/校验/预览通过；未批准提交被拒绝，原文件保持 |
| 合成 JSON/PEZ → 候选 JSON → 重新读取 | PASS：未知字段、合成噪域保留；原输入不变 |
| 仓库 guard、差异空白与候选文件审核 | 提交前执行；远程结果见对应 PR checks |
| 原 RPE/RPE Next 完整双方言转换、PEZ 导出 | NOT RUN / 尚未实现 |
| 实时 RPE Next 编辑、完整非 AI DSP/几何审计、审核 UI | NOT RUN / 尚未实现 |
| RTX 5060 模型训练、峰值显存、Phira-Pro 试玩 | NOT RUN |

V4/V5 校验使用的 `jsonschema.RefResolver` 发出弃用提示，测试通过；迁移留待独立变更。stdio 测试中的未批准提交会在服务端记录预期拒绝异常，客户端确认错误且无候选写入。ZIP 尚无累计解压量/条目数预算；本地 CLI 批准不是对同用户任意磁盘写入的安全边界。

CI 必须在本次 PR 实际运行并核对；本记录中的本地结果不替代远程检查或人工审查。回退使用 PR 提交的 `git revert`，保留共享历史；本次没有修改用户谱面、模型或训练资产。
