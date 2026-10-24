# PAMOs 版本控制与发布规范（V1）

**生效范围**：GitHub 代码、谱面资产/人工反馈、机器学习实验及训练权重、提示词/API、上游格式适配。本规范是 `AGENTS.md` 的技术细则。

## 1. 仓库及分支
- 仓库：`vaseft/PhiAiMadeOs`，远端：`https://github.com/vaseft/PhiAiMadeOs.git`。
- `main`：只放经人工确认的发布或稳定里程碑；`develop`：可集成的工作基线；`feature/*`、`fix/*`、`docs/*`：从 `develop` 新建的短命分支。
- 缺省 PR 为 `feature/* → develop`；release 为 `develop → main`，不得直接重写 `main`。正式发布后把发布修复及时合回 `develop`。
- 单人开发也使用 PR，以保存审查、测试和讨论记录。避免长命特性分支；每个功能 PR 尽量可独立回滚。

示例：
```bash
git clone https://github.com/vaseft/PhiAiMadeOs.git
cd PhiAiMadeOs
git fetch origin
git switch develop
git pull --ff-only origin develop
git switch -c feature/rpe-next-bridge
# ... 实施修改，运行测试 ...
git status --short
git diff --check
git add AGENTS.md docs/ ...
git commit -m "feat(rpe): add revision-checked editor bridge"
git push -u origin feature/rpe-next-bridge
# 创建 PR 到 develop，待 CI 与人工检查后再合并
```

## 2. 提交、PR 与发布
- Commit 使用 Conventional Commits，scope 推荐 `model`/`data`/`rpe`/`mcp`/`ui`/`audit`/`llm`/`ci`/`agent`/`docs`。
- 每个 PR 必须包含：概要、受影响模块、文件结构变化、兼容目标、运行的测试及命令/结果、模型训练实测、变更风险、回滚路径。
- PR 状态：draft → ready → checks passing → reviewed → merged。CI 红灯或关键测试未运行时不得自动合并。
- GitHub Actions 初始流程只验证 **bootstrap**；完整训练与真实游玩不在 CI 内。严禁将静态检查通过写成“模型通过验收”。
- **GitHub Settings → Branches → Add branch protection rule / Rulesets**（需仓库管理员操作）：为 `main` 设置 PR 必需、状态检查必需（先确认检查实际出现且成功后再选）、阻止 force push、阻止删除；根据协作情况设置至少 1 人审查。为 `develop` 设置 PR + 必要检查。连接器未暴露规则操作时，Agent 仅提供操作说明，不得宣称已经开启保护。
- 版本采用 SemVer：`v0.1.0-alpha.1`（原型），`v0.1.0`（通过明示的验收门槛）。每个发布用 annotated tag、`CHANGELOG.md`、测试摘要与对应 commit SHA。只有用户授权后才进行稳定发布/标记。

## 3. RPE 版本控制与 Git 的边界
- Git 仓库追踪 **源代码、格式 Schema、测试夹具（自造或获授权的极小样本）、配置模板、文档**。
- 谱面编辑历史在 PAMOs 数据库或 RPE Next 自身的谱面版本库中，不会因为 Git commit 而自动上传。两者用 `project_git_sha`、`chart_revision_id` 与 `chart_sha256` 关联。
- 创建新谱面：`r0001`（原始模型输出）→ `r0002`（LLM patch 候选）→ `r0003`（人工批准后的更改）→ `r0004`（局部重生成），每一版不可变、可比较、可回退。**示例编号**，真正实现使用 UUID/ULID 或数据库主键，不只靠编号推断顺序。
- 后处理请求必须携带 `base_revision_id`、`expected_chart_sha256` 和改动范围。若任一不符，拒绝并要求重新读取，绝不覆盖用户新编辑的内容。
- RPE Next 扩展必须优先调用 `api.editor.commit(label, changedChart)`，保留编辑撤销；`await api.editor.save()` 报错不可吞掉；已导出的 ZIP/PEZ 是独立快照，不代表版本库已备份。
- 防止未知事件丢失：先 round-trip，再比对字段、事件时序、音符与噪域数据。首版 **噪域只读**；在兼容转换可能丢失噪域时直接拒绝无损导出，需显式标记有损操作，且不得改原件。

## 4. 训练实验/权重版本控制
每次训练的 `run_manifest.json` 至少记录：
```json
{
  "run_id": "20261024-note-demo-001",
  "status": "experimental",
  "project_git_sha": "<40 hex SHA>",
  "project_git_dirty": false,
  "dataset_manifest_sha256": "<sha256>",
  "split_manifest_sha256": "<sha256>",
  "feature_extractor_version": "mel-v1",
  "model_arch_version": "note-rhythm-v1",
  "train_config_sha256": "<sha256>",
  "seed": 42,
  "python_version": "<version>",
  "torch_version": "<version>",
  "cuda_version": "<version>",
  "gpu": "RTX 5060 8GB",
  "host_ram_gb": 16,
  "max_vram_gib_observed": null,
  "checkpoint_sha256": null,
  "metrics_path": "metrics.json",
  "audit_report_id": null,
  "human_review_id": null
}
```
上述是 **Schema 示例**，`null` 表示尚未测得，不能填想象中的性能指标。
- 数据按照 **歌曲/同源音频簇分组** 划分 train/val/test；不同难度谱面不可跨分组。
- 训练源音频/完整谱面与大体积 checkpoint 永不上传公开 Git。完整元数据在本地或有授权的私有工件库保存；只把经过匿名化审核、无路径泄露的指标摘要提交 Git。
- 配置、种子、解析器、特征提取器、依赖、权重哈希、数据拆分哈希组成可复现链；仅重跑同一命令不足以证明复现。
- `experimental`→`candidate`→`stable` 状态转移须有独立自动校验、真实音频生成和人工试玩记录。可保留上一稳定权重，实现一键回滚。

## 5. API、提示词、上游版本
- 大模型后处理的系统提示词、用户模板、JSON Schema、API 参数都必须入 Git。改动后提高 `prompt_version`/`schema_version`，对历史 patch 做兼容检查。
- 日志只记录 provider、模型名、模板版本、请求 ID 与脱敏统计；不得记录 API Key，也不默认上传受版权约束的完整音频。
- 适配器锁定上游 SHA（`Phira-Pro`、`rpe-next`）及许可证；升级走 PR，并对原 RPE/RPE Next 的兼容性用例回归。不得复制 `rpe-next` 的 PolyForm Noncommercial 源码到 GPL 仓库。
- 用例必须包括判定线父子关系、变速、不同 RPEVersion、RPE Next 噪域只读保留、4K/5K/6K 固定线、偏移、扩展字段。

## 6. 防误上传及事故恢复
- 在 `.gitignore` 之外加 CI/提交前检查：秘钥扫描、超大文件扫描、扩展名黑名单、模型及训练资产路径检测。
- 不要把个人/客户训练数据、音频、原始谱面直接推至 GitHub；确有授权的公开小测试夹具需在 `fixtures/` 声明来源。
- 意外泄露 Key：先撤销轮换；再用合规历史清理流程通知协作者。历史重写涉及远端仓库，**必须事先征得用户确认**，不可单方面 force push。
- 代码回退用 `git revert <sha>` 创建新提交，不改写共享分支历史。
- 谱面回退创建新的指向旧内容的审计记录，不删旧评分。
- 模型回退更新 active registry 指向上一 stable 版本，保留关联的训练 manifest。
- 删除大文件、修改许可证、发布模型权重、授权状态不明时，暂停自动发布并请用户确认。

## 7. 工作完成的报告格式
```text
分支: feature/...
提交: <SHA>
Pull Request: <URL 或“未创建+原因”>
变更: <文件及功能>
测试: <命令、通过/失败/NOT RUN>
硬件: <RTX 5060 上真实测得数值，或 NOT RUN>
部署/兼容: <已验证格式/客户端，或 NOT RUN>
可回滚版本: <revision/model version/commit SHA>
剩余问题: <明确列出>
```

本文件是开发流程规范，不保证现有代码已经实现相关能力。
