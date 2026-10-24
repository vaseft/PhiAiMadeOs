<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'

type TrainingState = { state: string; progress: number; message: string; can_start: boolean; can_pause: boolean }
const current = ref<TrainingState>({ state: 'connecting', progress: 0, message: '正在连接训练服务…', can_start: false, can_pause: false })
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
      if (!stopped && version === generation) { current.value = value; error.value = '' }
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
  </main>
</template>

<style>
:root { font-family: "Microsoft YaHei UI", "Microsoft YaHei", system-ui, sans-serif; color: #273348; background: #f4f6fa; font-synthesis: none; }
* { box-sizing: border-box; }
body { margin: 0; min-width: 280px; min-height: 100vh; display: grid; place-items: center; padding: 24px; }
main { width: min(100%, 520px); padding: 32px; background: #fff; border: 1px solid #e6eaf1; border-radius: 22px; box-shadow: 0 12px 36px #24335209; }
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
@media (max-width: 400px) { main { padding: 24px 18px; } .controls { gap: 10px; } button { font-size: 16px; } }
@media (prefers-reduced-motion: reduce) { .fill, button { transition: none; } }
</style>
