<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { state, label, perform, refresh, activeJob, short, date } from '../state'
import { alignmentLabel, groupLabel, trainingGroup, difficultyLabel, trainingBlockers } from '../trainingReadiness'
import type { RecordData } from '../types'
const selected = ref<string[]>([]), seed = ref(42)
const training = reactive({ dataset_id: '', stage: 'all', epochs: 10, seed: 42, device: 'cuda', grad_accum: 16, microbatch: 1, prefetch_batches: 0, allow_runtime_batch_change: false, resume_run_id: '' })
const runtime = ref({ microbatch: 1, grad_accum: 16, prefetch_batches: 0, source: 'baseline' })
function applyRuntime() {
  const previous = state.runs.find(r => (r.run_id || r.id) === training.resume_run_id)
  const effective = previous ? (previous.config?.microbatch || 1) * (previous.config?.grad_accum || 16) : 16
  const batch = [16, 8, 4, 2, 1].find(value => value <= runtime.value.microbatch && effective % value === 0) || 1
  Object.assign(training, { microbatch: batch, grad_accum: effective / batch, prefetch_batches: runtime.value.prefetch_batches, allow_runtime_batch_change: !!previous })
}
onMounted(async () => {
  try { runtime.value = await api('/training/runtime') }
  catch {
    try { const response = await fetch('/assets/training-runtime.json', { cache: 'no-store' }); if (response.ok) runtime.value = await response.json() }
    catch { /* Keep baseline when neither calibrated source is available. */ }
  }
  if (!training.resume_run_id) applyRuntime()
})
function audioFor(chart: RecordData) { return state.assets.find(asset => asset.id === chart.music_asset_id) }
const eligibility = computed(() => state.charts.map(chart => ({ chart, reasons: trainingBlockers(chart, audioFor(chart)) })))
const eligible = computed(() => eligibility.value.filter(item => !item.reasons.length).map(item => item.chart))
const blocked = computed(() => eligibility.value.filter(item => item.reasons.length))
const cachedAssets = computed(() => state.assets.filter(asset => !!asset.analysis_path).length)
const preparedCharts = computed(() => state.charts.filter(chart => chart.training_readiness?.status === 'ready').length)
const preparationJobs = computed(() => state.jobs.filter(job => ['audio_prepare', 'dataset_prepare'].includes(job.kind || '')).slice(0, 3))
watch(eligible, charts => { const available = new Set(charts.map(chart => chart.id)); selected.value = selected.value.filter(id => available.has(id)) })
const gpuBusy = computed(() => state.jobs.some(j => activeJob(j) && /train|generat|infer/.test(j.kind || j.type || '')))
const chosenRun = ref(''), evidence = ref(''), promotion = ref('candidate')
const promoteModel = ref('')
const run = computed(() => state.runs.find(r => r.id === chosenRun.value || r.run_id === chosenRun.value))
watch(() => training.resume_run_id, id => {
  if (!id) { training.allow_runtime_batch_change = false; applyRuntime(); return }
  const r = state.runs.find(r => (r.run_id || r.id) === id)
  if (!r?.config) return
  const d = state.datasets.find(d => d.id === r.dataset_id || d.manifest?.id === r.dataset_id || d.sha256 === r.dataset_manifest_sha256)
  training.dataset_id = d?.id || ''
  training.stage = r.config.stage || 'all'
  training.epochs = r.config.epochs || 10
  training.seed = r.config.seed ?? r.seed ?? 42
  training.grad_accum = r.config.grad_accum || 16
  training.microbatch = r.config.microbatch || 1
  training.prefetch_batches = r.config.prefetch_batches || 0
  training.allow_runtime_batch_change = false
  training.device = String(r.config.device || 'cuda').startsWith('cuda') ? 'cuda' : 'cpu'
})
function toggleAll() { selected.value = selected.value.length === eligible.value.length ? [] : eligible.value.map(c => c.id) }
async function createDataset() { await perform('dataset', async () => { await api('/datasets', 'POST', { chart_ids: selected.value, seed: seed.value }); await refresh() }, '数据集构建已加入任务队列，将按同源歌曲分组划分。') }
async function startTraining() { await perform('training', async () => { const { resume_run_id, ...request } = training; await api('/training/runs', 'POST', { ...request, ...(resume_run_id ? { resume_run_id } : {}) }); await refresh() }, '真实训练任务已加入队列，结果默认为实验权重。') }
async function promote() { await perform('promote', async () => { await api(`/models/${promoteModel.value}/promote`, 'POST', { status: promotion.value, evidence: evidence.value }); await refresh() }, '模型状态请求已由本地服务处理，请核对注册表中的实际状态。') }
function points(values: number[]) { const min = Math.min(...values), max = Math.max(...values); return values.map((v, i) => `${20 + i / Math.max(1, values.length - 1) * 580},${130 - (v - min) / Math.max(.000001, max - min) * 100}`).join(' ') }
const loss = computed(() => { const src = run.value?.loss_history || []; return Array.isArray(src) ? src.map((x: any) => Number(typeof x === 'object' ? x.loss ?? x.train_loss : x)).filter(Number.isFinite) : [] })
</script>
<template>
  <div class="page-heading"><div><p class="eyebrow">DATA → LEARNING → EVIDENCE</p><h1>从有授权的数据，开始学习。</h1><p class="subtitle">按歌曲分组构建数据集，再按阶段训练小模型。训练结束不等于通过真人验收。</p></div><span class="badge outline">顺序训练 · 本地保存</span></div>
  <section class="panel">
    <div class="panel-heading"><div><p class="section-kicker">训练准备</p><h2>以实际记录核对准备进度</h2></div><span class="badge outline">元数据核对与人工听音分别记录</span></div>
    <div class="audit-counts"><span><strong>{{ cachedAssets }} / {{ state.assets.length }}</strong> 音频已登记特征缓存</span><span><strong>{{ preparedCharts }} / {{ state.charts.length }}</strong> 谱面已完成训练适配检查</span><span><strong>{{ eligible.length }}</strong> 当前可选样本</span></div>
    <p class="small-text muted">游戏导出样本可依据原始包元数据和文件哈希核对音乐绑定；这不代表已经人工听音。自动歌曲分组与人工分组分别保留，同源不同难度放在同一拆分组。特征缓存和文件完整性在构建数据集时再次检查。</p>
    <p v-for="job in preparationJobs" :key="job.id" class="soft-callout"><strong>{{ label(job.kind) }} · {{ label(job.status || job.state) }}</strong><br>{{ job.message || '请到任务中心查看实际进度' }}</p>
  </section>
  <div class="training-top-grid"><section class="panel">
    <div class="panel-heading"><div><p class="section-kicker">01 / 数据集</p><h2>选择有训练依据的素材</h2></div><span class="badge blue">{{ eligible.length }} 张符合条件</span></div>
    <p class="small-text muted">音乐与谱面都需明确允许训练，有有效的音乐绑定证据与歌曲分组。目标难度可成对留空；来源小数级别独立保留，不自动舍入，也不填造整数标签。</p>
    <div class="dataset-select">
      <label class="checkbox select-all"><input type="checkbox" :checked="selected.length === eligible.length && !!eligible.length" :disabled="!eligible.length" @change="toggleAll"><strong>选择全部符合条件的谱面</strong></label>
      <label v-for="c in eligible" :key="c.id" class="checkbox sample-row"><input v-model="selected" type="checkbox" :value="c.id"><span><strong>{{ c.name }}</strong><small>{{ label(c.chart_mode) }} {{ c.key_count ? `${c.key_count}K` : '' }} · {{ c.source_level || '原始级别未提供' }} · {{ difficultyLabel(c) }}</small><small>{{ alignmentLabel(c, audioFor(c)) }} · {{ groupLabel(c, audioFor(c)) }} {{ short(trainingGroup(c, audioFor(c))) }}</small><small>{{ audioFor(c)?.analysis_path ? '特征缓存已登记，构建时复核' : '音频特征待准备' }} · {{ c.training_readiness?.status === 'ready' ? '训练适配检查已完成' : '训练适配由后端终检' }}</small></span></label>
      <div v-if="!eligible.length" class="empty small"><span class="empty-icon">▧</span><strong>还没有符合条件的训练样本</strong><p>查看下方逐项原因；许可、音乐绑定和歌曲分组需要有效依据，仅存档资料不能加入训练。</p></div>
    </div>
    <div class="form-grid"><div class="field"><label>分组随机种子</label><input v-model.number="seed" type="number" min="0" max="4294967295" step="1"></div><div class="field end-field"><span class="muted small-text">已选择 {{ selected.length }} 张谱面</span><button class="button primary" :disabled="!selected.length || state.busy.dataset" @click="createDataset">构建数据集版本</button></div></div>
    <details v-if="blocked.length"><summary>{{ blocked.length }} 张谱面尚有训练阻塞</summary><p class="small-text muted">下列原因来自当前许可、绑定、分组和训练适配记录。目标难度未标注本身不阻塞训练；对应条件使用掩码，不从小数级别猜测。</p><div class="dataset-select"><div v-for="item in blocked" :key="item.chart.id" class="sample-row"><strong>{{ item.chart.name }}</strong><p class="small-text warning-text">{{ item.reasons.join('；') }}</p></div></div></details>
  </section>
    <section class="panel"><div class="panel-heading"><div><p class="section-kicker">02 / 真实训练</p><h2>每次只推进一个阶段</h2></div></div><div class="field"><label>数据集版本</label><select v-model="training.dataset_id" :disabled="!!training.resume_run_id"><option value="" disabled>选择构建完成的数据集</option><option v-for="d in state.datasets" :key="d.id" :value="d.id">{{ d.name || short(d.id) }} · v{{ d.version || 1 }} · {{ d.samples?.length ?? d.sample_count ?? '未知' }} 样本</option></select></div><div class="field"><label>训练起点</label><select v-model="training.resume_run_id"><option value="">从头开始新的训练记录</option><option v-for="r in state.runs" :key="r.id || r.run_id" :value="r.run_id || r.id">续训 {{ short(r.run_id || r.id) }} · {{ label(r.training_state || r.status) }}</option></select><p class="field-hint">续训只使用后端确认有效的本地 checkpoint；阶段、数据集和配置兼容性由服务检查。</p></div><div class="field"><label>训练阶段</label><select v-model="training.stage" :disabled="!!training.resume_run_id"><option value="note_rhythm">阶段 1 · 音符与节奏</option><option value="line_motion">阶段 2 · 判定线运动</option><option value="placement">阶段 3 · 空间与固定键位</option><option value="all">按顺序训练全部阶段</option></select></div><div class="form-grid"><div class="field"><label>训练轮数 Epoch</label><input v-model.number="training.epochs" type="number" min="1" max="1000" step="1"></div><div class="field"><label>每批并行窗口</label><select v-model.number="training.microbatch" :disabled="!!training.resume_run_id"><option v-for="size in [1, 2, 4, 8, 16]" :key="size" :value="size">{{ size }} 个窗口</option></select></div><div class="field"><label>累计批次</label><input v-model.number="training.grad_accum" :disabled="!!training.resume_run_id" type="number" min="1" max="128" step="1"></div><div class="field"><label>随机种子</label><input v-model.number="training.seed" :disabled="!!training.resume_run_id" type="number" min="0" max="4294967295" step="1"></div><div class="field"><label>计算设备</label><select v-model="training.device" :disabled="!!training.resume_run_id"><option value="cpu">CPU</option><option value="cuda">GPU / CUDA（需本机可用）</option></select></div></div><div class="soft-callout"><strong>当前每 {{ training.microbatch * training.grad_accum }} 个窗口更新一次参数</strong><p>每批最多 {{ training.microbatch }} 个同曲窗口并行；CPU预取 {{ training.prefetch_batches }} 批。续训应用本机档位时保留原有效批量。</p><button class="button secondary" :disabled="runtime.source !== 'local_calibration'" @click="applyRuntime">应用本机已校准档位</button></div><div class="soft-callout"><strong>RTX 5060 8GB / 16GB RAM 设计基线</strong><p>分阶段加载、短窗口与梯度累积。默认使用本机 RTX 5060 的 CUDA，逐阶段训练全部模型；新模型负载的实际显存峰值和训练效果以真实运行记录为准，当前未验收。</p><p v-if="state.status.hardware" class="micro">本机返回：{{ typeof state.status.hardware === 'string' ? state.status.hardware : JSON.stringify(state.status.hardware) }}</p></div><p v-if="gpuBusy" class="inline-error">已有生成或训练任务。请等待完成或在任务中心取消后继续。</p><button class="button primary full" :disabled="!training.dataset_id || training.epochs < 1 || training.grad_accum < 1 || gpuBusy || state.busy.training" @click="startTraining">{{ state.busy.training ? '正在提交…' : '开始真实训练' }}</button><p class="field-hint">任务进度和取消入口在“任务中心”。没有真实日志或 checkpoint 时，不显示训练成功。</p></section></div>
  <section class="panel"><div class="panel-heading"><div><p class="section-kicker">版本化数据</p><h2>本地数据集</h2></div><span class="muted micro">{{ state.datasets.length }} 个版本</span></div><div class="table-scroll"><table><thead><tr><th>数据集</th><th>样本与分组</th><th>Manifest SHA-256</th><th>创建时间</th></tr></thead><tbody><tr v-for="d in state.datasets" :key="d.id"><td><strong>{{ d.name || short(d.id) }}</strong><small>版本 {{ d.version || '—' }}</small></td><td>{{ d.sample_count ?? d.samples?.length ?? '—' }} 样本<small>{{ d.group_count != null ? `${d.group_count} 个歌曲组` : '按歌曲分组，详见 manifest' }}</small></td><td><code>{{ short(d.sha256 || d.manifest_sha256) }}</code><details><summary>查看实际 manifest</summary><pre>{{ JSON.stringify(d, null, 2) }}</pre></details></td><td>{{ date(d.created_at) }}</td></tr><tr v-if="!state.datasets.length"><td colspan="4"><div class="empty small"><strong>还没有构建数据集</strong><p>在上方选择符合条件的素材并开始构建。</p></div></td></tr></tbody></table></div></section>
  <section class="panel"><div class="panel-heading"><div><p class="section-kicker">真实训练记录</p><h2>过程与结果，都可以查回。</h2></div><select v-model="chosenRun" class="run-select"><option value="">选择训练记录查看详情</option><option v-for="r in state.runs" :key="r.id || r.run_id" :value="r.id || r.run_id">{{ short(r.id || r.run_id) }} · {{ label(r.stage) }} · {{ label(r.training_state || r.status) }}</option></select></div><div v-if="!state.runs.length" class="empty small"><span class="empty-icon">⌘</span><strong>尚无真实训练记录</strong><p>完成数据集构建并发起训练后，日志和权重会在本机保存。</p></div><template v-if="run"><p v-if="run.error || run.message" class="soft-callout">{{ run.error || run.message }}</p><div class="row between"><span class="badge blue">{{ label(run.training_state || run.status) }}</span><span class="muted micro">{{ date(run.created_at) }}</span></div><svg v-if="loss.length > 1" viewBox="0 0 620 160" class="loss-chart" role="img" aria-label="实际训练损失曲线"><line x1="20" y1="130" x2="600" y2="130" stroke="#d7dfe4"/><polyline :points="points(loss)" fill="none" stroke="#337e8b" stroke-width="2.5"/><text x="20" y="153" fill="#71808d" font-size="10">真实训练步序 · Loss</text></svg><p v-else class="soft-callout muted">此记录尚未提供可绘制的 loss 序列，不显示模拟曲线。</p><details open><summary>训练元数据与日志</summary><pre>{{ JSON.stringify(run, null, 2) }}</pre></details></template></section>
  <section class="panel"><div class="panel-heading"><div><p class="section-kicker">MODEL REGISTRY</p><h2>可用权重与来源</h2></div><span class="badge outline">默认 experimental</span></div><div class="model-grid"><article v-for="m in state.models" :key="m.id || m.bundle_id" class="registry-card"><div class="row between"><span class="file-icon">{{ m.status === 'baseline_only' ? '≋' : '⌘' }}</span><span :class="['badge', m.available ? 'green' : m.status === 'baseline_only' ? '' : 'amber']">{{ label(m.status) }}</span></div><h3>{{ m.name || m.id || m.bundle_id }}</h3><p>{{ m.status === 'baseline_only' ? '传统音频分析与规则生成，不包含训练权重。' : m.available ? '服务已标记权重可加载，真实效果仍需独立审核与试玩。' : '此记录尚无可用权重，无法用于模型生成。' }}</p><p class="micro muted">训练记录 {{ short(m.run_id) }} · 权重 {{ short(m.checkpoint_sha256) }}</p><details><summary>查看来源、支持模式与证据</summary><pre>{{ JSON.stringify(m, null, 2) }}</pre></details></article><div v-if="!state.models.length" class="empty"><strong>模型注册表暂无记录</strong><p>请连接本地服务或完成真实训练。</p></div></div><details class="promotion"><summary>有人工证据后，申请提升模型状态</summary><p class="small-text muted">训练结束只产生实验权重。候选 / 稳定状态需要独立校验、真实生成与真人试玩证据，由服务再次核验。</p><div class="form-grid"><div class="field"><label>实际模型</label><select v-model="promoteModel"><option value="" disabled>选择真实权重</option><option v-for="m in state.models.filter(m => m.status !== 'baseline_only')" :key="m.id" :value="m.id">{{ m.name || m.id }}</option></select></div><div class="field"><label>目标状态</label><select v-model="promotion"><option value="candidate">候选 candidate</option><option value="stable">稳定 stable</option></select></div><div class="field span-2"><label>人工证据引用与说明</label><textarea v-model="evidence" rows="3" placeholder="提供审计、人工审核、真实客户端试玩记录 ID 与结果。"></textarea></div></div><button class="button secondary" :disabled="!promoteModel || !evidence.trim() || state.busy.promote" @click="promote">根据上述人工证据申请提升</button></details></section>
</template>
