import type { RecordData } from './types'

const ranges: Record<string, [number, number]> = { EZ: [0, 10], HD: [11, 14], IN: [14, 17], AT: [15, 18] }
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value)
export function trainingPermission(record?: RecordData) {
  return record?.license_status === 'explicit_permitted' && Array.isArray(record.allowed_actions) && record.allowed_actions.includes('training')
}
export function difficultyLabelsValid(chart: RecordData) {
  if (chart.difficulty_class == null && chart.difficulty_value == null) return true
  const bounds = ranges[chart.difficulty_class || '']
  return !!bounds && Number.isInteger(chart.difficulty_value) && chart.difficulty_value >= bounds[0] && chart.difficulty_value <= bounds[1]
}
export function automaticAlignment(chart: RecordData, asset?: RecordData) {
  const evidence = chart.alignment_evidence
  return !!asset && evidence?.method === 'game_export_binding_v1' && evidence.status === 'source_metadata_consistent'
    && hash(chart.sha256) && evidence.chart_file_sha256 === chart.sha256
    && hash(asset.sha256) && evidence.audio_sha256 === asset.sha256
    && evidence.music_asset_id === chart.music_asset_id && asset.id === chart.music_asset_id
    && evidence.source_export_user_confirmed === true
    && hash(chart.original_sha256) && evidence.source_chart_sha256 === chart.original_sha256
}
export function automaticGroup(chart: RecordData, asset?: RecordData) {
  const evidence = chart.group_evidence
  return !!asset && evidence?.method === 'export_identity_audio_union_v1' && evidence.status === 'verified'
    && typeof chart.training_group_id === 'string' && !!chart.training_group_id.trim()
    && evidence.group_id === chart.training_group_id
    && hash(asset.sha256) && evidence.audio_sha256 === asset.sha256
    && evidence.music_asset_id === chart.music_asset_id && asset.id === chart.music_asset_id
}
function manualGroup(chart: RecordData) {
  return [undefined, null, 'human_song_cluster', 'manual'].includes(chart.group_method)
    && typeof chart.group_id === 'string' && !!chart.group_id.trim()
}
export function trainingGroup(chart: RecordData, asset?: RecordData) {
  if (manualGroup(chart)) return chart.group_id
  return automaticGroup(chart, asset) ? chart.training_group_id : ''
}
export function alignmentLabel(chart: RecordData, asset?: RecordData) {
  if (chart.human_verified_alignment === true) return '人工确认已对齐'
  return automaticAlignment(chart, asset) ? '游戏导出元数据核对，未人工听音' : '对齐证据待确认'
}
export function groupLabel(chart: RecordData, asset?: RecordData) {
  if (manualGroup(chart)) return '人工歌曲分组'
  return automaticGroup(chart, asset) ? '自动歌曲分组' : '歌曲分组待确认'
}
export function difficultyLabel(chart: RecordData) {
  return chart.difficulty_class && Number.isInteger(chart.difficulty_value)
    ? `目标难度 ${chart.difficulty_class} ${chart.difficulty_value}`
    : '目标难度未标注 · 训练时掩码保留'
}
export function trainingBlockers(chart: RecordData, asset?: RecordData) {
  const reasons: string[] = []
  if (chart.import_status === 'archived_only') reasons.push('仅存档，尚无可训练转换')
  if (!trainingPermission(chart)) reasons.push('谱面训练许可待确认')
  if (!asset) reasons.push('未关联本机音乐')
  else if (!trainingPermission(asset)) reasons.push('音乐训练许可待确认')
  if (chart.human_verified_alignment !== true && !automaticAlignment(chart, asset)) reasons.push('音乐对齐证据待确认或已失效')
  if (!trainingGroup(chart, asset)) reasons.push('同源歌曲分组待确认')
  if (!difficultyLabelsValid(chart)) reasons.push('目标难度须成对留空或填写合法类别与整数')
  if (chart.training_readiness?.status === 'blocked') {
    const details = chart.training_readiness.reasons
    reasons.push(...(Array.isArray(details) && details.length ? details.map((reason: unknown) => typeof reason === 'string' ? reason : '训练适配检查存在阻塞') : ['训练适配检查尚未通过']))
  }
  return [...new Set(reasons)]
}
