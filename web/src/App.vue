<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { state, refresh, activeJob, label, short } from './state'
import GeneratePage from './pages/GeneratePage.vue'
import LibraryPage from './pages/LibraryPage.vue'
import ReviewPage from './pages/ReviewPage.vue'
import TrainingPage from './pages/TrainingPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import JobList from './components/JobList.vue'
const page = ref('generate')
const selected = ref('')
const items = [
  { id: 'generate', title: '创作与生成', hint: '从音乐开始', icon: '✦' },
  { id: 'review', title: '审核工作台', hint: '听音、预览与评分', icon: '▤' },
  { id: 'library', title: '本地素材库', hint: '素材与使用许可', icon: '▧' },
  { id: 'training', title: '数据集与训练', hint: '从授权数据学习', icon: '⌘' },
  { id: 'jobs', title: '任务中心', hint: '进度与运行记录', icon: '◷' },
  { id: 'settings', title: '连接与设置', hint: '可选 API 与编辑器', icon: '⚙' },
]
const current = computed(() => items.find(i => i.id === page.value)!)
const running = computed(() => state.jobs.filter(activeJob).length)
let timer: ReturnType<typeof setTimeout>
let disposed = false
async function poll() { if (disposed) return; await refresh(); if (!disposed) timer = setTimeout(poll, 3500) }
onMounted(async () => { await refresh(true); timer = setTimeout(poll, 3500) })
onUnmounted(() => { disposed = true; clearTimeout(timer) })
function openCandidate(id: string) { selected.value = id; page.value = 'review' }
</script>
<template>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="#" @click.prevent="page = 'generate'"><span class="brand-mark">P<span>·</span></span><div><strong>PhiAiMadeOs</strong><small>LOCAL CHART STUDIO</small></div></a>
      <div class="workspace-label">个人工作空间 <span>本机</span></div>
      <nav aria-label="主导航"><button v-for="item in items" :key="item.id" :class="['nav-item', { active: page === item.id }]" @click="page = item.id"><span class="nav-icon">{{ item.icon }}</span><span>{{ item.title }}<small>{{ item.hint }}</small></span><i v-if="item.id === 'jobs' && running" class="nav-count">{{ running }}</i></button></nav>
      <div class="sidebar-bottom"><div class="row"><span :class="['status-dot', state.connected ? 'green-dot' : 'error-dot']"></span><strong>{{ state.connected ? '本地服务已连接' : '本地服务未连接' }}</strong></div><p>{{ state.status.version ? `工作台 ${state.status.version}` : '等待本机服务响应' }}</p><button class="button subtle full" :disabled="state.loading" @click="refresh(true)">{{ state.loading ? '连接中…' : '重新连接 / 刷新' }}</button><span class="privacy-note">素材保存在本机。外部 API 默认关闭。</span></div>
    </aside>
    <div class="main-shell">
      <header class="topbar"><div class="breadcrumb">工作空间 <span>/</span> {{ current.title }}</div><div class="row"><span class="local-pill"><span class="status-dot green-dot"></span>本地优先</span><button class="icon-button" aria-label="刷新数据" title="刷新数据" @click="refresh(true)">↻</button><span class="avatar">我</span></div></header>
      <main>
        <div v-if="!state.connected" class="connection-banner"><strong>尚未连接本地服务</strong><span>请先启动 PhiAiMadeOs 本地工作台。已填写的内容会保留在当前页面，连接后可继续。</span></div>
        <GeneratePage v-if="page === 'generate'" @open-candidate="openCandidate" @library="page = 'library'" @jobs="page = 'jobs'" />
        <LibraryPage v-if="page === 'library'" @open-candidate="openCandidate" />
        <KeepAlive><ReviewPage v-if="page === 'review'" v-model:selected="selected" /></KeepAlive>
        <TrainingPage v-if="page === 'training'" />
        <SettingsPage v-if="page === 'settings'" />
        <template v-if="page === 'jobs'"><div class="page-heading"><div><p class="eyebrow">TASK CENTER</p><h1>每一步，都有记录。</h1><p class="subtitle">查看本机任务的实际进度、日志与结果。GPU 任务依次执行。</p></div><span class="badge blue">{{ running }} 项进行中</span></div><div class="panel"><JobList /></div></template>
        <footer class="footer"><span>PhiAiMadeOs <span class="muted">/ 本地谱面工作台</span></span><span>独立审计 · 人工审核 · 版本可追溯</span></footer>
      </main>
    </div>
    <div class="notice-stack" aria-live="polite"><article v-for="n in state.notices" :key="n.id" :class="['notice', n.tone]"><div><strong>{{ n.text }}</strong><small v-if="n.detail">{{ n.detail }}</small></div><button aria-label="关闭提示" @click="state.notices = state.notices.filter(x => x.id !== n.id)">×</button></article></div>
  </div>
</template>
