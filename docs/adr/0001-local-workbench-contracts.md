# ADR 0001：本地工作台与模块契约

用户本轮要求完成测试以外能落地的工作。本轮不新增或主动运行测试；保留既有 CI。产品功能代码、打包和启动可以执行，所有尚未验收能力标记 NOT RUN，不自动合并未验证的新功能 PR。

## 边界

源代码 `src/phiaimadeos/`，Vue 3 + TypeScript 界面 `web/`。FastAPI 绑定 127.0.0.1:8765，单 worker；长任务通过独立 Python 子进程，SQLite WAL 保存状态，GPU 任务进程锁互斥。音乐、谱面、特征、权重、数据库与日志始终在被忽略的本机数据目录。

## 共享数据接口

- 所有记录均使用随机 `id` 和 UTC `created_at`；本机路径只接受后端生成的安全相对路径，不接受客户端任意文件路径。
- MusicAsset：`id,name,path,sha256,duration_s,sample_rate,channels,license_status,allowed_actions,analysis_path`。
- ChartAsset：`id,name,path,sha256,music_asset_id,chart_mode,key_count,difficulty_class,difficulty_value,license_status,allowed_actions,source_type,warnings`。
- Candidate：`id,music_asset_id,chart_mode,key_count,conditions,chart_path,chart_sha256,manifest,status,parent_id,audit_id`。chart 文件不可变，修改、回滚均创建新候选 ID。
- 许可状态 `explicit_permitted/restricted/unknown`；允许动作 `local_research/training/distribution` 分开保存。模型训练只读人工明确允许 training 的数据。没有训练权重时只提供标识清楚的 baseline_only 生成入口。
- IR：`schema_version,chart_mode,key_count,bpm_map,offset_ms,duration_s,notes,judge_lines,raw_payload,warnings`。note：`id,line_id,kind,beat,end_beat,time_s,end_time_s,x,above,fake,lane_index,raw`；拍数保持 `[whole,numerator,denominator]`，秒数仅派生。line：`id,parent_id,raw`。
- 数据集 manifest：`id,version,created_at,sha256,samples`；sample：`chart_id,music_asset_id,chart_path,feature_path,group_id,split,conditions,allowed_actions`。文件路径相对项目根；feature NPY `[frames,104]`，采样率 22050Hz，hop 882（25Hz），按歌曲簇分组划分。

## Python 模块接口

- `formats`：`read_chart(path)->dict`、`chart_to_ir(chart,chart_mode='regular',key_count=None)->dict`、`ir_to_chart(ir)->dict`、`beat_to_seconds(beat,bpm_map)->float`、`seconds_to_beat(seconds,bpm_map)->list`、`make_chart(notes,bpm,duration_s,conditions)->dict`、`export_package(chart,music_path,output_path,metadata,illustration_path=None)->dict`。未知字段保留，噪域禁止修改，无法无损转换时返回明确限制。
- `audio`：`probe_audio(path)->dict`、`analyze_audio(path,cache_dir,progress=None)->dict`。返回 `feature_path,waveform_path,onsets_s,bpm,beat_times_s,duration_s,sample_rate,feature_version,warnings`；只用传统 DSP，无 torch，分块处理音频。
- `baseline`：`generate_baseline(analysis,conditions)->dict` 返回 RPE chart；pure_keys 真正静线固定 K，普通模式可生成受控线运动，噪域不生成。
- `audit`：`audit_chart(chart,analysis=None,conditions=None)->dict` 返回 `status: BLOCK/WARN/PASS,issues,metrics,engine_version,chart_sha256`，无模型依赖。issue 含 `severity,code,message,time_s,note_id,line_id`。
- `dataset`：`build_manifest(samples,output_dir,seed=42)->dict`；不得同源歌曲跨 split，不支持输入明确报告，不能静默删除标签。
- `training`：`run_training(request,project_root,progress)->dict`。请求 `manifest_path,stage:note_rhythm/line_motion/placement/all,epochs,seed,grad_accum,device,resume_run_id?`。输出真实训练 run/model metadata，默认 experimental；checkpoint 与完整日志本地保存。只在 worker 中 import torch。
- `inference`：`generate_learned(analysis,conditions,bundle,project_root,progress=None)->dict`，分阶段加载模型，pure_keys 跳过 LineMotionNet。
- root 提供 `settings.py` 的 `get_settings()` 与 `Settings.root/data_dir`；`store.py` 的 `Store.put(kind,record,immutable=False),get(kind,id),list(kind),update(kind,id,changes)`。record/metadata 统一为 JSON dict。模型模块可直接通过 manifest 加载，不依赖 API。

## UI / API 契约

`GET /api/v1/session -> {csrf_token}`。同源 API 请求加 `X-PAMOS-Token`；上传 multipart，其他写操作 JSON。GET 音频/下载使用 same-origin HttpOnly 会话 cookie。客户端不存储 API Key，不连接远程资源。

- `GET /api/v1/status -> {version,counts,hardware,jobs,capabilities}`。
- `GET /api/v1/assets -> {items}`；`POST /api/v1/assets/music` multipart `file,license_status,allowed_actions(JSON string)`。
- `POST /api/v1/imports/chart` multipart `file,music_asset_id?,chart_mode,key_count?,difficulty_class,difficulty_value,license_status,allowed_actions`；JSON 或安全 ZIP/PEZ。
- `GET /api/v1/charts -> {items}`。
- `GET /api/v1/models -> {items}`。
- `GET /api/v1/capabilities -> {modes,special_features,live_bridge}`。
- `POST /api/v1/generation-conditions/normalize` 按已有 GenerationRequest Schema，返回 `{effective_conditions,overrides}`。
- `POST /api/v1/generations` 标准条件请求，返回 `{job_id}`。
- `GET /api/v1/jobs -> {items}`、`GET /api/v1/jobs/{id}`；`POST /api/v1/jobs/{id}/cancel`。
- `GET /api/v1/candidates -> {items}`、`GET /api/v1/candidates/{id}` 元数据；`GET /api/v1/candidates/{id}/timeline?start_s=0&end_s=30 -> {notes,judge_lines,bpm_map,offset_ms,duration_s,chart_mode,key_count}`；`GET /api/v1/assets/{id}/audio`；`GET /api/v1/assets/{id}/waveform -> {peaks,duration_s}`。
- `POST /api/v1/candidates/{id}/audit -> {job_id}`；`GET /api/v1/candidates/{id}/audit`。
- `POST /api/v1/candidates/{id}/reviews`：`reviewer,scores:{rhythm,playability,readability,expression,difficulty,completeness},decision:approved/revision_requested/rejected,comment,annotations:[{time_s,text}]`；六项上限25/25/20/15/10/5，必须真人填分。
- `GET /api/v1/candidates/{id}/history -> {versions,reviews}`；`POST /api/v1/candidates/{id}/revert` 创建新 revision。
- `POST /api/v1/candidates/{id}/proposals`：`expected_chart_sha256,operations,beat_window`；`GET /api/v1/proposals/{id}`；`POST /api/v1/proposals/{id}/approve` 显式按钮批准；`POST /api/v1/proposals/{id}/commit` 新候选并重审计。
- `POST /api/v1/candidates/{id}/exports`：`purpose:local/distribution,include_audio:true` -> `{id,download_url}`，需同版本审核通过且无 BLOCK；`GET /api/v1/candidates/{id}/chart` 允许下载标注未审核的 JSON 草稿。
- `POST /api/v1/candidates/{id}/playtests`：`reviewer,engine_version,platform,passed,notes`；不得自动登记试玩。
- `POST /api/v1/datasets`：`chart_ids,seed` -> `{job_id}`；`GET /api/v1/datasets -> {items}`。
- `POST /api/v1/training/runs`：`dataset_id,stage,epochs,seed,device,grad_accum` -> `{job_id}`；`GET /api/v1/training/runs -> {items}`；`POST /api/v1/models/{id}/promote` 需要人工证据，禁止自动 stable。
- LLM 设置与 postprocess、bridge 配对/状态独立路由实现，默认禁用，不发送音频或完整曲库。

接口错误统一 `{detail:{code,message,...}}`。UI 禁止将计划/空结果展示成成功；未提供有效数据/权重时显示明确原因。工作台资源由本机静态构建提供，无 CDN、埋点或外部字体。
