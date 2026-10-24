<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import TrainingLossChart from './TrainingLossChart.vue'
import type { StageCurve } from './TrainingLossChart.vue'

type Source = { run_id: string; sample_count: number; phase: number; patience: number; plateau_stages: string[] }
type SourceHistory = { run_id: string; sample_count: number; epochs: number }
type Runtime = { microbatch: number; grad_accum: number; prepare_workers: number; prefetch_batches: number; vram_budget_gib: number }
type RuntimeState = { saved: Runtime; active: Runtime | null; applying: boolean; message: string; preparation?: { actual_workers: number; requested_workers: number } }
type Gpu = { utilization_percent: number | null; memory_used_mib: number | null; memory_total_mib: number | null; temperature_c: number | null; power_w: number | null }
type TrainingState = { state: string; progress: number; message: string; can_start: boolean; can_pause: boolean; auto_continue: boolean; auto_replace_source: boolean; source?: Source; source_history: SourceHistory[]; runtime?: RuntimeState; gpu?: Gpu | null }
const current = ref<TrainingState>({ state: 'connecting', progress: 0, message: '正在连接训练服务…', can_start: false, can_pause: false, auto_continue: false, auto_replace_source: false, source_history: [] })
const curves = ref<StageCurve[]>([])
const selectedRun = ref('')
const curvesError = ref('')
const truncated = ref(false)
let pollCount = 0
const pending = ref(false)
const error = ref('')
const percent = computed(() => Math.round(current.value.progress * 100))
const batches = [1, 2, 4, 8, 16, 32, 64, 128]
const draft = ref<Runtime>({ microbatch: 8, grad_accum: 2, prepare_workers: 0, prefetch_batches: 1, vram_budget_gib: 6.2 })
const legacyRuntime = ref<Runtime>({ ...draft.value })
const runtime = computed<RuntimeState>(() => current.value.runtime ?? { saved: legacyRuntime.value, active: null, applying: false, message: '旧服务尚未加载强度接口；重启工作台后可以应用设置。' })
let runtimeLoaded = false
const signature = (value: Runtime) => JSON.stringify([value.microbatch, value.grad_accum, value.prepare_workers, value.prefetch_batches, value.vram_budget_gib])
const dirty = computed(() => !!current.value.runtime && signature(draft.value) !== signature(current.value.runtime.saved))
const batchIndex = computed({ get: () => batches.indexOf(draft.value.microbatch), set: value => { draft.value.microbatch = batches[value] ?? 8 } })
const presets = [
  { name: '稳健', microbatch: 8, grad_accum: 2, prepare_workers: 2, vram_budget_gib: 6.2 },
  { name: '增强', microbatch: 32, grad_accum: 1, prepare_workers: 4, vram_budget_gib: 6.6 },
  { name: '高负载', microbatch: 64, grad_accum: 1, prepare_workers: 6, vram_budget_gib: 7 },
  { name: '极限', microbatch: 128, grad_accum: 1, prepare_workers: 8, vram_budget_gib: 7.2 },
]
function choosePreset(preset: typeof presets[number]) { draft.value = { ...preset, prefetch_batches: 1 } }
function setCurrent(value: TrainingState) {
  const keepDraft = runtimeLoaded && dirty.value
  current.value = value
  if (value.runtime && !keepDraft) { draft.value = { ...value.runtime.saved }; runtimeLoaded = true }
}
function runtimeLabel(value: Runtime) { return `${value.microbatch} 并行 × ${value.grad_accum} 累积 · CPU ${value.prepare_workers || '自动'}路 · ${value.vram_budget_gib} GiB预算` }
const gpuMemory = computed(() => {
  const gpu = current.value.gpu
  return gpu?.memory_used_mib != null && gpu.memory_total_mib != null ? `${(gpu.memory_used_mib / 1024).toFixed(1)} / ${(gpu.memory_total_mib / 1024).toFixed(1)} GB` : '暂不可读'
})
let timer: ReturnType<typeof setTimeout> | undefined
let stopped = false
let refreshing = false
let generation = 0
async function refresh() {
  const version = generation
  if (!pending.value && !refreshing) {
    refreshing = true
    try {
      const value = await api<TrainingState>('/trainer')
      if (!stopped && version === generation) {
        if (!selectedRun.value && current.value.source?.run_id !== value.source?.run_id) { curves.value = []; pollCount = 0 }
        setCurrent(value); error.value = ''
        if (!value.runtime && !runtimeLoaded) {
          try {
            legacyRuntime.value = { ...legacyRuntime.value, ...await api<Runtime>('/training/runtime') }
            draft.value = { ...legacyRuntime.value }; runtimeLoaded = true
          } catch { /* The compatibility notice remains visible. */ }
        }
      }
      if (pollCount++ % 3 === 0) {
        try {
          const selection = selectedRun.value
          const analysis = await api<{ stages: StageCurve[]; truncated: boolean; run_id: string }>('/trainer/analysis' + (selection ? `?run_id=${encodeURIComponent(selection)}` : ''))
          if (!stopped && selection === selectedRun.value && (selection || analysis.run_id === current.value.source?.run_id)) {
            curves.value = analysis.stages; truncated.value = analysis.truncated; curvesError.value = ''
          }
        } catch { curvesError.value = '暂时无法读取曲线，正在重连…' }
      }
    } catch (exc) {
      if (!stopped && version === generation) {
        error.value = exc instanceof Error ? exc.message : '连接暂时中断，正在重新连接…'
        current.value.can_start = false; current.value.can_pause = false
      }
    } finally { refreshing = false }
  }
  if (!stopped) timer = setTimeout(refresh, 1000)
}
async function act(action: 'start' | 'pause') {
  if (pending.value) return
  pending.value = true
  generation++
  error.value = ''
  try { setCurrent(await api<TrainingState>(`/trainer/${action}`, 'POST')) }
  catch (exc) { error.value = exc instanceof Error ? exc.message : '操作失败，请稍后重试' }
  finally { pending.value = false }
}
async function toggleSetting(event: Event, setting: 'auto' | 'source-auto') {
  const enabled = (event.target as HTMLInputElement).checked
  if (pending.value) return
  pending.value = true; generation++; error.value = ''
  try { setCurrent(await api<TrainingState>(`/trainer/${setting}`, 'POST', { enabled })) }
  catch (exc) { error.value = exc instanceof Error ? exc.message : '设置失败，请重试' }
  finally { pending.value = false }
}
async function applyRuntime() {
  if (pending.value || !current.value.runtime) return
  pending.value = true; generation++; error.value = ''
  try {
    const value = await api<TrainingState>('/trainer/runtime', 'POST', {
      microbatch: draft.value.microbatch, grad_accum: draft.value.grad_accum, prepare_workers: draft.value.prepare_workers,
      prefetch_batches: draft.value.prefetch_batches, vram_budget_gib: draft.value.vram_budget_gib,
    })
    current.value = value
    if (value.runtime) draft.value = { ...value.runtime.saved }
  } catch (exc) { error.value = exc instanceof Error ? exc.message : '强度设置未保存，请重试' }
  finally { pending.value = false }
}
onMounted(refresh)
onUnmounted(() => { stopped = true; clearTimeout(timer) })
</script>

<template>
  <main aria-label="PAMOs训练控制">
    <div class="controls">
      <button class="train" :disabled="pending || !current.can_start" @click="act('start')">训练</button>
      <button class="pause" :disabled="pending || !current.can_pause" @click="act('pause')">暂停训练</button>
    </div>
    <div class="progress" role="progressbar" aria-label="本轮训练进度" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100">
      <div class="fill" :style="{ width: `${percent}%` }"></div>
      <span>{{ percent }}%</span>
    </div>
    <p role="status" aria-live="polite" :class="{ error }">{{ error || (pending ? '正在处理…' : current.message) }}</p>
    <div class="training-options">
      <label class="auto-option"><input type="checkbox" :checked="current.auto_continue" :disabled="pending || current.state === 'connecting' || current.state === 'unavailable'" @change="toggleSetting($event, 'auto')"><span>自动继续</span><small>暂停时关闭</small></label>
      <label class="auto-option"><input type="checkbox" :checked="current.auto_replace_source" :disabled="pending || current.state === 'connecting' || current.state === 'unavailable'" @change="toggleSetting($event, 'source-auto')"><span>无改善自动换源</span><small>连续8轮未刷新验证最佳值后切换</small></label>
    </div>
    <p v-if="current.source" class="source-status">数据阶段 {{ current.source.phase }} · {{ current.source.sample_count }} 份谱面<span v-if="current.source.plateau_stages.length"> · 已达到换源条件</span></p>
    <section class="intensity" aria-label="训练强度设置">
      <div class="intensity-heading"><h1>训练强度</h1><span class="setting-tag">{{ !current.runtime ? '服务待更新' : runtime.applying ? '等待断点后应用' : dirty ? '有未应用的调整' : '设置已保存' }}</span></div>
      <p v-if="!current.runtime" class="compatibility-note">当前服务需要重启以加载强度设置。已保存的训练断点保留。</p>
      <div class="gpu-stats" aria-label="GPU实时状态">
        <span>GPU <strong>{{ current.gpu?.utilization_percent != null ? `${current.gpu.utilization_percent}%` : '暂不可读' }}</strong></span>
        <span>总显存占用 <strong>{{ gpuMemory }}</strong></span>
        <span>温度 <strong>{{ current.gpu?.temperature_c != null ? `${current.gpu.temperature_c} °C` : '—' }}</strong></span>
        <span>功耗 <strong>{{ current.gpu?.power_w != null ? `${current.gpu.power_w.toFixed(0)} W` : '—' }}</strong></span>
      </div>
      <fieldset :disabled="pending || runtime.applying || !current.runtime">
        <div class="presets"><button v-for="preset in presets" :key="preset.name" type="button" :class="{ selected: draft.microbatch === preset.microbatch && draft.grad_accum === preset.grad_accum && draft.prepare_workers === preset.prepare_workers && draft.vram_budget_gib === preset.vram_budget_gib }" @click="choosePreset(preset)">{{ preset.name }}<small>{{ preset.microbatch }} 并行窗口</small></button></div>
        <div class="runtime-fields">
          <label class="batch-field"><span>GPU 并行窗口 <strong>{{ draft.microbatch }}</strong></span><input v-model.number="batchIndex" type="range" min="0" max="7" step="1" aria-label="GPU并行窗口"><small>1 → 128，越大通常越占显存</small></label>
          <label><span>CPU 准备路数</span><select v-model.number="draft.prepare_workers" aria-label="CPU准备路数"><option :value="0">自动</option><option v-for="count in 8" :key="count" :value="count">{{ count }} 路</option></select><small>可用内存不足时会降低实际路数</small></label>
          <label><span>梯度累积</span><input v-model.number="draft.grad_accum" type="number" min="1" :max="Math.min(128, Math.floor(2048 / draft.microbatch))" step="1" aria-label="梯度累积"><small>每次更新 {{ draft.microbatch * draft.grad_accum }} 个窗口</small></label>
          <label><span>训练显存预算 <strong>{{ draft.vram_budget_gib.toFixed(1) }} GiB</strong></span><input v-model.number="draft.vram_budget_gib" type="range" min="2" max="7.2" step="0.1" aria-label="训练显存预算"><small>用于停止超限，不会预占或填满显存</small></label>
        </div>
        <div class="apply-row"><label class="prefetch-option"><input v-model="draft.prefetch_batches" type="checkbox" :true-value="1" :false-value="0">提前准备下一批</label><button class="apply-runtime" :disabled="!dirty || draft.grad_accum < 1 || draft.grad_accum * draft.microbatch > 2048" @click="applyRuntime">{{ current.can_pause ? '应用并继续训练' : '保存强度设置' }}</button></div>
      </fieldset>
      <div class="runtime-detail"><div>已保存：{{ runtimeLabel(runtime.saved) }}</div><div>当前任务：{{ runtime.active ? runtimeLabel(runtime.active) : current.runtime ? '未运行' : '请看上方训练状态' }}<span v-if="runtime.preparation"> · CPU实际 {{ runtime.preparation.actual_workers }} 路</span></div></div>
      <p class="runtime-note">{{ runtime.message || '选择预设或拖动滑块，再点击应用。' }} 运行中在断点后生效；暂停时只保存。调大有效批量会改变每次参数更新的数据量；内存不足时会停止，可调低后从断点继续。</p>
    </section>
    <section class="analysis" aria-label="训练效果分析">
      <div class="analysis-heading"><h1>训练效果</h1><div class="legend"><span class="train-key">训练批次损失</span><span class="val-key">验证损失</span></div></div>
      <label v-if="current.source_history.length" class="history-select">曲线数据阶段 <select v-model="selectedRun" @change="pollCount = 0; curves = []"><option value="">当前阶段 · {{ current.source?.sample_count }} 份谱面</option><option v-for="(source, index) in current.source_history" :key="source.run_id" :value="source.run_id">阶段 {{ index + 1 }} · {{ source.sample_count }} 份 · {{ source.epochs }} 轮</option></select></label>
      <p v-if="!curves.length" class="analysis-note">正在准备当前数据阶段的训练日志；已有历史曲线可从上方选择。</p>
      <div class="charts"><TrainingLossChart v-for="curve in curves" :key="curve.stage" :curve="curve" /></div>
      <p class="analysis-note">{{ curvesError || (truncated ? '显示最近日志区间。' : '') }} 不同数据阶段独立计轮、独立分析；验证按歌曲簇平均，损失不代表可玩性。</p>
    </section>
  </main>
</template>

<style>
:root { font-family: "Microsoft YaHei UI", "Microsoft YaHei", system-ui, sans-serif; color: #273348; background: #f4f6fa; font-synthesis: none; }
* { box-sizing: border-box; }
body { margin: 0; min-width: 280px; min-height: 100vh; display: grid; place-items: center; padding: 24px; }
main { width: min(100%, 1040px); padding: 32px; background: #fff; border: 1px solid #e6eaf1; border-radius: 22px; box-shadow: 0 12px 36px #24335209; }
.controls { display: flex; gap: 16px; margin-bottom: 26px; }
button { flex: 1; min-height: 56px; border-radius: 12px; font: inherit; font-size: 17px; font-weight: 600; cursor: pointer; transition: background .15s; }
.train { color: #fff; border: 1px solid #326be5; background: #326be5; }
.train:hover:enabled { background: #245ac9; }
.pause { color: #344259; border: 1px solid #d7dfea; background: #f5f7fb; }
.pause:hover:enabled { background: #e8edf6; }
button:disabled { opacity: .42; cursor: default; }
button:focus-visible { outline: 3px solid #8cafff; outline-offset: 3px; }
.progress { position: relative; height: 26px; overflow: hidden; border-radius: 20px; background: #e9eef6; }
.fill { height: 100%; background: #84aaf6; transition: width .3s ease; }
.progress span { position: absolute; inset: 0; display: grid; place-items: center; font-size: 13px; font-variant-numeric: tabular-nums; font-weight: 600; color: #19325b; }
p { margin: 14px 0 0; min-height: 20px; font-size: 12px; line-height: 1.6; text-align: center; color: #6a788d; overflow-wrap: anywhere; }
p.error { color: #b43e3e; }
.training-options { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 12px 24px; margin: 20px 0 8px; }
.auto-option { display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 8px; font-size: 13px; cursor: pointer; }
.auto-option input { accent-color: #326be5; width: 17px; height: 17px; cursor: pointer; }
.auto-option small { color: #8190a6; font-size: 11px; }
p.source-status { margin: 6px 0 18px; font-size: 11px; color: #71829c; }
.history-select { display: flex; align-items: center; gap: 10px; font-size: 12px; color: #71829c; margin: 0 0 14px; }
.history-select select { padding: 5px 8px; border: 1px solid #d7dfea; border-radius: 7px; background: #fff; color: #344259; font: inherit; }
.analysis { border-top: 1px solid #edf0f6; padding-top: 20px; }
.intensity { padding: 20px; margin: 16px 0 24px; background: #f8faff; border: 1px solid #e1e9f7; border-radius: 14px; }
.intensity-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.setting-tag { color: #53729f; font-size: 11px; }
p.compatibility-note { text-align: left; color: #95703e; font-size: 12px; }
.gpu-stats { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 16px 0; font-size: 12px; color: #71829c; }
.gpu-stats strong { color: #344259; font-weight: 600; margin-left: 5px; }
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.presets { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.presets button { background: white; border: 1px solid #d7e1f0; color: #4a5e7b; min-height: 58px; font-size: 13px; font-weight: 500; }
.presets button.selected { border-color: #628fe8; background: #eaf1ff; color: #295bc1; }
.presets small { display: block; font-size: 10px; font-weight: 400; margin-top: 4px; color: #8190a6; }
.runtime-fields { display: grid; grid-template-columns: 1.3fr .8fr .8fr 1.3fr; gap: 18px; margin: 20px 0; }
.runtime-fields label { display: flex; flex-direction: column; gap: 10px; min-width: 0; font-size: 12px; color: #4a5e7b; }
.runtime-fields label > span { display: flex; justify-content: space-between; gap: 4px; }
.runtime-fields input[type=range] { width: 100%; margin: 7px 0; accent-color: #326be5; cursor: pointer; }
.runtime-fields input[type=number], .runtime-fields select { width: 100%; min-height: 30px; padding: 4px 8px; background: white; border: 1px solid #d7e1f0; border-radius: 6px; font: inherit; color: #344259; }
.runtime-fields small { color: #8190a6; font-size: 10px; line-height: 1.5; }
.apply-row { display: flex; justify-content: space-between; align-items: center; gap: 20px; }
.prefetch-option { display: flex; align-items: center; gap: 5px; font-size: 12px; color: #71829c; }
.prefetch-option input { accent-color: #326be5; }
button.apply-runtime { flex: initial; min-height: 36px; padding: 8px 20px; font-size: 13px; border: 1px solid #326be5; background: #326be5; color: white; border-radius: 8px; }
.runtime-detail { margin-top: 16px; padding-top: 12px; border-top: 1px solid #e4eaf5; color: #5e7392; font-size: 11px; line-height: 1.9; }
p.runtime-note { margin-top: 8px; text-align: left; font-size: 10px; color: #8190a6; }
@media (max-width: 760px) { .runtime-fields { grid-template-columns: 1fr 1fr; } .intensity { padding: 16px; } .presets { gap: 6px; } }
.analysis-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
h1 { margin: 0; font-size: 15px; font-weight: 600; }
.legend { display: flex; gap: 14px; font-size: 11px; color: #6a788d; }
.legend span::before { content: ''; display: inline-block; width: 14px; height: 3px; vertical-align: middle; margin-right: 5px; background: #6b96ee; border-radius: 2px; }
.legend .val-key::before { background: #d39135; }
.charts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
p.analysis-note { color: #8995a6; font-size: 11px; }
@media (max-width: 760px) { .charts { grid-template-columns: 1fr; } }
@media (max-width: 400px) { main { padding: 24px 18px; } .controls { gap: 10px; } button { font-size: 16px; } }
@media (prefers-reduced-motion: reduce) { .fill, button { transition: none; } }
</style>
