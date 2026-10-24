import type { RecordData, Timeline } from './types'
export function beatNumber(v: any): number {
  if (Array.isArray(v)) return Number(v[0] || 0) + Number(v[1] || 0) / (Number(v[2]) || 1)
  if (v && typeof v === 'object') return Number(v.whole || 0) + Number(v.numerator || 0) / (Number(v.denominator) || 1)
  return Number(v) || 0
}
type TempoIndex = { beats: Float64Array; bpms: Float64Array; seconds: Float64Array; zero: number }
const tempoIndexes = new WeakMap<RecordData[], TempoIndex>()
function beforeOrAt(values: ArrayLike<number>, target: number) {
  let left = 0, right = values.length
  while (left < right) { const middle = (left + right) >>> 1; if (values[middle]! <= target) left = middle + 1; else right = middle }
  return Math.max(0, left - 1)
}
function tempoIndex(data: Timeline): TempoIndex {
  const map = data.bpm_map || []
  const cached = tempoIndexes.get(map)
  if (cached) return cached
  const rows = map.map(m => ({ beat: beatNumber(m.beat ?? m.start_beat ?? m.startTime ?? 0), bpm: Number(m.bpm || 120) })).filter(m => m.bpm > 0).sort((a, b) => a.beat - b.beat)
  if (!rows.length) rows.push({ beat: 0, bpm: 120 })
  const beats = Float64Array.from(rows, r => r.beat), bpms = Float64Array.from(rows, r => r.bpm), seconds = new Float64Array(rows.length)
  for (let i = 1; i < rows.length; i++) seconds[i] = seconds[i - 1]! + (beats[i]! - beats[i - 1]!) * 60 / bpms[i - 1]!
  const first = beforeOrAt(beats, 0), zero = seconds[first]! - beats[first]! * 60 / bpms[first]!
  const result = { beats, bpms, seconds, zero }
  tempoIndexes.set(map, result)
  return result
}
function offset(data: Timeline) { return Number(data.offset_ms || 0) / 1000 + Number(data.info_offset_s || 0) }
// Matches formats.py: package parser flags determine each line's effective time_scale.
export function secondsToBeat(seconds: number, data: Timeline, factor = 1) {
  const map = tempoIndex(data), elapsed = (seconds - offset(data)) / Math.max(.000001, factor) + map.zero
  const i = beforeOrAt(map.seconds, elapsed)
  return map.beats[i]! + (elapsed - map.seconds[i]!) * map.bpms[i]! / 60
}
export function beatToSeconds(beat: number, data: Timeline, factor = 1) {
  const map = tempoIndex(data), i = beforeOrAt(map.beats, beat)
  return (map.seconds[i]! + (beat - map.beats[i]!) * 60 / map.bpms[i]! - map.zero) * factor + offset(data)
}
function bounceOut(x: number) {
  if (x < 1 / 2.75) return 7.5625 * x * x
  if (x < 2 / 2.75) { x -= 1.5 / 2.75; return 7.5625 * x * x + .75 }
  if (x < 2.5 / 2.75) { x -= 2.25 / 2.75; return 7.5625 * x * x + .9375 }
  x -= 2.625 / 2.75; return 7.5625 * x * x + .984375
}
function easeIn(family: string, x: number): number {
  if (family === 'sine') return 1 - Math.cos(x * Math.PI / 2)
  if (family === 'quad') return x ** 2
  if (family === 'cubic') return x ** 3
  if (family === 'quart') return x ** 4
  if (family === 'quint') return x ** 5
  if (family === 'expo') return x === 0 ? 0 : 2 ** (10 * x - 10)
  if (family === 'circ') return 1 - Math.sqrt(Math.max(0, 1 - x * x))
  if (family === 'back') return 2.70158 * x ** 3 - 1.70158 * x * x
  if (family === 'elastic') return x === 0 || x === 1 ? x : -(2 ** (10 * x - 10)) * Math.sin((10 * x - 10.75) * 2 * Math.PI / 3)
  if (family === 'bounce') return 1 - bounceOut(1 - x)
  return x
}
const eases: Record<number, [string, string]> = { 2: ['sine','out'], 3:['sine','in'], 4:['quad','out'], 5:['quad','in'], 6:['sine','inout'], 7:['quad','inout'], 8:['cubic','out'], 9:['cubic','in'], 10:['quart','out'], 11:['quart','in'], 12:['cubic','inout'], 13:['quart','inout'], 14:['quint','out'], 15:['quint','in'], 16:['expo','out'], 17:['expo','in'], 18:['circ','out'], 19:['circ','in'], 20:['back','out'], 21:['back','in'], 22:['circ','inout'], 23:['back','inout'], 24:['elastic','out'], 25:['elastic','in'], 26:['bounce','out'], 27:['bounce','in'], 28:['bounce','inout'], 29:['elastic','inout'] }
function ease(kind: number, x: number) {
  x = Math.min(1, Math.max(0, x)); const [family, direction] = eases[kind] || ['linear', 'in']
  if (direction === 'in') return easeIn(family, x)
  if (direction === 'out') return 1 - easeIn(family, 1 - x)
  return x < .5 ? easeIn(family, x * 2) / 2 : 1 - easeIn(family, 2 - 2 * x) / 2
}
function fraction(event: RecordData, x: number) {
  if (event.bezier && event.bezierPoints?.length === 4) {
    const [x1, y1, x2, y2] = event.bezierPoints
    const cubic = (t: number, a: number, b: number) => 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t * t * b + t ** 3
    let left = 0, right = 1
    for (let i = 0; i < 30; i++) { const middle = (left + right) / 2; if (cubic(middle, x1, x2) < x) left = middle; else right = middle }
    return cubic((left + right) / 2, y1, y2)
  }
  const kind = Number(event.easingType || 1), left = Number(event.easingLeft ?? 0), right = Number(event.easingRight ?? 1)
  if (kind <= 1 || left >= right || (left === 0 && right === 1)) return ease(kind, x)
  const start = ease(kind, left), end = ease(kind, right)
  return Math.abs(end - start) < 1e-12 ? x : (ease(kind, left + (right - left) * x) - start) / (end - start)
}
type EventIndex = { starts: Float64Array; order: Uint32Array | null }
const eventIndexes = new WeakMap<RecordData[], EventIndex>()
function eventIndex(events: RecordData[]): EventIndex {
  const cached = eventIndexes.get(events)
  if (cached) return cached
  const starts = Float64Array.from(events, e => beatNumber(e.startTime ?? e.start_beat))
  let ordered = true
  for (let i = 1; i < starts.length; i++) if (starts[i]! < starts[i - 1]!) { ordered = false; break }
  // Preserve source order for equal starts: the last event at a boundary wins.
  // The source array itself remains immutable, including non-monotonic timelines.
  const order = ordered ? null : Uint32Array.from(events, (_, i) => i).sort((a, b) => starts[a]! - starts[b]! || a - b)
  const result = { starts, order }
  eventIndexes.set(events, result)
  return result
}
function eventValue(events: RecordData[], beat: number, fallback: number) {
  if (!Array.isArray(events) || !events.length) return fallback
  const index = eventIndex(events)
  let left = 0, right = events.length
  while (left < right) { const middle = (left + right) >>> 1, original = index.order ? index.order[middle]! : middle; if (index.starts[original]! <= beat) left = middle + 1; else right = middle }
  const selected = events[left ? (index.order ? index.order[left - 1]! : left - 1) : 0]!
  const a = beatNumber(selected.startTime ?? selected.start_beat), b = beatNumber(selected.endTime ?? selected.end_beat), start = Number(selected.start ?? 0), end = Number(selected.end ?? start)
  if (beat < a) return start
  return beat >= b || b <= a ? end : start + (end - start) * fraction(selected, (beat - a) / (b - a))
}
export type LineTransform = { x: number; y: number; rotation: number; alpha: number }
const lineIndexes = new WeakMap<RecordData[], Map<string, RecordData>>()
function lineIndex(data: Timeline) {
  let result = lineIndexes.get(data.judge_lines)
  if (!result) { result = new Map(data.judge_lines.map(l => [String(l.id), l])); lineIndexes.set(data.judge_lines, result) }
  return result
}
function resolveLine(line: RecordData, audioSeconds: number, data: Timeline, results: Map<string, LineTransform>, visited: Set<string>): LineTransform {
  const id = String(line.id), cached = results.get(id)
  if (cached) return cached
  if (visited.has(id)) return { x: 0, y: 0, rotation: 0, alpha: 1 }
  visited.add(id)
  const raw = line.raw || line, beat = secondsToBeat(audioSeconds, data, Number(line.time_scale ?? raw.bpmfactor ?? 1)), layers = raw.eventLayers || []
  let x = 0, y = 0, rotation = 0, alpha = 0, hasAlpha = false
  for (const layer of layers) {
    if (!layer) continue
    x += eventValue(layer.moveXEvents, beat, 0) / 675
    y += eventValue(layer.moveYEvents, beat, 0) / 450
    rotation -= eventValue(layer.rotateEvents, beat, 0)
    if (layer.alphaEvents?.length) { alpha += eventValue(layer.alphaEvents, beat, 0); hasAlpha = true }
  }
  const father = line.parent_id ?? (raw.father >= 0 ? `line_${raw.father}` : null)
  const parent = father != null ? lineIndex(data).get(String(father)) : undefined
  if (parent) {
    const p = resolveLine(parent, audioSeconds, data, results, visited), r = p.rotation * Math.PI / 180
    const dx = x, dy = y
    x = p.x + dx * Math.cos(r) - dy * Math.sin(r); y = p.y + dx * Math.sin(r) + dy * Math.cos(r)
    if (raw.rotateWithFather !== false) rotation += p.rotation
  }
  const result = { x, y, rotation, alpha: hasAlpha ? Math.max(0, Math.min(1, alpha / 255)) : 1 }
  visited.delete(id); results.set(id, result)
  return result
}
export function lineTransform(line: RecordData, audioSeconds: number, data: Timeline): LineTransform {
  return resolveLine(line, audioSeconds, data, new Map(), new Set())
}
export function lineTransforms(audioSeconds: number, data: Timeline) {
  const results = new Map<string, LineTransform>(), visiting = new Set<string>()
  for (const line of data.judge_lines) resolveLine(line, audioSeconds, data, results, visiting)
  return results
}
