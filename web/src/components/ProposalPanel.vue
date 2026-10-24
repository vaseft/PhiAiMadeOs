<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { state, perform, refresh, label, short } from '../state'
import { beatNumber } from '../timeline'
import type { Candidate, Note, RecordData } from '../types'
const props = defineProps<{ candidate: Candidate; note: Note | null; existing: RecordData[] }>()
const emit = defineEmits<{ committed: [id: string] }>()
const proposal = ref<RecordData | null>(null)
const proposalId = ref('')
const reason = ref(''), delta = ref(0), newKind = ref('TAP'), lane = ref(0), x = ref(0)
const op = ref('MOVE_NOTE_TIME')
const startBeat = ref(0), endBeat = ref(8), instruction = ref(''), confirmExternal = ref(false)
const llm = ref<RecordData>({ enabled: false, configured: false })
const localBeat = computed(() => props.note ? beatNumber(props.note.beat ?? props.note.start_beat) : 0)
const proposed = computed(() => {
  if (!props.note) return null
  let payload: RecordData = {}
  if (op.value === 'MOVE_NOTE_TIME') payload = { new_start_beat: Math.max(0, localBeat.value + delta.value) }
  if (op.value === 'CHANGE_NOTE_KIND') payload = { new_kind: newKind.value }
  if (op.value === 'MOVE_NOTE_X') payload = { new_x: x.value }
  if (op.value === 'MOVE_NOTE_LANE') payload = { new_lane_index: lane.value }
  return { op: op.value, target_id: props.note.id, payload, reason: reason.value.trim() }
})
watch(() => props.note, n => { if (n) { delta.value = 0; newKind.value = n.kind.toUpperCase(); lane.value = n.lane_index || 0; x.value = n.x; op.value = 'MOVE_NOTE_TIME'; startBeat.value = Math.max(0, beatNumber(n.beat) - 4); endBeat.value = beatNumber(n.beat) + 4 } })
watch(() => props.candidate.id, async () => { proposal.value = null; proposalId.value = ''; confirmExternal.value = false; try { llm.value = await api('/settings/llm') } catch { llm.value = { enabled: false, configured: false } } }, { immediate: true })
const recentIds = computed(() => {
  const ids = props.existing.filter(p => p.candidate_id === props.candidate.id).map(p => p.id)
  for (const j of state.jobs) if (j.result?.proposal_ids && (j.candidate_id === props.candidate.id || j.request?.candidate_id === props.candidate.id || j.result?.candidate_id === props.candidate.id)) ids.push(...j.result.proposal_ids)
  return Array.from(new Set(ids.filter(Boolean)))
})
async function load(id = proposalId.value) { if (!id) return; await perform('proposal-read', async () => { proposal.value = await api(`/proposals/${encodeURIComponent(id)}`); proposalId.value = id }) }
async function propose() {
  if (!proposed.value || !props.note) return
  await perform('propose', async () => {
    const p = await api(`/candidates/${props.candidate.id}/proposals`, 'POST', { expected_chart_sha256: props.candidate.chart_sha256, operations: [proposed.value], beat_window: [Math.max(0, localBeat.value - 4), localBeat.value + 4] })
    const id = p.id || p.proposal_id
    if (id) { proposalId.value = id; proposal.value = await api(`/proposals/${id}`) } else proposal.value = p
  }, '局部提案已建立，请先检查差异，再决定是否批准。')
}
async function postprocess() {
  await perform('postprocess', async () => { await api(`/candidates/${props.candidate.id}/postprocess`, 'POST', { beat_window: [startBeat.value, endBeat.value], instruction: instruction.value, confirm_external_upload: true, mode: 'suggest' }); confirmExternal.value = false; await refresh() }, '已提交局部建议任务；结果只形成提案，不会自动修改谱面。')
}
async function approve() { if (!proposal.value) return; await perform('proposal-approve', async () => { await api(`/proposals/${proposal.value!.id || proposalId.value}/approve`, 'POST', {}); await load() }, '已人工批准该提案。仍需点击提交才能创建新版本。') }
async function commit() { if (!proposal.value) return; await perform('proposal-commit', async () => { const r = await api(`/proposals/${proposal.value!.id || proposalId.value}/commit`, 'POST', {}); await refresh(); if (r.candidate_id) emit('committed', r.candidate_id) }, '已创建新候选版本，后续需重新审计与审核。') }
const approved = computed(() => proposal.value?.approved === true || proposal.value?.status?.toLowerCase() === 'approved' || !!proposal.value?.approved_at)
const blocked = computed(() => (proposal.value?.candidate_id && proposal.value.candidate_id !== props.candidate.id) || proposal.value?.validation?.valid === false || proposal.value?.validation?.status === 'BLOCK' || proposal.value?.status?.toLowerCase() === 'rejected')
</script>
<template>
  <section class="panel"><div class="panel-heading"><div><p class="section-kicker">局部修订</p><h2>先看差异，再决定应用。</h2></div><span class="badge outline">创建新版本</span></div><div class="proposal-layout">
    <div><h3>手工调整一个音符</h3><p class="muted small-text">暂停预览并点击一个音符，创建有限范围的修改建议。</p><div v-if="note" class="selected-note"><span class="badge blue">{{ note.kind }}</span><strong>{{ note.id }}</strong><span>第 {{ localBeat.toFixed(3) }} 拍 · {{ note.time_s.toFixed(3) }} 秒</span></div><div v-else class="empty small"><span class="empty-icon">⊙</span><strong>还未选中音符</strong><p>在上方参考预览中点击音符。</p></div>
      <div v-if="note" class="form-grid"><div class="field"><label>调整项目</label><select v-model="op"><option value="MOVE_NOTE_TIME">音符时间</option><option v-if="note.kind.toUpperCase() !== 'HOLD'" value="CHANGE_NOTE_KIND">非长条音符类型</option><option v-if="candidate.chart_mode === 'pure_keys'" value="MOVE_NOTE_LANE">固定键位</option><option v-else value="MOVE_NOTE_X">横向位置</option></select></div><div class="field"><label>{{ op === 'MOVE_NOTE_TIME' ? '时间偏移（拍）' : op === 'CHANGE_NOTE_KIND' ? '调整为' : op === 'MOVE_NOTE_LANE' ? '目标键位' : '谱面横坐标' }}</label><input v-if="op === 'MOVE_NOTE_TIME'" v-model.number="delta" type="number" min="-.125" max=".125" step=".03125"><select v-else-if="op === 'CHANGE_NOTE_KIND'" v-model="newKind"><option>TAP</option><option>DRAG</option><option>FLICK</option></select><select v-else-if="op === 'MOVE_NOTE_LANE'" v-model.number="lane"><option v-for="k in candidate.key_count || 4" :key="k" :value="k-1">第 {{ k }} 键</option></select><input v-else v-model.number="x" type="number" min="-2000" max="2000" step="1"></div><div class="field span-2"><label>修改理由</label><input v-model="reason" placeholder="说明为什么需要修改，至少 8 个字" maxlength="500"></div></div><button class="button secondary" :disabled="!note || reason.trim().length < 8 || Math.abs(delta) > .125 || state.busy.propose" @click="propose">建立局部提案</button>
      <div class="divider"></div><h3>可选：让外部 API 提出局部建议</h3><p class="muted small-text">仅发送所选拍范围的脱敏结构、局部审计证据和你的要求。不会发送音频或完整曲库。</p><p v-if="!llm.enabled || !llm.configured" class="soft-callout muted">外部 API 尚未启用或未配置密钥。可在“连接与设置”中配置。</p><template v-else><div class="form-grid"><div class="field"><label>起始拍</label><input v-model.number="startBeat" type="number" min="0" step=".25"></div><div class="field"><label>结束拍（范围最多 16 拍）</label><input v-model.number="endBeat" type="number" :min="startBeat + .25" step=".25"></div></div><div class="field"><label>希望改善什么</label><textarea v-model="instruction" rows="3" maxlength="2000" placeholder="例如：检查这一段的同列长条冲突，保留音乐重音。"></textarea></div><div class="external-summary"><strong>将发送给 {{ llm.provider }} / {{ llm.model }}</strong><p>候选 {{ short(candidate.id) }} · 第 {{ startBeat }}–{{ endBeat }} 拍 · 当前版本哈希 {{ short(candidate.chart_sha256) }}</p><p>内容：局部音符、生成条件、局部审计证据摘要与上述要求。输出上限 {{ llm.max_tokens }} tokens。</p><label class="checkbox"><input v-model="confirmExternal" type="checkbox"><span>我已查看摘要，同意本次将这些局部资料发送给该服务。</span></label></div><button class="button secondary" :disabled="!confirmExternal || !instruction.trim() || endBeat <= startBeat || endBeat - startBeat > 16 || startBeat < 0 || state.busy.postprocess" @click="postprocess">请求局部建议</button></template>
    </div>
    <div class="proposal-review"><h3>差异与人工批准</h3><div class="field"><label>查看已有提案</label><div class="input-action"><select v-if="recentIds.length" v-model="proposalId"><option value="" disabled>选择提案</option><option v-for="id in recentIds" :key="id" :value="id">{{ short(id) }}</option></select><input v-else v-model="proposalId" placeholder="输入任务结果中的提案 ID"><button class="button secondary" :disabled="!proposalId || state.busy['proposal-read']" @click="load()">读取</button></div></div><div v-if="!proposal" class="empty"><span class="empty-icon">⇄</span><strong>提案不会自动生效</strong><p>建立或选择一份提案，在这里检查差异、校验与版本哈希。</p></div><template v-else><div class="row between"><span class="badge" :class="blocked ? 'red' : approved ? 'green' : 'amber'">{{ blocked ? '校验阻断' : approved ? '已人工批准' : '待人工批准' }}</span><code>{{ short(proposal.id || proposalId) }}</code></div><p class="micro muted">基于版本 {{ short(proposal.base_revision || proposal.candidate_id) }} · {{ short(proposal.base_chart_sha256 || proposal.expected_chart_sha256 || candidate.chart_sha256) }}</p><div class="diff-view"><h4>本次差异</h4><pre>{{ JSON.stringify(proposal.diff || proposal.preview || proposal.operations, null, 2) }}</pre></div><details open><summary>本地校验结果</summary><pre>{{ JSON.stringify(proposal.validation || { status: proposal.status, message: '服务未提供详细校验结果，请核对后再批准。' }, null, 2) }}</pre></details><div class="button-group"><button class="button secondary" :disabled="blocked || approved || state.busy['proposal-approve']" @click="approve">我已查看差异，批准</button><button class="button primary" :disabled="!approved || blocked || state.busy['proposal-commit'] || proposal.status?.toLowerCase() === 'committed'" @click="commit">提交为新版本</button></div><p class="field-hint">提交会再次检查版本哈希与约束，并对新版本重新审计。旧谱面和评分会保留。</p></template></div>
  </div></section>
</template>
