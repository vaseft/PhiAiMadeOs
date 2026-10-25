<script setup lang="ts">
import { computed } from 'vue'
export type LossPoint = { x: number; loss: number; epoch: number }
export type StageCurve = { stage: string; training: LossPoint[]; validation: LossPoint[]; latest_validation: number | null; validation_change_percent: number | null; trend: string; latest_validation_epoch: number | null }
const props = defineProps<{ curve: StageCurve }>()
const names: Record<string, string> = { note_rhythm: '音符节奏', line_motion: '判定线运动', placement: '音符布局' }
const points = computed(() => [...props.curve.training, ...props.curve.validation])
const bounds = computed(() => {
  const xs = points.value.map(p => p.x), ys = points.value.map(p => p.loss)
  const xmin = xs.length ? Math.max(0, Math.min(...xs) - 1) : 0, xmax = Math.max(...xs, xmin + 1)
  const rawLo = ys.length ? Math.min(...ys) : 0, rawHi = ys.length ? Math.max(...ys) : 1
  const log = rawLo >= 0 && rawHi > 10 && rawHi / Math.max(rawLo, .001) > 50
  const lo = log ? Math.log1p(rawLo) : rawLo, hi = log ? Math.log1p(rawHi) : rawHi
  const pad = Math.max((hi - lo) * .12, Math.abs(hi) * .03, .001)
  return { xmin, xmax, ymin: Math.max(0, lo - pad), ymax: hi + pad, log }
})
const x = (point: LossPoint) => 44 + (point.x - bounds.value.xmin) / (bounds.value.xmax - bounds.value.xmin) * 282
const y = (point: LossPoint) => 148 - ((bounds.value.log ? Math.log1p(point.loss) : point.loss) - bounds.value.ymin) / (bounds.value.ymax - bounds.value.ymin) * 126
const line = (values: LossPoint[]) => values.map(p => `${x(p)},${y(p)}`).join(' ')
const format = (n: number) => n === 0 ? '0' : Math.abs(n) < .01 || Math.abs(n) >= 10000 ? n.toExponential(1) : Number(n.toPrecision(3)).toString()
const ticks = computed(() => [bounds.value.ymax, (bounds.value.ymax + bounds.value.ymin) / 2, bounds.value.ymin].map(v => bounds.value.log ? Math.expm1(v) : v))
const trend = computed(() => {
  const value = props.curve.validation_change_percent
  if (props.curve.trend === 'possible_overfit') return '验证连续上升、训练下降，可能过拟合'
  if (value === null) return '等待更多验证点，暂不判断趋势'
  return `验证损失较上轮${value < 0 ? '下降' : value > 0 ? '上升' : '持平'}${value === 0 ? '' : ` ${Math.abs(value).toFixed(1)}%`}`
})
</script>

<template>
  <article class="loss-card">
    <header><h2>{{ names[curve.stage] || curve.stage }}</h2><span>验证 {{ curve.latest_validation === null ? '—' : format(curve.latest_validation) }}</span></header>
    <svg viewBox="0 0 340 181" role="img" :aria-label="`${names[curve.stage]}训练与验证损失曲线`">
      <template v-for="(tick, i) in ticks" :key="i">
        <line x1="44" x2="326" :y1="22 + i * 63" :y2="22 + i * 63" class="grid-line" />
        <text x="38" :y="26 + i * 63" text-anchor="end">{{ format(tick) }}</text>
      </template>
      <text x="44" y="166">{{ bounds.xmin }}</text><text x="326" y="166" text-anchor="end">{{ bounds.xmax }}</text><text x="185" y="179" text-anchor="middle">优化器步</text>
      <polyline v-if="curve.training.length" :points="line(curve.training)" class="train-line" />
      <polyline v-if="curve.validation.length" :points="line(curve.validation)" class="val-line" />
      <circle v-for="p in curve.validation" :key="p.epoch" :cx="x(p)" :cy="y(p)" r="3" class="val-dot"><title>第{{ p.epoch }}轮验证：{{ p.loss.toFixed(6) }}</title></circle>
      <text v-if="!points.length" x="185" y="86" text-anchor="middle">等待真实训练日志</text>
    </svg>
    <p v-if="bounds.log" class="scale-note">对数刻度 · 保留初期高损失</p>
    <p class="trend" :class="curve.trend">{{ trend }}</p>
  </article>
</template>

<style scoped>
.loss-card { min-width: 0; border: 1px solid #e5eaf3; border-radius: 14px; padding: 16px 12px 12px; background: #fff; }
header { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin: 0 4px 8px; }
h2 { margin: 0; font-size: 14px; font-weight: 600; }
header span { color: #6a788d; font-size: 11px; font-variant-numeric: tabular-nums; }
svg { display: block; width: 100%; overflow: visible; }
text { font-family: inherit; font-size: 9px; fill: #8190a6; }
.grid-line { stroke: #eaf0f7; stroke-width: 1; }
.train-line { fill: none; stroke: #6b96ee; stroke-width: 1.5; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.val-line { fill: none; stroke: #d39135; stroke-width: 2; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.val-dot { fill: #d39135; }
.trend { margin: 6px 0 0; font-size: 11px; text-align: center; min-height: 18px; color: #6a788d; }
.scale-note { margin: 0; text-align: center; font-size: 10px; color: #8995a6; }
.improving { color: #27835a; }
.rising, .possible_overfit { color: #b36e24; }
</style>
