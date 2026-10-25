// SPDX-License-Identifier: GPL-3.0-only
// Independently authored against the pinned public RPE Next API-1 declaration.
const ENDPOINT = 'ws://127.0.0.1:8765/api/v1/bridge/ws';
function semantic(value) {
  if (Array.isArray(value)) return value.map(semantic);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, semantic(value[key])]));
  return value;
}
const sameChart = (left, right) => JSON.stringify(semantic(left)) === JSON.stringify(semantic(right));
async function snapshot(editor) {
  if (!editor.hasDocument || !editor.chart) throw new Error('请先打开谱面');
  const serialized = JSON.stringify(editor.chart);
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(serialized));
  const sha256 = Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
  return {serialized, sha256};
}

export function activate(api) {
  if (api.version !== 1 || typeof api.editor.commit !== 'function' || typeof api.editor.save !== 'function') {
    throw new Error('此桥接需要公开 API 1 的 commit/save 接口');
  }
  let socket = null;
  let connecting = false;
  let applying = false;
  let alive = true;
  const panel = document.createElement('section');
  panel.className = 'pamos-local-bridge';
  panel.dataset.modInteractive = 'true';
  const title = document.createElement('strong');
  title.textContent = 'PAMOs 本地审批桥接 · 待实机验收';
  const description = document.createElement('p');
  description.textContent = '在 PAMOs 生成一次性配对码。连接会将当前谱面 JSON 发送到本机工作台；不会发送音频或曲绘。';
  const code = document.createElement('input');
  code.type = 'password';
  code.autocomplete = 'off';
  code.placeholder = '一次性配对码（5 分钟有效）';
  const connect = document.createElement('button');
  connect.textContent = '配对并发送当前谱面快照';
  const disconnect = document.createElement('button');
  disconnect.textContent = '断开';
  const status = document.createElement('p');
  status.textContent = '未连接';
  panel.append(title, description, code, connect, disconnect, status);
  api.style('.pamos-local-bridge{position:fixed;right:18px;bottom:24px;width:310px;z-index:9000;background:#162426;color:#edf7ed;padding:16px;border:1px solid #71958c;border-radius:12px;font:13px/1.6 system-ui;box-shadow:0 8px 30px #0005}.pamos-local-bridge input{box-sizing:border-box;width:100%;margin:8px 0;padding:8px}.pamos-local-bridge button{padding:6px 9px;margin:3px;border-radius:5px;cursor:pointer}');
  api.mount(panel);
  const setStatus = text => { if (alive) status.textContent = text; };
  const send = value => { if (alive && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(value)); };
  const close = () => { socket?.close(); socket = null; connecting = false; code.value = ''; setStatus('已断开；没有确认保存的命令不视为成功'); };
  api.listen(disconnect, 'click', close);
  api.listen(connect, 'click', async () => {
    if (connecting || socket?.readyState === WebSocket.OPEN) return;
    const pairing = code.value.trim();
    if (!pairing) { setStatus('请输入配对码'); return; }
    try {
      await snapshot(api.editor);
      connecting = true;
      const currentSocket = new WebSocket(ENDPOINT);
      socket = currentSocket;
      currentSocket.onopen = () => {
        if (!alive) { currentSocket.close(); return; }
        send({type: 'authenticate', pairing_code: pairing});
        code.value = '';
        setStatus('正在认证');
      };
      currentSocket.onerror = () => setStatus('连接失败；请先启动本机 PAMOs 工作台');
      currentSocket.onclose = () => { if (socket === currentSocket) { socket = null; connecting = false; setStatus('连接已关闭'); } };
      currentSocket.onmessage = async event => {
        try {
          if (!alive || event.data.length > 40 * 1024 * 1024) return;
          const message = JSON.parse(event.data);
          if (message.type === 'authenticated') {
            const current = await snapshot(api.editor);
            if (!alive || socket !== currentSocket) return;
            send({type: 'snapshot', serialized_chart: current.serialized, editor_sha256: current.sha256});
            connecting = false;
          } else if (message.type === 'snapshot_received') {
            setStatus('已连接。工作台快照：' + message.candidate_id + '；原始谱面未改动');
          } else if (message.type === 'error') {
            setStatus('工作台拒绝：' + String(message.message));
          } else if (message.type === 'apply') {
            if (applying) { send({type: 'ack', command_id: message.command_id, status: 'FAILED', message: '已有保存命令执行中'}); return; }
            applying = true;
            let release = null;
            try {
              const before = await snapshot(api.editor);
              if (!alive || socket !== currentSocket) return;
              if (before.sha256 !== message.expected_editor_sha256) {
                send({type: 'ack', command_id: message.command_id, status: 'CONFLICT', editor_sha256: before.sha256, message: '编辑器内容已变化，请重新配对；没有覆盖任何编辑'});
                return;
              }
              release = api.lockEditing({reason: '正在应用人工批准的 PAMOs 修订'});
              // Recheck synchronously after the digest await. Other mods can edit despite UI locks.
              if (JSON.stringify(api.editor.chart) !== before.serialized) throw new Error('提交前谱面发生变化');
              if (!message.chart || typeof message.chart !== 'object') throw new Error('修订谱面无效');
              api.editor.commit('PAMOs 人工批准修订 ' + String(message.command_id).slice(0, 8), structuredClone(message.chart));
              if (!sameChart(api.editor.chart, message.chart)) throw new Error('编辑器提交钩子取消或改变了已批准内容，请人工核对');
              await api.editor.save();
              if (!alive || socket !== currentSocket) return;
              const after = await snapshot(api.editor);
              const state = api.editor.dirty || !sameChart(api.editor.chart, message.chart) ? 'NEEDS_SAVE' : 'SAVED';
              send({type: 'ack', command_id: message.command_id, status: state, editor_sha256: after.sha256, message: state === 'SAVED' ? '公开 save() 已完成，当前文档无未保存修改' : 'save() 已完成但仍有新修改，请人工确认'});
              setStatus(state === 'SAVED' ? '修订已提交且保存完成。下一轮修改请重新配对。' : '仍有未保存修改，请人工检查；未登记保存成功');
            } catch (error) {
              const current = await snapshot(api.editor).catch(() => null);
              send({type: 'ack', command_id: message.command_id, status: 'NEEDS_SAVE', editor_sha256: current?.sha256, message: String(error?.message || error)});
              setStatus('提交或保存未完成：' + String(error?.message || error) + '。请检查并使用编辑器撤销/保存。');
            } finally {
              release?.();
              applying = false;
            }
          }
        } catch (error) { setStatus('桥接错误：' + String(error?.message || error)); }
      };
    } catch (error) { connecting = false; setStatus(String(error?.message || error)); }
  });
  api.interval(async () => {
    if (applying || socket?.readyState !== WebSocket.OPEN || !alive) return;
    try { const current = await snapshot(api.editor); send({type: 'heartbeat', editor_sha256: current.sha256}); }
    catch { close(); }
  }, 10000);
  api.commands.register({id: 'toggle-panel', title: '显示/隐藏 PAMOs 桥接', run() { panel.hidden = !panel.hidden; }});
  return () => { alive = false; socket?.close(); socket = null; code.value = ''; };
}
