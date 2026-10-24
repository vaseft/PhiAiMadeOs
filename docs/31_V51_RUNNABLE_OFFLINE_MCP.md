# PAMOs V5.1：可运行的离线 RPE MCP 最小纵向切片

**状态（本次导入验证）**：原包 6 项测试保留，修复后离线核心共 18 项测试通过；另有 1 项真实 stdio 子进程测试通过，验证 8 个工具、读取/提议/校验/预览，以及拒绝未获批准的提交。本地环境为 Windows、Python 3.12.14、`mcp==2.3.0`。与 rpe-next 的**实时模组桥接尚未实现**，绝不可将其标成已连接。详细范围见 `33_V51_IMPORT_RECORD.md`。

## 目标与边界
- 源码 `pamos_mcp/core.py` 独立开发，不复制 rpe-next PolyForm-NC 源代码。
- 兼容当前已确认的**共同 RPE JSON 结构**：`META`, `BPMList`, `judgeLineList`, `notes`, `eventLayers`；接受 JSON / PEZ (ZIP) 文件输入。**不宣称两种方言的无损格式转换**。
- 只允许 5 个明确 Note PATCH 操作：`SHIFT_NOTE_BEATS`（不超过 1/8 beat）、`SET_NOTE_X`（非纯 K）、`SET_NOTE_TYPE`（非 Hold 三类间）、`SET_HOLD_END`、`MOVE_NOTE_LANE`（必须提供明确的 `PAMOs_lane_positions`，不能猜测列位置）。
- `pure_keys` 校验固定线、拒绝父线及扩展移动和变换、跨事件位置跳变；读取时必须提供数量等于 K 且互异的显式 `PAMOs_lane_positions`。`noise_area`/`blockAreaList` 是只读数据，不能写。
- 源文件只读，提交后仅写 `.pamos_state/candidates/*.json` 候选；**没有执行完整 DSP 审计、几何审计或 Phira-Pro 试玩**，标记 `STRUCTURAL_ONLY`。
- PEZ 导入仅作**谱面 JSON 抽取**；该 MVP 不导出 PEZ（媒体不会神奇地随 JSON 一起导出）。
- 用原始文件 SHA256 作 CAS revision。每次 PATCH 依照 `READ→PROPOSE→VALIDATE→PREVIEW→USER_APPROVE→CANDIDATE_COMMIT` 流程。
- 批次最多 12 条，禁止额外 PATCH 字段、路径遍历与 ZIP 非法路径。

## 开始使用
```bash
cd /path/to/PhiAiMadeOs
python -m venv .venv
# 激活 .venv 后
python -m pip install -r requirements/mcp_v51.txt
python -m pip install -r requirements/contracts.txt
python -m unittest discover -s tests -v
# macOS/Linux/WSL2
export PAMOs_RPE_WORKSPACE=/absolute/path/to/your/authorized_charts
python -m pamos_mcp.server
```

运行 stdio 后，进程由 MCP 宿主控制；在终端看不到普通聊天界面。把 `configs/codex_mcp_v51.example.toml` 中的路径换为本机真实绝对路径，添加至 Codex 配置并重启相应 MCP 连接。正确连接应能通过 `tools/list` 看见 `rpe_capabilities` 等 8 个工具。本次测试使用临时目录中的合成夹具，没有接入个人谱面目录或配置用户的常驻 MCP 服务。

Windows PowerShell 直接运行时：
```powershell
$env:PAMOs_RPE_WORKSPACE = 'D:\\PAMOsCharts'
python -m pamos_mcp.server
```

示例 PATCH（先从 `rpe_open_project` 获取 revision）：
```json
{
  "project_id":"test.json",
  "expected_revision":"<open_project revision>",
  "chart_mode":"pure_keys",
  "key_count":4,
  "operations":[{"op":"MOVE_NOTE_LANE","note_ref":"l0:n0","value":2}]
}
```
需要谱面内（用于演示的）`PAMOs_lane_positions`；实际编辑时必须通过谱面预览 + 显式轨道映射替代此演示字段，避免数据格式污染。以 `rpe_preview_diff` 检查原始和变更。然后由**真人在独立交互终端**执行：
```bash
python -m pamos_mcp.approve --workspace /absolute/path/to/your/authorized_charts --proposal <proposal_id>
```
根据终端提示完整输入 `APPROVE <proposal_id>`，之后才可由 MCP 客户端调用 `rpe_commit_patch`，它创建**新的候选**，不会修改原始谱面。CLI 的本地授权只保证不会被只持有 MCP 工具的模型跳过；并非对拥有任意本地命令执行和同用户文件读写权的攻击者建立安全边界。生产版必须接入 PAMOs UI 的会话级安全审查与身份鉴别。

## 功能尚欠缺
0. 当前 ZIP 输入仅用于有授权的本地文件，已有压缩包和单 JSON 大小限制，尚无累计解压量/条目数预算，不能称为完整的不可信归档沙箱。
1. 使用已核实的 `rpe-next` Mod API 1 实现 `.rpenmod` 插件，并使其仅从受控本地后端取得已审计 patch，调用 `api.editor.commit` → `await api.editor.save()`；当前 `LIVE_EDITOR_NOT_CONNECTED`。
2. 为**原 RPE / Next 格式**实现真正格式化往返和安全 PEZ 导出；目前只有通用 RPE 结构的无损 JSON 保留，不是双方言转换器。
3. 非 AI DSP/几何审计、波形同步预览、人工打分、Phira-Pro 可玩性验收。
4. 真实 5060 GPU 训练与已训练模型接入（当前只有 Agent 蓝图和小型压力测试脚本）。
5. 依据有权运行的两种 RPE 版本及测试样本做 golden tests，锁定上游 commit 与许可证。

## 兼容事实与许可证
2026-10-24 核对 `kclg-YSJ/rpe-next`：README v0.12.2，支持 RPE Next / 原 RPE × JSON / PEZ 导出；Mod API 1 文档在 `protocols/MOD-PROTOCOL.zh-CN.md`，`src/core/chart.mjs` 普通 Note 类型是 `1=Tap,2=Hold,3=Flick,4=Drag`。`rpe-next` 的 `package.json` 声明 PolyForm Noncommercial 1.0.0；本工具源代码按 GPL-3.0 发布前须完成许可审核，不能直接复制 Next 源码到 GPL 工程。

## 固定上游版本（2026-10-24 读取 GitHub）
`configs/upstreams.lock.json` 已记录：
- RPE Next commit `740fe7ebaa04506f26fdec4e37794f97da1fcf4d`
- Phira-Pro commit `4ed6aaf6b844cfe59c9122a068f3fe5411553936`

这只是源码参照锁定，不构成与上述两版本的实机通过证明，后续需要 CI fixture/客户端验证。
