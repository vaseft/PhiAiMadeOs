## 目标与关联问题
<!-- 说明本 PR 解决什么；可关联 issue -->

## 变更内容
<!-- 具体文件/模块/行为，说明是否更改公开 API、Schema、提示词或上游依赖 -->

## 兼容与授权
- [ ] 不含训练音频、原始社区/官方谱面、密钥或模型权重
- [ ] 没有未经授权复制 rpe-next（PolyForm Noncommercial）源码
- [ ] 如修改 RPE 适配，已记录上游 SHA、保留未知字段并检查噪域只读限制
- [ ] 如修改 4K/5K/6K，确保固定判定线不动

## 测试（填写运行命令和结果）
- 单元 / Schema：
- RPE 格式 round-trip：
- LLM/MCP patch 版本冲突与回滚：
- 实机 RTX 5060 8GB 显存：PASS / FAIL / NOT RUN（测量值）：
- Phira-Pro 真实试玩：PASS / FAIL / NOT RUN：
- CI 链接：

## 影响范围与回滚
- 代码回滚 commit：
- 谱面/模型版本回滚方式：
- 潜在风险及未完成事项：

## 文档与发布
- [ ] 已更新 AGENTS/文档（若涉及开发约束）
- [ ] 已更新 CHANGELOG.md 的 Unreleased
- [ ] 不把“计划”或静态检查描述成“功能已实现”
