# 本地工作台界面

Vue 3 / TypeScript / Vite。仅依赖本地 `/api/v1` 服务；没有 CDN、远程字体、埋点或浏览器凭据持久化。

## 开发与打包

在 `web/` 中执行：

```powershell
npm ci --cache E:\PhiAiMade\.cache\npm
npm run dev
npm run build
```

开发服务固定为 `127.0.0.1:5173`，`/api` 代理到 `127.0.0.1:8765`。生产构建使用相对资源路径，输出 `dist/`，由 FastAPI 提供同源页面。`node_modules/` 和 `dist/` 不追踪到 Git；锁文件固定依赖版本。Vue、Vite、Vue 插件、vue-tsc 为 MIT，TypeScript 为 Apache-2.0。

## 模块

- `api.ts`：同源会话、CSRF token、统一可见错误、安全下载地址。
- `state.ts`：本机资源、串行轮询、防重复提交和提示。
- `pages/`：条件生成、素材许可、人工审核、数据集与训练、可选 LLM 与 RPE 连接。
- `components/ChartPreview.vue` / `timeline.ts`：音频唯一时钟、分页时间轴、Canvas 固定 K / 动态线、波形与定位。
- `components/ProposalPanel.vue`：局部修改 / 外发摘要确认、真实差异、人工批准与新版本提交。

评分初始为空，密钥仅保存在页面与服务进程内存。审核草稿在切换工作台页签时保留在当前浏览器会话内，离开审核页会暂停音频。外部 API 请求只在明确确认后交给本地服务发送；界面不直接调用供应商。

## 交付界限

本轮只进行依赖安装和生产构建，不新增、运行测试，不进行浏览器、GPU、真实训练、RPE 编辑器或 Phira-Pro 验收（NOT RUN）。生产构建通过不等于功能验收通过。

浏览器预览参考本项目独立几何与时间映射实现，处理双 offset、bpmfactor、普通标量事件、父线变换和公开缓动。预览的音符滚动速度为参考值；复杂速度积分、纹理、扩展控制曲线与目标客户端仍可能有差异。自动演示不登记真人试玩。
