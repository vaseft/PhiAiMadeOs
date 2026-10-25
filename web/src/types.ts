export type RecordData = Record<string, any>
export interface Asset extends RecordData { id: string; name: string; duration_s?: number; license_status: string; allowed_actions: string[] }
export interface Chart extends RecordData { id: string; name: string; music_asset_id?: string | null; chart_mode: string; key_count?: number; difficulty_class?: string | null; difficulty_value?: number | null; source_type?: string; source_format?: string; source_level?: string; source_difficulty_value?: number | null; import_status?: 'ready' | 'archived_only'; candidate_id?: string | null; license_status: string; allowed_actions: string[] }
export interface Candidate extends RecordData { id: string; music_asset_id: string; chart_mode: string; key_count?: number; chart_sha256: string; conditions: RecordData; status: string; parent_id?: string; manifest?: RecordData }
export interface Job extends RecordData { id: string; kind?: string; state?: string; status?: string; progress?: number; message?: string }
export interface Note extends RecordData { id: string; line_id: string; kind: string; time_s: number; end_time_s?: number; x: number; above?: number; fake?: boolean; lane_index?: number }
export interface Timeline extends RecordData { notes: Note[]; judge_lines: RecordData[]; bpm_map: RecordData[]; offset_ms: number; duration_s: number; chart_mode: string; key_count?: number }
export interface Audit extends RecordData { status: string; issues: RecordData[]; metrics?: RecordData; engine_version?: string }
export interface ScoreField { key: string; name: string; max: number; hint: string }
export const scoreFields: ScoreField[] = [
  { key: 'rhythm', name: '节奏契合', max: 25, hint: '音符与节奏、音乐结构是否一致' },
  { key: 'playability', name: '手感与可玩性', max: 25, hint: '触控手法与交互是否合理' },
  { key: 'readability', name: '可读性', max: 20, hint: '能否看清与预判音符' },
  { key: 'expression', name: '音乐表现', max: 15, hint: '判定线与配置对音乐的表达' },
  { key: 'difficulty', name: '难度匹配', max: 10, hint: '实际体验是否符合所选难度' },
  { key: 'completeness', name: '完整性', max: 5, hint: '结构、结尾与段落是否完整' },
]
