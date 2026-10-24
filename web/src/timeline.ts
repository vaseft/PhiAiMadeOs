import type { RecordData, Timeline } from './types'
export function beatNumber(v: any): number {
  if (Array.isArray(v)) return Number(v[0] || 0) + Number(v[1] || 0) / (Number(v[2]) || 1)
  if (v && typeof v === 'object') return Number(v.whole || 0) + Number(v.numerator || 0) / (Number(v.denominator) || 1)
  return Number(v) || 0
}
function bpmSegments(map: RecordData[]) {
  return (map || []).map(m => ({ beat: beatNumber(m.beat ?? m.start_beat ?? m.startTime ?? 0), bpm: Number(m.bpm || 120) })).filter(m => m.bpm > 0).sort((a, b) => a.beat - b.beat)
}
function offset(data: Timeline) { return Number(data.offset_ms || 0) / 1000 + Number(data.info_offset_s || 0) }
// Matches formats.py: package parser flags determine each line's effective time_scale.
export function secondsToBeat(seconds: number, data: Timeline, factor = 1) {
  const map = bpmSegments(data.bpm_map), elapsed = (seconds - offset(data)) / Math.max(.000001, factor)
  if (!map.length) return elapsed * 2
  let remain = elapsed
  for (let i = 0; i < map.length; i++) {
    const seg = map[i]!, next = map[i + 1]
    const span = next ? (next.beat - seg.beat) * 60 / seg.bpm : Infinity
    if (remain <= span) return seg.beat + remain * seg.bpm / 60
    remain -= span
  }
  return 0
}
export function beatToSeconds(beat: number, data: Timeline, factor = 1) {
  const map = bpmSegments(data.bpm_map)
  if (!map.length) return beat / 2 * factor + offset(data)
  let seconds = 0
  if (beat < map[0]!.beat) return (beat - map[0]!.beat) * 60 / map[0]!.bpm * factor + offset(data)
  for (let i = 0; i < map.length; i++) {
    const seg = map[i]!, next = map[i + 1]
    if (beat <= seg.beat) break
    seconds += (Math.min(beat, next?.beat ?? beat) - seg.beat) * 60 / seg.bpm
    if (!next || beat < next.beat) break
  }
  return seconds * factor + offset(data)
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
function eventValue(events: any[], beat: number, fallback: number) {
  if (!Array.isArray(events) || !events.length) return fallback
  let selected = events[0], selectedStart = -Infinity
  for (const event of events) { const start = beatNumber(event.startTime ?? event.start_beat); if (start <= beat && start >= selectedStart) { selected = event; selectedStart = start } }
  const a = beatNumber(selected.startTime ?? selected.start_beat), b = beatNumber(selected.endTime ?? selected.end_beat), start = Number(selected.start ?? 0), end = Number(selected.end ?? start)
  if (beat < a) return start
  return beat >= b || b <= a ? end : start + (end - start) * fraction(selected, (beat - a) / (b - a))
}
export function lineTransform(line: RecordData, audioSeconds: number, data: Timeline, visited = new Set<string>()): { x: number; y: number; rotation: number; alpha: number } {
  if (visited.has(String(line.id))) return { x: 0, y: 0, rotation: 0, alpha: 1 }
  visited.add(String(line.id))
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
  const parent = father != null ? data.judge_lines.find(p => String(p.id) === String(father)) : undefined
  if (parent) {
    const p = lineTransform(parent, audioSeconds, data, visited), r = p.rotation * Math.PI / 180
    const dx = x, dy = y
    x = p.x + dx * Math.cos(r) - dy * Math.sin(r); y = p.y + dx * Math.sin(r) + dy * Math.cos(r)
    if (raw.rotateWithFather !== false) rotation += p.rotation
  }
  return { x, y, rotation, alpha: hasAlpha ? Math.max(0, Math.min(1, alpha / 255)) : 1 }
}
