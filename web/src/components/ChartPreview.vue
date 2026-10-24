<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, audioUrl } from '../api'
import { time } from '../state'
import { beatToSeconds, secondsToBeat, lineTransform } from '../timeline'
import type { Note, Timeline } from '../types'
const props = defineProps<{ candidateId: string; musicId: string }>()
const emit = defineEmits<{ time: [value: number]; selectNote: [note: Note] }>()
const audio = ref<HTMLAudioElement>()
const canvas = ref<HTMLCanvasElement>()
const wave = ref<HTMLCanvasElement>()
const data = ref<Timeline | null>(null)
const peaks = ref<number[]>([])
const onsets = ref<number[]>([])
const current = ref(0), duration = ref(0), playing = ref(false), rate = ref(1), error = ref(''), audioError = ref(''), loading = ref(false)
const showNotes = ref(true), showLines = ref(true), showIds = ref(false), showWave = ref(true), showOnsets = ref(true), showEvents = ref(true)
const hitTargets: { x: number; y: number; r: number; note: Note }[] = []
let frame = 0, mounted = false, observer: ResizeObserver | undefined, sequence = 0, pageStart = -100, fetchingPage = false, retryAfter = 0
let waveDuration = 0
const metadata = computed(() => data.value ? `${data.value.chart_mode === 'pure_keys' ? `固定 ${data.value.key_count}K` : '动态判定线'} · 当前窗口 ${data.value.notes?.length || 0} 个音符` : '等待时间轴')
function fit(el: HTMLCanvasElement) {
  const rect = el.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2)
  if (el.width !== Math.round(rect.width * dpr) || el.height !== Math.round(rect.height * dpr)) { el.width = Math.round(rect.width * dpr); el.height = Math.round(rect.height * dpr) }
  const ctx = el.getContext('2d')!; ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  return { ctx, w: rect.width, h: rect.height }
}
async function loadPage(at: number, force = false) {
  if (!props.candidateId || fetchingPage || (!force && Date.now() < retryAfter) || (!force && at >= Math.max(0, pageStart + 4) && at < pageStart + 34)) return
  const start = Math.max(0, Math.floor(at / 25) * 25 - 8), seq = sequence
  fetchingPage = true
  try { const result = await api<Timeline>(`/candidates/${props.candidateId}/timeline?start_s=${start}&end_s=${start + 50}`); if (seq === sequence) { data.value = result; pageStart = start; retryAfter = 0; duration.value = Number(result.duration_s) || duration.value; error.value = '' } }
  catch (e) { if (seq === sequence) { retryAfter = Date.now() + 3000; error.value = e instanceof Error ? e.message : '时间轴读取失败。' } }
  finally { if (seq === sequence) fetchingPage = false }
}
async function load() {
  ++sequence; pageStart = -100; retryAfter = 0; fetchingPage = false; data.value = null; peaks.value = []; onsets.value = []; error.value = ''; audioError.value = ''; current.value = 0; duration.value = 0; waveDuration = 0
  audio.value?.pause(); if (audio.value) { try { audio.value.currentTime = 0 } catch {} } playing.value = false
  if (!props.candidateId) return
  loading.value = true
  await loadPage(0, true)
  if (props.musicId) {
    const seq = sequence
    try { const result = await api(`/assets/${props.musicId}/waveform`); if (seq === sequence) { peaks.value = (result.peaks || []).map((v: any) => Array.isArray(v) ? Math.max(...v.map((n: any) => Math.abs(Number(n)))) : Math.abs(Number(v))); waveDuration = Number(result.duration_s) || 0; onsets.value = result.onsets_s || [] } }
    catch (e) { if (seq === sequence) error.value = `波形不可用：${e instanceof Error ? e.message : '未返回数据'}` }
  }
  loading.value = false
}
function seek(value: number) { const t = Math.max(0, Math.min(duration.value || Infinity, value)); if (audio.value) { try { audio.value.currentTime = t } catch { /* Metadata not yet available; the requested static frame remains visible. */ } } current.value = t; emit('time', t); void loadPage(t) }
function nativeSeek() { current.value = audio.value?.currentTime || 0; emit('time', current.value); void loadPage(current.value) }
function metadataLoaded() { if (!audio.value) return; duration.value = Number.isFinite(audio.value.duration) ? audio.value.duration : duration.value; audio.value.playbackRate = rate.value; audioError.value = '' }
async function toggle() {
  if (!audio.value || !props.musicId) return
  try { if (audio.value.paused) await audio.value.play(); else audio.value.pause(); audioError.value = '' }
  catch { audioError.value = '浏览器尚未允许播放，或音频无法解码。请直接点击下方音频控件重试。' }
}
function jumpBar(direction: number) { if (data.value) seek(beatToSeconds(Math.max(0, secondsToBeat(current.value, data.value) + direction * 4), data.value)) }
function draw() {
  if (!mounted) return
  if (audio.value && !audio.value.paused) { current.value = audio.value.currentTime; emit('time', current.value); void loadPage(current.value) }
  if (canvas.value) {
    const { ctx, w, h } = fit(canvas.value)
    ctx.clearRect(0, 0, w, h); ctx.fillStyle = '#111b29'; ctx.fillRect(0, 0, w, h)
    const grad = ctx.createRadialGradient(w * .5, h * .65, 0, w * .5, h * .5, w * .7); grad.addColorStop(0, '#203448'); grad.addColorStop(1, '#111b29'); ctx.fillStyle = grad; ctx.fillRect(0, 0, w, h)
    ctx.strokeStyle = '#ffffff06'; ctx.lineWidth = 1
    for (let x = 0; x < w; x += w / 12) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke() }
    for (let y = 0; y < h; y += h / 8) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke() }
    hitTargets.length = 0
    if (data.value) {
      const d = data.value, pure = d.chart_mode === 'pure_keys', K = d.key_count || 4, judgeY = h * .725, scale = w / 1350, velocity = h * .43
      if (pure) {
        for (let k = 0; k < K; k++) { const x = k * w / K; ctx.fillStyle = k % 2 ? '#ffffff04' : '#ffffff09'; ctx.fillRect(x, 0, w / K, h); ctx.strokeStyle = '#ffffff10'; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); ctx.fillStyle = '#8395a8'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center'; ctx.fillText(String(k + 1), x + w / (2 * K), h - 15) }
        if (showLines.value) { ctx.strokeStyle = '#d0e8f6'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(0, judgeY); ctx.lineTo(w, judgeY); ctx.stroke() }
      }
      const lineMap = new Map<string, { x: number; y: number; rotation: number; alpha: number }>()
      for (const line of d.judge_lines || []) {
        const t = lineTransform(line, current.value, d); lineMap.set(String(line.id), t)
        if (!pure && showLines.value) { ctx.save(); ctx.globalAlpha = t.alpha; ctx.translate(w / 2 + t.x * w / 2, h / 2 - t.y * h / 2); ctx.rotate(-t.rotation * Math.PI / 180); ctx.strokeStyle = '#d2e9ef'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(-w * .5, 0); ctx.lineTo(w * .5, 0); ctx.stroke(); if (showIds.value) { ctx.fillStyle = '#8ab9c5'; ctx.font = '10px monospace'; ctx.fillText(`LINE ${line.id}`, -w * .38, -8) } ctx.restore() }
      }
      if (showNotes.value) for (const n of d.notes || []) {
        const start = Number(n.time_s), end = Number(n.end_time_s ?? start), delta = start - current.value
        if (end < current.value - .16 || delta > 3 || !Number.isFinite(start)) continue
        const t = lineMap.get(String(n.line_id)) || { x: 0, y: 0, rotation: 0, alpha: 1 }
        const baseX = pure ? ((Number(n.lane_index) || 0) + .5) * w / K : w / 2 + t.x * w / 2
        const baseY = pure ? judgeY : h / 2 - t.y * h / 2
        const r = pure ? 0 : -t.rotation * Math.PI / 180, noteX = pure ? 0 : Number(n.x || 0) * scale, dir = n.above === 2 ? -1 : 1
        const noteY = -Math.max(delta, 0) * velocity * dir, kind = String(n.kind).toUpperCase(), width = pure ? Math.max(12, w / K * .73) : Math.max(22, 72 * scale)
        const color = kind === 'HOLD' ? '#e9c47b' : kind === 'DRAG' ? '#8ce3c6' : kind === 'FLICK' ? '#f39fae' : '#8bc9f0'
        ctx.save(); ctx.globalAlpha = (n.fake ? .32 : 1) * (pure ? 1 : t.alpha); ctx.translate(baseX, baseY); ctx.rotate(r); ctx.translate(noteX, noteY)
        if (kind === 'HOLD') { const body = Math.max(0, (end - Math.max(start, current.value)) * velocity); ctx.fillStyle = '#e9c47b55'; ctx.fillRect(-width / 2 + 3, -body * dir, width - 6, body * dir); ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.strokeRect(-width / 2 + 3, -body * dir, width - 6, body * dir) }
        ctx.shadowColor = color; ctx.shadowBlur = 9; ctx.fillStyle = color
        if (kind === 'FLICK') { ctx.beginPath(); ctx.moveTo(-width / 2, 0); ctx.lineTo(0, -7); ctx.lineTo(width / 2, 0); ctx.lineTo(0, 7); ctx.closePath(); ctx.fill() }
        else { ctx.fillRect(-width / 2, -4, width, 8); ctx.fillStyle = '#ffffff99'; ctx.fillRect(-width / 2 + 2, -3, width - 4, 1) }
        ctx.shadowBlur = 0
        if (showIds.value) { ctx.fillStyle = '#d8e1ea'; ctx.font = '9px monospace'; ctx.textAlign = 'center'; ctx.fillText(n.id, 0, -12) }
        ctx.restore()
        hitTargets.push({ x: baseX + noteX * Math.cos(r) - noteY * Math.sin(r), y: baseY + noteX * Math.sin(r) + noteY * Math.cos(r), r: Math.max(14, width / 2), note: n })
      }
      ctx.fillStyle = '#b6c5d3'; ctx.font = '10px sans-serif'; ctx.textAlign = 'left'; ctx.fillText(pure ? `${K}K · STATIC LANES` : 'DYNAMIC LINES · REFERENCE PREVIEW', 18, 25)
      ctx.textAlign = 'right'; ctx.fillText(`${time(current.value)}  /  ${time(duration.value)}`, w - 18, 25)
    } else { ctx.fillStyle = '#a6b8c9'; ctx.font = '14px sans-serif'; ctx.textAlign = 'center'; ctx.fillText(loading.value ? '正在读取本地时间轴…' : '选择候选谱面后显示预览', w / 2, h / 2) }
  }
  drawWave(); frame = requestAnimationFrame(draw)
}
function drawWave() {
  if (!wave.value) return
  const { ctx, w, h } = fit(wave.value), dur = waveDuration || duration.value || 1
  ctx.clearRect(0, 0, w, h); ctx.fillStyle = '#f1f4f6'; ctx.fillRect(0, 0, w, h)
  if (showWave.value && peaks.value.length) { const mid = h * .36, max = Math.max(1, ...peaks.value.slice(0, 10000)); for (let x = 0; x < w; x += 3) { const idx = Math.floor(x / w * peaks.value.length), a = Math.min(1, (peaks.value[idx] || 0) / max); ctx.fillStyle = x / w * dur < current.value ? '#397f8b' : '#a3b8c2'; ctx.fillRect(x, mid - a * (h * .28), 2, Math.max(1, a * h * .56)) } }
  if (showOnsets.value) for (const onset of onsets.value) { ctx.strokeStyle = '#d69a51'; ctx.beginPath(); ctx.moveTo(Number(onset) / dur * w, 0); ctx.lineTo(Number(onset) / dur * w, h * .65); ctx.stroke() }
  if (showNotes.value) for (const n of data.value?.notes || []) { ctx.fillStyle = String(n.kind).toUpperCase() === 'HOLD' ? '#bd9859' : '#5b9baa'; ctx.fillRect(n.time_s / dur * w, h * .76, Math.max(2, ((n.end_time_s || n.time_s) - n.time_s) / dur * w), 5) }
  if (showEvents.value && data.value) { const map = data.value; for (const l of map.judge_lines || []) for (const layer of l.raw?.eventLayers || []) for (const event of [...(layer.moveXEvents || []), ...(layer.moveYEvents || []), ...(layer.rotateEvents || [])]) { ctx.fillStyle = '#a29bc1'; const x = beatToSeconds(Number.isFinite(event.startTime) ? event.startTime : (Array.isArray(event.startTime) ? event.startTime[0] + event.startTime[1] / event.startTime[2] : 0), map) / dur * w; ctx.fillRect(x, h * .9, 2, 4) } }
  ctx.strokeStyle = '#202f40'; ctx.lineWidth = 1.5; const playX = current.value / dur * w; ctx.beginPath(); ctx.moveTo(playX, 0); ctx.lineTo(playX, h); ctx.stroke()
}
function waveClick(e: MouseEvent) { const el = wave.value!; const r = el.getBoundingClientRect(); seek((e.clientX - r.left) / r.width * (waveDuration || duration.value)) }
function noteClick(e: MouseEvent) { const r = canvas.value!.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top; const hit = hitTargets.slice().reverse().find(t => Math.abs(t.x - x) < t.r && Math.abs(t.y - y) < 14); if (hit) { audio.value?.pause(); emit('selectNote', hit.note) } }
watch(() => [props.candidateId, props.musicId], load)
watch(rate, value => { if (audio.value) audio.value.playbackRate = value })
onMounted(() => { mounted = true; void load(); observer = new ResizeObserver(() => { drawWave() }); if (canvas.value) observer.observe(canvas.value); frame = requestAnimationFrame(draw) })
onActivated(() => { mounted = true; cancelAnimationFrame(frame); frame = requestAnimationFrame(draw) })
onDeactivated(() => { mounted = false; cancelAnimationFrame(frame); audio.value?.pause() })
onUnmounted(() => { mounted = false; ++sequence; cancelAnimationFrame(frame); observer?.disconnect(); audio.value?.pause() })
defineExpose({ seek })
</script>
<template>
  <section class="preview-panel">
    <div class="preview-heading"><div><span class="preview-dot"></span><strong>同步参考预览</strong><small>{{ metadata }}</small></div><label class="checkbox"><input v-model="showIds" type="checkbox">显示 ID</label></div>
    <canvas ref="canvas" class="chart-canvas" aria-label="谱面参考画面，点击音符可创建局部修改建议" @click="noteClick"></canvas>
    <div class="transport"><div class="row"><button class="icon-button" aria-label="后退一小节" title="后退四拍" @click="jumpBar(-1)">↤</button><button class="play-button" :disabled="!musicId || !!audioError" :aria-label="playing ? '暂停' : '播放'" @click="toggle">{{ playing ? 'Ⅱ' : '▶' }}</button><button class="icon-button" aria-label="前进一小节" title="前进四拍" @click="jumpBar(1)">↦</button><span class="time-display">{{ time(current) }} <span>/ {{ time(duration) }}</span></span></div><select v-model.number="rate" class="speed-select" aria-label="播放速度"><option :value=".5">0.5×</option><option :value="1">1×</option><option :value="1.5">1.5×</option><option :value="2">2×</option></select></div>
    <input class="seek-slider" type="range" min="0" :max="duration || 1" step=".001" :value="current" aria-label="定位播放时间" @input="seek(Number(($event.target as HTMLInputElement).value))">
    <div class="wave-toolbar"><strong>音乐与事件</strong><div class="row"><label class="checkbox"><input v-model="showWave" type="checkbox">波形</label><label class="checkbox"><input v-model="showNotes" type="checkbox">音符</label><label class="checkbox"><input v-model="showLines" type="checkbox">判定线</label><label class="checkbox"><input v-model="showOnsets" type="checkbox">起音</label><label class="checkbox"><input v-model="showEvents" type="checkbox">线事件</label></div></div>
    <canvas ref="wave" class="wave-canvas" aria-label="点击波形定位时间" @click="waveClick"></canvas>
    <div class="preview-bottom"><span>{{ peaks.length ? '点击波形或拖动进度条定位；点击音符创建局部提案。' : '波形暂无数据，仍可使用时间进度条。' }}</span><strong>音频为唯一播放时钟</strong></div>
    <audio v-if="musicId" ref="audio" :key="musicId" :src="audioUrl(musicId)" preload="metadata" controls class="native-audio" @loadedmetadata="metadataLoaded" @play="playing = true" @pause="playing = false" @ended="playing = false" @seeked="nativeSeek" @error="audioError = '音频暂不可播放，请检查素材是否可解码或重新连接本地服务。'"></audio>
    <p v-else class="inline-error">此候选未关联音乐，无法同步播放。</p>
    <p v-if="audioError" class="inline-error">{{ audioError }}</p><p v-if="error" class="inline-error">{{ error }} <button class="text-button" @click="load">重试读取</button></p>
    <p class="preview-disclaimer">这是浏览器参考演示，不登记真人试玩。复杂缓动、纹理、自定义事件与目标客户端可能有差异；正式结论需在 Phira-Pro 中试玩。</p>
  </section>
</template>
