const prefix = '/api/v1'
let token = ''
let opening: Promise<void> | undefined
export class ApiError extends Error {
  constructor(message: string, public code: string, public status: number, public detail?: unknown) { super(message); this.name = 'ApiError' }
}
export async function openSession(force = false) {
  if (token && !force) return
  if (opening) return opening
  opening = (async () => {
    let res: Response
    try { res = await fetch(`${prefix}/session`, { credentials: 'same-origin', cache: 'no-store' }) }
    catch { throw new ApiError('无法建立本机会话，请先启动本地工作台服务。', 'NETWORK_ERROR', 0) }
    if (!res.ok) throw new ApiError('无法建立本机会话，请确认本地服务正在运行。', 'SESSION_UNAVAILABLE', res.status)
    const data = await res.json()
    if (!data.csrf_token) throw new ApiError('本地服务未返回会话凭据。', 'SESSION_INVALID', res.status)
    token = data.csrf_token
  })().finally(() => { opening = undefined })
  return opening
}
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  await openSession()
  const headers: Record<string, string> = { 'X-PAMOS-Token': token }
  const options: RequestInit = { method, headers, credentials: 'same-origin', cache: 'no-store' }
  if (body instanceof FormData) options.body = body
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body) }
  let res: Response
  try { res = await fetch(prefix + path, options) }
  catch { throw new ApiError('无法连接本地服务。请检查工作台服务，并使用“重新连接”。', 'NETWORK_ERROR', 0) }
  let data: any
  try { data = await res.json() } catch { data = null }
  if (!res.ok) {
    const detail = data?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || data?.message || (res.status === 404 ? '此记录或接口暂不可用。' : `本地服务返回错误 (${res.status})。`)
    throw new ApiError(message, detail?.code || `HTTP_${res.status}`, res.status, detail)
  }
  return data as T
}
export const audioUrl = (id: string) => `${prefix}/assets/${encodeURIComponent(id)}/audio`
export const chartUrl = (id: string) => `${prefix}/candidates/${encodeURIComponent(id)}/chart`
export function safeDownload(url: string) {
  const u = new URL(url, window.location.origin)
  if (u.origin !== window.location.origin || !u.pathname.startsWith('/api/')) throw new Error('服务返回的下载地址不属于本地工作台。')
  return u.pathname + u.search
}
