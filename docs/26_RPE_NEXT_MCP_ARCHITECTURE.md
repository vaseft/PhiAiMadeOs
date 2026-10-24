# 26 — PAMOs RPE 编辑 MCP 与编辑器桥接架构

## 26.1 已核实的上游事实（2026-10-24）
- `kclg-YSJ/rpe-next` README 当前说明版本 **0.12.2**，可导入原 RPE，能选择 **RPE Next / 原 RPE × JSON / PEZ** 四种导出组合；格式转换不一定完整，作者建议保留备份。
- `protocols/MOD-PROTOCOL.zh-CN.md` 定义 API 1：扩展包采用 `.rpenmod`，`activate(api)`，编辑器 API 包含 `api.editor.chart`、`commit(label,chart)`、`save()`、`seekBeat()`、`beginPreviewSession()` 等；`schemas/mod-api-v1.d.ts` 给出类型。可用于自建 PAMOs Bridge 模组。
- 经当前 README、已知协议及 package.json 查验，**未确认上游提供现成 MCP Server**。因此以现有稳定 API 1 构建 **PAMOs 自有 MCP Server + 本地 Bridge + 编辑器模组**。执行期必须再审计锁定 commit；如果以后上游真的添加 MCP，重新做能力探针并经人工批准再替换。
- rpe-next 非 GPL：使用 PolyForm Noncommercial 1.0.0。不要把其源码、资源或发布包直接纳入 PAMOs GPL 分发。首选独立编写的互操作适配器，使用公示的模组协议；单独部署原项目时须遵守许可证和 NOTICE。

## 26.2 运行架构
```text
Codex / 其他 MCP Client (本机)
         │ JSON-RPC / MCP stdio
         ▼
  pamos-rpe-mcp  ←—— 工具调用鉴权/白名单/日志/预算
         │ localhost HTTP / WS（仅 PAMOs 内部）
         ▼
  PAMOs Backend & Revision Store  ←—— Tensor 模型候选 / DSP / LLM patch
         │ 命令队列，版本号，pairing
         ├─── 文件适配器（原 RPE JSON/PEZ；Next JSON/PEZ）
         │
         ▼
  PAMOs RPE Next Bridge（可选实时编辑）
         │ 本地 WS；Origin 与 token 双重限制
         ▼
  RPE Next 0.12.2 pinned + 自建 `pamos-rpe-bridge.rpenmod`
         │ `api.editor.commit(...)` → `api.editor.save()`
         ▼
  RPE Next 画面与时间轴 / 预览 / 撤销

目标测试运行时 Phira-Pro pinned commit（独立应用）
```

**不要**直接让云模型访问浏览器调试端口、文件系统或 GitHub token。大模型读到的是经过授权且被裁剪的谱面片段；MCP server 是受控工具面。

## 26.3 操作顺序（强制）
1. `rpe_capabilities`：读取 RPE adapter/runtime 可用能力、支持的事件和 pinned SHA。
2. `rpe_list_projects` / `rpe_open_project`：只能打开用户明确允许的本地工作目录/当前编辑器项目。原始文件只读备份。
3. `rpe_get_segment`：取指定 beat 窗口，可附带传统 DSP、线轨迹与 warning refs；固定响应上限，分页。
4. `rpe_propose_patch`：创建不可执行候选 PATCH。仅白名单 Note/Line 操作；噪域 `noise_areas/blockAreaList` 完全不可写。
5. `rpe_validate_patch`：严格 schema、mode/K、父线、时间、几何、预算、不可修改字段、基线 hash 校验；成功返回 validation id。
6. `rpe_preview_diff`：可视化预览、缺陷定位和音频同步。无需修改编辑器正式存档。
7. `rpe_commit_patch`：必须携带 `validation_id`、当前 chart revision、用户 approval；否则拒绝。创建 PAMOs candidate revision，触发**正式非 AI 审计**；硬错误回滚；通过时才在编辑器用 `editor.commit` 形成撤销点。
8. `rpe_save_project`：editor commit 后需等待 `editor.save()`，检查竞态版本号与 dirty state；保存失败不得说成功。
9. `rpe_export_project`：按格式明确能力，默认保留 Next 特性，不准有损静默转换；导出再导入校验；Phira Pro 试玩单独验证。
10. `rpe_revert_revision`：从不可变原始候选恢复，保留差异、审计与评分历史。

**MCP 工具不是无条件写入权限**。Codex/LLM 本地应用工具也必须通过 revision compare-and-swap、校验、审批、审计。

## 26.4 双版本 RPE adapter
- `rpe_original`: 离线读取/写入原版 JSON/PEZ；验证 Note、判定线、BPM、META、offset 等原版字段；支持项目转换后送 RPE Next 编辑。首版**不承诺控制旧版 RPE 桌面程序窗口**。
- `rpe_next`: 读取/写入 Next JSON/PEZ；RPE Next only 事件、shader、噪域、轨迹、模组字段采用 `opaque_extensions` 保真。
- 核心 `ChartIR v5` 采用稳定 ID 和 beat 有理数，不用浮点秒作为唯一时间主键；保留原版时间元信息、层级、父线/坐标、源格式、完整未知字段并校验哈希。每次导入、变更、导出要有双向 snapshot/diff。
- next → original：可转换部分根据上游兼容转换路径生成导出副本。**噪域存在时**默认 `BLOCK`，如人工明确选择有损导出，另存副本并生成删除字段清单；此类有损副本不回写训练数据或覆盖原文件。
- original → next：可以尝试导入，但对未知 easing/fake/alpha/纹理/持久层保留内容并显示兼容警告；不能声称双向无损。
- 文件包先做 zip-bomb、路径遍历、恶意 MIME、资产引用和重名检查；不得自动解压到库外。

## 26.5 活编辑器模组规范
- 在独立 `PAMOs Bridge` 包中实现 `mod.json` + `main.mjs`；使用 `activate(api)` 和 `api.editor.commit`、`save`、`seekBeat` 等已经文档化 API，避免直接修改 `editor.raw.chart`。
- 模组是编辑器内**高权限 JavaScript 代码**，没有安全沙箱，且可能访问编辑器所有数据。只允许人工审查过的本地源码、手动导入、手动启用；禁止自动远程注入或启用。
- 模组与 PAMOs 使用 loopback、一次性配对码、随机 token、严格 Origin、同用户权限、短时效、命令序号 + 过期时间；会话关停即撤销；写操作要二次确认。
- 若浏览器对 HTTPS 页面请求 localhost WS 存在 mixed-content / private-network / CSP 等问题，**优先使用 `npm start` 启动本地 RPE Next (默认 127.0.0.1:4173)**，不要绕过浏览器安全策略。
- 在 PAMOs 后端先执行完整 patch 验证，经过签名的 `validated_patch` 才进入模组；模组再校验 base revision 和 payload，禁止全量替换未确认内容。已存在编辑器未保存修改时禁止覆盖，需先保存或进入分支。
- `api.editor.commit('PAMOs: <revision>', newChart)` 后再 `await api.editor.save()`；`save` 过程中有并发编辑则只能标记需要再保存，不可误报。commit/保存/联机操作分别记录结果。
- 原 RPE 的“Live 编辑”如无可验证官方 API，不使用 OCR/鼠标模拟假装 MCP 操作；使用安全的离线 JSON/PEZ 再导入。

## 26.6 与训练/LLM 的接口
PAMOs 小模型输出候选 → 可选 LLM patch 生成（`prompts/LLM_CHART_REFINER_SYSTEM_ZH.md`）→ PAMOs 本地批准/校验 → MCP 送入编辑器 → 正式 DSP/几何审计 → 人工评分 → Phira Pro 验证。低显存 5060 不运行第二个本地大模型，后处理走外部 API 时显式同意。

## 26.7 探针及失败策略
运行期间记录 `rpe_next_git_sha`、`bridge_version`、`phira_pro_git_sha`、`original_format_version`、`capabilities`、`feature_probe_hash`。任何工具不支持、桥断线、修订冲突、schema 不符、噪域写入请求、版本漂移都 fail closed。没有实际 Live bridge 的测试记录时 UI 标记 `RPE MCP LIVE: NOT_CONNECTED`，不能标记“已连通”。
