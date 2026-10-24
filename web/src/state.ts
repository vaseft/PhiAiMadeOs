import { reactive } from 'vue'
import { api, ApiError, openSession } from './api'
import type { Asset, Chart, Candidate, Job, RecordData } from './types'
export const state = reactive({
  connected: false, loading: false, status: {} as RecordData,
  assets: [] as Asset[], charts: [] as Chart[], candidates: [] as Candidate[], jobs: [] as Job[],
  models: [] as RecordData[], datasets: [] as RecordData[], runs: [] as RecordData[], capabilities: {} as RecordData,
  notices: [] as { id: number; text: string; tone: string; detail?: string }[],
  busy: {} as Record<string, boolean>,
})
let noticeId = 0
export function notify(text: string, tone = 'success', detail?: string) {
  const id = ++noticeId
  state.notices.push({ id, text, tone, detail })
  if (state.notices.length > 8) state.notices.shift()
  if (tone === 'success') setTimeout(() => { state.notices = state.notices.filter(n => n.id !== id) }, 7000)
}
export function showError(e: unknown) {
  notify(e instanceof Error ? e.message : '操作未完成。', 'error', e instanceof ApiError ? e.code : undefined)
}
export async function perform<T>(key: string, work: () => Promise<T>, success?: string): Promise<T | undefined> {
  if (state.busy[key]) return
  state.busy[key] = true
  try { const result = await work(); if (success) notify(success); return result }
  catch (e) { showError(e) }
  finally { state.busy[key] = false }
}
let refreshing = false
export async function refresh(all = false) {
  if (refreshing) return
  refreshing = true
  if (all) state.loading = true
  try {
    if (all) await openSession(true)
    const status = await api('/status')
    state.status = status; state.connected = true
    const preparing = [...state.jobs, ...(status.jobs || [])].some((job: Job) => ['audio_prepare', 'dataset_prepare'].includes(job.kind || '') && (activeJob(job) || !state.jobs.some(previous => previous.id === job.id && previous.updated_at === job.updated_at && jobState(previous) === jobState(job))))
    const resources = all ? ['assets', 'charts', 'candidates', 'jobs', 'models', 'datasets', 'training/runs', 'capabilities'] : ['candidates', 'jobs', 'models', 'training/runs', ...(status.counts?.datasets !== state.datasets.length ? ['datasets'] : []), ...(status.counts?.assets !== state.assets.length || preparing ? ['assets'] : []), ...(status.counts?.charts !== state.charts.length || preparing || state.jobs.some(job => job.kind === 'library_reprocess' && activeJob(job)) ? ['charts'] : [])]
    const results = await Promise.allSettled(resources.map(path => api('/' + path)))
    results.forEach((r, i) => {
      if (r.status === 'fulfilled') {
        const key = resources[i] === 'training/runs' ? 'runs' : resources[i]
        ;(state as any)[key] = key === 'capabilities' ? r.value : r.value.items || []
      } else if (all) showError(r.reason)
    })
  } catch (e) { state.connected = false; if (all) showError(e) }
  finally { refreshing = false; state.loading = false }
}
export function jobState(job: Job) { return String(job.state || job.status || 'unknown').toLowerCase() }
export function activeJob(job: Job) { return ['queued', 'pending', 'running', 'generating', 'auditing', 'training', 'cancelling', 'cancel_requested'].includes(jobState(job)) }
export function label(value: unknown) {
  const labels: Record<string, string> = { regular: '常规多线', pure_keys: '固定键位', anomaly: '特殊异像', explicit_permitted: '明确许可', restricted: '有限许可', unknown: '许可待确认', local_research: '本地研究', training: '模型训练', distribution: '对外分发', queued: '等待执行', pending: '等待执行', running: '正在执行', completed: '已完成', succeeded: '已完成', success: '已完成', failed: '失败', cancelled: '已取消', cancelling: '正在取消', cancel_requested: '正在取消', generated: '已生成', auditing: '审计中', ready_for_review: '待人工审核', audit_blocked: '审计阻断', approved: '审核通过', revision_requested: '退回修改', rejected: '已拒绝', exported: '已导出', experimental: '实验权重', candidate: '候选权重', stable: '稳定权重', baseline_only: '规则基线', note_rhythm: '音符与节奏', line_motion: '判定线运动', placement: '空间与键位', all: '依次训练全部阶段', cpu: 'CPU', cuda: 'GPU / CUDA' }
  Object.assign(labels, { draft: '草稿', awaiting_review: '待人工审核', blocked: '审计阻断', not_run: '尚未运行', interrupted: '已中断', partial: '部分完成', analysis: '音频分析', generation: '谱面生成', learned_generation: '模型生成', audit: '独立审计', dataset: '构建数据集', postprocess: '局部建议', training: '模型训练' })
  labels.library_import = '导入本地素材库'
  labels.library_reprocess = '补处理容量与时序受限谱面'
  labels.audio_prepare = '准备音频特征'
  labels.dataset_prepare = '核对训练素材与歌曲分组'
  const text = String(value ?? '—'); return labels[text.toLowerCase()] || text
}
export function time(value?: number) { if (!Number.isFinite(value)) return '—'; const n = Math.max(0, value!); return `${Math.floor(n / 60).toString().padStart(2, '0')}:${(n % 60).toFixed(3).padStart(6, '0')}` }
export function date(value?: string | number) { if (!value) return '—'; const d = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value); return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN', { hour12: false }) }
export function short(value?: string) { return value ? value.slice(0, 10) : '—' }
export function nameOf(id: string) { return state.assets.find(a => a.id === id)?.name || '未关联音乐' }
