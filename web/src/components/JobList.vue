<script setup lang="ts">
import { computed, reactive } from 'vue'
import { api } from '../api'
import { state, activeJob, jobState, label, perform, refresh, short, date } from '../state'
const props = defineProps<{ compact?: boolean }>()
const jobs = computed(() => props.compact ? state.jobs.slice(0, 4) : state.jobs)
const details = reactive<Record<string, any>>({})
async function readJob(id: string) { await perform(`job-detail-${id}`, async () => { details[id] = await api(`/jobs/${id}`) }) }
function progress(job: any) { const v = Number(job.progress); return Number.isFinite(v) ? Math.max(0, Math.min(100, v <= 1 ? v * 100 : v)) : 0 }
async function cancel(id: string) { await perform(`cancel-${id}`, async () => { await api(`/jobs/${id}/cancel`, 'POST', {}); await refresh() }, '已申请取消，等待任务安全退出。') }
</script>
<template>
  <div class="job-list">
    <div v-if="!jobs.length" class="empty small"><span class="empty-icon">◷</span><strong>当前没有任务</strong><p>导入、生成和训练的进度会显示在这里。</p></div>
    <article v-for="job in jobs" :key="job.id" class="job-card">
      <div class="row between"><div class="row"><span class="status-dot" :class="activeJob(job) ? 'busy-dot' : jobState(job) === 'failed' ? 'error-dot' : ''"></span><strong>{{ label(job.kind || job.type || '本地任务') }}</strong></div><span class="badge" :class="jobState(job) === 'failed' ? 'red' : activeJob(job) ? 'blue' : ''">{{ label(jobState(job)) }}</span></div>
      <p class="muted job-message">{{ job.message || job.phase || job.stage || '服务未提供阶段说明' }}</p>
      <div v-if="activeJob(job)" class="progress"><i :style="{ width: progress(job) + '%' }"></i></div>
      <div class="row between micro muted"><span>{{ short(job.id) }} · {{ date(job.created_at) }}</span><span v-if="activeJob(job)">{{ progress(job).toFixed(0) }}%</span></div>
      <p v-if="job.error" class="inline-error">{{ typeof job.error === 'string' ? job.error : job.error.message || JSON.stringify(job.error) }}</p>
      <details v-if="!compact" @toggle="($event.target as HTMLDetailsElement).open && readJob(job.id)"><summary>查看真实日志与结果</summary><button class="text-button" :disabled="state.busy[`job-detail-${job.id}`]" @click="readJob(job.id)">刷新实际日志</button><pre>{{ details[job.id]?.logs || (details[job.id] ? JSON.stringify(details[job.id].result || details[job.id], null, 2) : '正在读取本机任务记录…') }}</pre></details>
      <button v-if="activeJob(job)" class="button subtle small-button" :disabled="state.busy[`cancel-${job.id}`] || ['cancelling','cancel_requested'].includes(jobState(job))" @click="cancel(job.id)">取消任务</button>
    </article>
  </div>
</template>
