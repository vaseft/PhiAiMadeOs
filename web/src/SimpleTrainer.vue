<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import TrainingLossChart from './TrainingLossChart.vue'
import type { StageCurve } from './TrainingLossChart.vue'

type Source = { run_id: string; sample_count: number; phase: number; patience: number; plateau_stages: string[] }
type SourceHistory = { run_id: string; sample_count: number; epochs: number }
type TrainingState = { state: string; progress: number; message: string; can_start: boolean; can_pause: boolean; auto_continue: boolean; auto_replace_source: boolean; source?: Source; source_history: SourceHistory[] }
const current = ref<TrainingState>({ state: 'connecting', progress: 0, message: '正在连接训练服务…', can_start: false, can_pause: false, auto_continue: false, auto_replace_source: false, source_history: [] })
const curves = ref<StageCurve[]>([])
const selectedRun = ref('')
const curvesError = ref('')
const truncated = ref(false)
let pollCount = 0
const pending = ref(false)
const error = ref('')
const percent = computed(() => Math.round(current.value.progress * 100))
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
        current.value = value; error.value = ''
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
  try { current.value = await api<TrainingState>(`/trainer/${action}`, 'POST') }
  catch (exc) { error.value = exc instanceof Error ? exc.message : '操作失败，请稍后重试' }
  finally { pending.value = false }
}
async function toggleSetting(event: Event, setting: 'auto' | 'source-auto') {
  const enabled = (event.target as HTMLInputElement).checked
  if (pending.value) return
  pending.value = true; generation++; error.value = ''
  try { current.value = await api<TrainingState>(`/trainer/${setting}`, 'POST', { enabled }) }
  catch (exc) { error.value = exc instanceof Error ? exc.message : '设置失败，请重试' }
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
    <section class="analysis" aria-label="训练效果分析">
      <div class="analysis-heading"><h1>训练效果</h1><div class="legend"><span class="train-key">训练批次损失</span><span class="val-key">验证损失</span></div></div>
      <label v-if="current.source_history.length" class="history-select">曲线数据阶段 <select v-model="selectedRun" @change="pollCount = 0; curves = []"><option value="">当前阶段 · {{ current.source?.sample_count }} 份谱面</option><option v-for="(source, index) in current.source_history" :key="source.run_id" :value="source.run_id">阶段 {{ index + 1 }} · {{ source.sample_count }} 份 · {{ source.epochs }} 轮</option></select></label>
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
