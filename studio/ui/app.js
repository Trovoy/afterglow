'use strict';
const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;
const state = { connected: false, config: null, shows: [], showSel: null, show: null, ed: null, ports: [], profiles: [], prof: null };

// ---------- motion (GSAP-style eases on the Web Animations API) ----------
const EASE = { out: 'cubic-bezier(0.16,1,0.3,1)', p3out: 'cubic-bezier(0.215,0.61,0.355,1)', p3in: 'cubic-bezier(0.55,0.055,0.675,0.19)', inOut: 'cubic-bezier(0.65,0,0.35,1)' };
const CALM = matchMedia('(prefers-reduced-motion: reduce)').matches;
const T = (ms) => (CALM ? 0 : ms);
function after(o, a, ms, fn) { const t = o._tok = (o._tok || 0) + 1; const f = () => { if (o._tok !== t) return; o._tok++; fn(); }; a.onfinish = f; setTimeout(f, ms + 80); }
function showModal(id) { const m = $(id), c = m.firstElementChild; m._tok = (m._tok || 0) + 1; m.getAnimations({ subtree: true }).forEach(a => a.cancel());
  if (m.classList.contains('show') && !m._closing) return; m._closing = false; m.classList.add('show');
  m.animate({ opacity: [0, 1] }, { duration: T(260), easing: EASE.p3out });
  c.animate({ opacity: [0, 1], transform: ['translateY(24px) scale(.96)', 'none'] }, { duration: T(560), easing: EASE.out }); }
function hideModal(id) { const m = $(id), c = m.firstElementChild; if (!m.classList.contains('show') || m._closing) return; m._closing = true;
  const a = m.animate({ opacity: [1, 0] }, { duration: T(240), easing: EASE.p3in, fill: 'forwards' });
  c.animate({ transform: ['none', 'translateY(12px) scale(.98)'] }, { duration: T(240), easing: EASE.p3in, fill: 'forwards' });
  after(m, a, T(240), () => { m.classList.remove('show'); m.getAnimations({ subtree: true }).forEach(x => x.cancel()); m._closing = false; }); }
function toast(msg, kind = '') {
  const t = document.createElement('div'); t.className = 'toast ' + kind; t.textContent = msg;
  $('toasts').appendChild(t);
  t.animate({ opacity: [0, 1], transform: ['translateX(28px)', 'none'] }, { duration: T(520), easing: EASE.out });
  setTimeout(() => { const a = t.animate({ opacity: [1, 0], transform: ['none', 'translateX(16px)'] }, { duration: T(260), easing: EASE.p3in, fill: 'forwards' });
    after(t, a, T(260), () => t.remove()); }, 4200);
}
function movePill(a, instant) { const p = $('nav-pill'); if (!p || !a) return; const nav = a.parentElement;
  const to = { top: a.offsetTop + 'px', height: a.offsetHeight + 'px' }; const from = { top: p.style.top || to.top, height: p.style.height || to.height };
  p.style.top = to.top; p.style.height = to.height; if (!instant) p.animate([from, to], { duration: T(480), easing: EASE.out }); }
function enterPage(page) { const items = page.querySelectorAll(':scope > h1, :scope > .sub, :scope > .card, :scope > .grid > .card, :scope > .row, :scope > .console');
  items.forEach((el, i) => el.animate({ opacity: [0, 1], transform: ['translateY(14px)', 'none'] }, { duration: T(520), delay: T(Math.min(i, 8) * 45), easing: EASE.out, fill: 'backwards' })); }
async function call(name, ...args) {
  const r = await api()[name](...args);
  if (r && r.ok === false && r.err) { toast(r.err, 'err'); }
  return r;
}
const fmtT = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;

// same wording as the phone page's device info
const RESET = { poweron: '正常通电', software: '软件重启（更新或重启）', task_wdt: '看门狗自动恢复', int_wdt: '看门狗自动恢复', wdt: '看门狗自动恢复',
  panic: '程序异常后自动恢复', brownout: '供电不足（检查 USB 线或电源）', external: '复位按键', deepsleep: '休眠唤醒', unknown: '未知' };
function upTime(t) { const d = Math.floor(t / 86400), h = Math.floor(t % 86400 / 3600), m = Math.floor(t % 3600 / 60);
  return (d ? d + ' 天 ' : '') + (d || h ? h + ' 小时 ' : '') + m + ' 分钟'; }
// ---------- navigation ----------
document.querySelectorAll('nav a').forEach(a => a.onclick = () => {
  if (a.classList.contains('active')) return;
  document.querySelectorAll('nav a').forEach(x => x.classList.toggle('active', x === a)); movePill(a);
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + a.dataset.page));
  enterPage($('page-' + a.dataset.page));
  const pg = a.dataset.page;
  if (pg === 'shows') { loadShows().then(loadDevShows); drawTL(); }
  if (pg === 'flash') { loadPackages(); }
  if (pg === 'profiles') { loadProfiles(); }
  if (pg === 'log') { api().get_log().then(l => { $('log').textContent = l.join('\n'); $('log').scrollTop = 1e9; }); }
  if (pg === 'music') { loadLoopDevices(); }
});

// ---------- backend events ----------
window.onBackend = (e) => {
  switch (e.type) {
    case 'log': { const el = $('log'); el.textContent += (el.textContent ? '\n' : '') + e.line; if (el.textContent.length > 120000) el.textContent = el.textContent.slice(-80000); el.scrollTop = 1e9; break; }
    case 'mic': $('mic-meter').style.width = Math.min(100, e.level * 400) + '%'; $('m-level').textContent = e.level.toFixed(3);
      rhythm({ mic: e.mic, bpm: e.bpm, beats: e.beats }, 'x'); break;
    case 'loop_level': $('loop-meter').style.width = Math.min(100, e.level * 100) + '%'; setLive(e.rgb); break;
    case 'disconnected': toast('控制器已断开：' + (e.msg || ''), 'err'); setConnected(null); break;
    case 'device_event': if (e.evt === 'wake_done') toast('唤醒完成'); if (e.evt === 'tx_error') toast('发射错误：' + (e.msg || ''), 'err'); break;
    case 'flash_log': { const el = $('flash-log'); el.textContent += e.line + '\n'; el.scrollTop = 1e9; break; }
    case 'flash_progress': flashProgress(e); break;
    case 'flash_done': if (guide.flashing) { guideFlashDone(e); break; }
      flashDone(e); scanFlash(); break;
    case 'build_log': $('g-log').textContent = e.line; break;
    case 'device_show_done': if (e.ok) { toast('已写入控制器，可在手机上播放', 'ok'); loadDevShows(); } else toast('写入失败：' + e.err, 'err'); break;
    case 'build_done': if (e.ok) { toast('复刻生成完成：' + e.name, 'ok'); loadShows(); } else toast('生成失败：' + e.err, 'err'); break;
    case 'show_pos': if (state.ed) { state.ed.playhead = e.pos; $('ed-pos').textContent = fmtT(e.pos); drawTL(); } break;
    case 'show_video': openShowVideo(e); break;
    case 'show_state': if (e.state === 'stopped') closeShowVideo(true); if (e.state === 'waking') toast('正在唤醒手环，30 秒后开始播放'); if (e.state === 'stopped' && state.ed) { state.ed.playhead = null; drawTL(); } break;
    case 'toast': toast(e.msg, e.kind || ''); break;
  }
};

// ---------- devices ----------
const ICON_CHIP = '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9z"/></svg>';
async function scan() {
  $('dev-list').innerHTML = '<div class="empty">扫描中…</div>';
  const r = await call('scan'); if (!r.ok) return;
  const list = r.data;
  if (!list.length) {
    $('dev-list').innerHTML = '<div class="empty">正在分析原因…</div>';
    const h = await api().scan_hint();
    $('dev-list').innerHTML = fixHTML(h); return;
  }
  $('dev-list').innerHTML = '';
  list.forEach(d => {
    const el = document.createElement('div'); el.className = 'item';
    let pill = '<span class="pill">还没刷固件</span>';
    if (d.busy) pill = '<span class="pill warn" title="关掉其他正在使用它的程序后重新扫描">被其他程序占用</span>';
    if (d.fw) pill = `<span class="pill ${d.connected ? 'ok' : 'acc'}">${d.connected ? '已连接 · ' : ''}固件 ${d.ver}${d.state === 'old' ? ' · 可更新' : ''}</span>`;
    const btn = d.fw && !d.connected ? '<button class="primary">连接</button>' : (d.state === 'blank' ? '<button class="primary">刷入固件</button>' : '');
    el.innerHTML = `<div class="ico">${ICON_CHIP}</div><div style="flex:1"><b>${d.port}</b><div class="mut small">${d.desc}${d.mac ? ' · ' + d.mac : ''}</div></div>${pill}${btn}`;
    const b = el.querySelector('button'); if (b) b.onclick = () => d.fw ? connect(d.port) : openGuide(d.port);
    $('dev-list').appendChild(el);
  });
}
async function connect(port) {
  const r = await call('connect', port);
  if (r.ok) { toast('已连接 ' + port, 'ok'); setConnected(r.data); scan(); loadConfig(); }
}
function setConnected(info) {
  state.connected = !!info;
  $('sb-dot').className = 'dot' + (info ? ' on' : '');
  $('sb-title').textContent = info ? 'Afterglow 控制器' : '未连接';
  $('sb-sub').textContent = info ? `固件 ${info.ver}${info.ssid ? ' · ' + info.ssid : ''}` : '在“设备”页连接控制器';
  $('dev-pill').innerHTML = info ? '<span class="pill ok">已连接</span>' : '<span class="pill">未连接</span>';
  $('dev-meta').textContent = info ? `固件 ${info.ver} · 协议 ${info.proto} · ${info.built}` : '连接后显示固件版本和状态';
  if (!info) { $('dev-mode').textContent = '—'; setLive([0, 0, 0]); }
}
const MODE = { off: '熄灭', hold: '固定颜色', mic: '跟随音乐', stream: '电脑控制' };
let lastBeats = 0, lastBeatT = 0;
function rhythm(s, pre) {
  const now = Date.now(); if (s.beats !== lastBeats) { lastBeats = s.beats; lastBeatT = now; }
  const hearing = s.mic && s.bpm > 0 && now - lastBeatT < 4000; const b = Math.round(s.bpm || 0);
  const tempo = hearing ? (b >= 140 ? '快节奏' : b >= 95 ? '中速' : '慢节奏') : '未检测到节奏';
  [[pre + '-beat', pre + '-bpm'], ['m-beat', 'm-bpm']].forEach(([d, t]) => { const dot = $(d), txt = $(t); if (!dot) return;
    dot.className = 'beat' + (hearing ? ' go' : ''); dot.style.setProperty('--p', hearing ? (60 / s.bpm).toFixed(3) + 's' : '1s');
    txt.innerHTML = hearing ? `${b}<small style="font-size:12px;color:#8b93a7;margin-left:3px">拍/分</small>` : '—'; });
  if ($(pre + '-tempo')) $(pre + '-tempo').textContent = tempo; $('m-tempo').textContent = hearing ? tempo : '—';
}
function colourFromStatus(s) {
  const hold = s.mode === 'hold' && s.color; markSwatch(hold ? s.color : '');
  if (hold) { const sw = [...document.querySelectorAll('#swatches .sw')].find(e => e.dataset.hex === s.color);
    $('dev-mode').textContent = '固定颜色 · ' + (sw ? sw.dataset.n : '自定义'); const v = [1, 3, 5].map(i => parseInt(s.color.substr(i, 2), 16)); setLive(v); }
  else if (s.mode === 'off') setLive([0, 0, 0]);
}
const hexOf = (r, g, b) => '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
function markSwatch(h) { document.querySelectorAll('#swatches .sw').forEach(e => e.classList.toggle('sel', e.dataset.hex === h)); }
async function poll() {
  if (!state.connected) return;
  const r = await api().status();
  if (!r.connected) { setConnected(null); return; }
  if (!r.ok) return;
  const s = r.data;
  $('dev-mode').textContent = MODE[s.mode] || s.mode;
  $('st-mic').textContent = s.mic ? '正常' : '未检测到';
  rhythm(s, 'st'); colourFromStatus(s);
  const v = Math.min(100, Math.round((s.level || 0) / 0.03 * 100)); $('st-vol').style.width = v + '%';
  $('st-volt').textContent = v < 15 ? '安静' : v < 50 ? '适中' : '较大';
  $('st-freq').textContent = s.freq.toFixed(3);
  $('st-dbm').textContent = s.dbm;
  $('st-wifi').textContent = s.wifi_clients;
  $('st-health').textContent = s.uptime_s == null ? '' : `已运行 ${upTime(s.uptime_s)} · 开机 ${s.boots ?? '—'} 次 · 上次启动：${RESET[s.reset] || s.reset || '—'}`;
  $('sb-dot').className = 'dot ' + (s.mode !== 'off' ? 'tx' : 'on');
}
setInterval(poll, 1000);
$('btn-scan').onclick = scan;
$('btn-disconnect').onclick = async () => { await call('disconnect'); setConnected(null); scan(); };

function setLive(rgb) {
  const [r, g, b] = rgb; $('live-dot').style.background = `rgb(${r},${g},${b})`;
  $('live-dot').style.boxShadow = `0 0 0 4px #12151b, 0 0 ${r + g + b > 30 ? 46 : 0}px rgb(${r},${g},${b})`;
}

// ---------- control ----------
const SW = [['红', 255, 0, 0], ['橙', 255, 80, 0], ['黄', 255, 200, 0], ['绿', 0, 255, 0], ['青', 0, 255, 255], ['蓝', 0, 0, 255], ['紫', 200, 0, 255], ['粉', 255, 0, 120], ['白', 255, 255, 255]];
SW.forEach(([n, r, g, b]) => {
  const el = document.createElement('div'); el.className = 'sw' + (0.2126 * r + 0.7152 * g + 0.0722 * b < 140 ? ' dark' : '');   // label colour by perceived brightness
  el.dataset.n = n; el.style.background = `rgb(${r},${g},${b})`;
  el.style.boxShadow = 'none';
  el.dataset.hex = hexOf(r, g, b);
  el.onclick = async () => { const res = await call('color', r, g, b); if (res.ok) { setLive([r, g, b]); markSwatch(el.dataset.hex); toast('已切换为' + n + '色', 'ok'); } };
  $('swatches').appendChild(el);
});
$('btn-custom').onclick = () => { const h = $('custom-color').value; const v = [1, 3, 5].map(i => parseInt(h.substr(i, 2), 16)); call('color', ...v).then(r => r.ok && setLive(v)); };
$('btn-off').onclick = () => call('off').then(r => r.ok && setLive([0, 0, 0]));
$('btn-wake').onclick = () => call('command', 'wake 30').then(r => r.ok && toast('正在唤醒手环（约 30 秒）'));

// ---------- music ----------
const STYLES = [[4, '演唱会'], [3, '综合'], [0, '脉冲'], [1, '换色'], [2, '音量']];
STYLES.forEach(([v, n]) => { const b = document.createElement('button'); b.textContent = n; b.dataset.v = v;
  b.onclick = () => setKey('mstyle', v).then(() => markSeg('style-seg', v)); $('style-seg').appendChild(b); });
function markSeg(id, v) { document.querySelectorAll(`#${id} button`).forEach(b => b.classList.toggle('on', b.dataset.v == v)); }
async function setKey(k, v) { const r = await call('set_key', k, v); if (r.ok && state.config) state.config[k] = v; return r; }
function bindSlider(key, fmt = (v) => v) {
  const s = $('s-' + key), out = $('v-' + key);
  s.oninput = () => out.textContent = fmt(s.value);
  s.onchange = () => setKey(key, s.value);
}
const SLIDERS = {
  'music-sliders': [['msens', '灵敏度', '数值越小越灵敏', 1.05, 4, 0.05, 1.8, ''], ['bright', '亮度', '', 10, 255, 5, 200, ''],
    ['mbase', '底光', '演唱会效果节拍间亮度', 0, 60, 5, 0, '%'], ['mhold', '脉冲时长', '脉冲效果每次点亮的时长', 40, 600, 10, 120, 'ms']],
  'power-sliders': [['pchan', '单色上限', '', 20, 100, 5, 80, '%'], ['psum', '三色合计上限', '', 30, 300, 5, 125, '%']] };
const SL = {};
Object.entries(SLIDERS).forEach(([box, list]) => list.forEach(([k, label, hint, mn, mx, st, def, u]) => {
  const pos = (def - mn) / (mx - mn);
  const w = document.createElement('div'); w.className = 'slider';
  w.innerHTML = `<span class="lab">${label}<small>默认 ${def}${u}${hint ? ' · ' + hint : ''}</small></span>
    <div class="rw"><i class="tick" style="left:calc(${pos * 100}% + ${9 - pos * 18}px)"></i><input type="range" id="s-${k}" min="${mn}" max="${mx}" step="${st}" value="${def}"></div>
    <span class="val"><a class="rst" id="r-${k}">↺</a><span id="v-${k}"></span></span>`;
  $(box).appendChild(w);
  const s = $('s-' + k), show = () => { $('v-' + k).textContent = s.value + u; $('r-' + k).style.visibility = Math.abs(s.value - def) < st / 2 ? 'hidden' : 'visible'; };
  s.oninput = show; s.onchange = () => setKey(k, s.value);
  $('r-' + k).title = '恢复默认 ' + def + u;
  $('r-' + k).onclick = () => { s.value = def; show(); setKey(k, def).then(r => r.ok && toast(label + '已恢复默认')); };
  SL[k] = { show, def }; show();
}));
$('btn-reset-music').onclick = () => { SLIDERS['music-sliders'].forEach(([k, , , , , , def]) => { $('s-' + k).value = def; SL[k].show(); setKey(k, def); }); toast('已恢复默认设置，请点击“保存到控制器”使其永久生效'); };
async function loadConfig() {
  const r = await call('config'); if (!r.ok) return;
  const c = state.config = r.data;
  Object.keys(SL).forEach(k => { if (c[k] !== undefined) { $('s-' + k).value = c[k]; SL[k].show(); } });
  markSeg('style-seg', c.mstyle); $('t-auto').checked = !!c.auto; $('t-wifi').checked = !!c.wifi; $('t-ka').checked = !!c.ka; $('t-aoff').checked = !!c.aoff;
}
$('btn-mic').onclick = () => call('mic').then(r => r.ok && toast('开始跟随音乐（控制器麦克风）', 'ok'));
$('t-auto').onchange = (e) => setKey('auto', e.target.checked ? 1 : 0);
$('t-aoff').onchange = (e) => setKey('aoff', e.target.checked ? 1 : 0).then(r => r.ok && call('save') && toast(e.target.checked ? '已开启信号中断后自动熄灭' : '已关闭信号中断后自动熄灭'));
$('t-ka').onchange = (e) => setKey('ka', e.target.checked ? 1 : 0).then(r => r.ok && call('save') && toast(e.target.checked ? '已开启保持唤醒' : '已关闭保持唤醒，使用前请先唤醒手环'));
$('t-mon').onchange = (e) => call('micmon', e.target.checked ? 1 : 0);
$('btn-save').onclick = $('btn-save2').onclick = () => call('save').then(r => r.ok && toast('已保存到控制器', 'ok'));
async function loadLoopDevices() {
  const list = await api().loop_devices();
  if (list.error) { toast(list.error, 'err'); return; }
  $('loop-dev').innerHTML = list.map(d => `<option value="${d.index}">${d.name}</option>`).join('');
}
$('btn-loop-refresh').onclick = loadLoopDevices;
$('btn-loop-start').onclick = () => call('start_loopback', $('loop-dev').value).then(r => r.ok && toast('正在跟随电脑音频', 'ok'));
$('btn-loop-stop').onclick = () => call('stop_loopback').then(() => { $('loop-meter').style.width = '0'; toast('已停止，手环将在 1 秒内熄灭'); });

// ---------- settings ----------
$('t-wifi').onchange = (e) => setKey('wifi', e.target.checked ? 1 : 0).then(r => r.ok && toast('保存并重启后生效'));
$('btn-wifi-pass').onclick = () => setKey('appass', $('wifi-pass').value).then(r => r.ok && toast('密码已修改，保存并重启后生效', 'ok'));
$('btn-factory').onclick = async (e) => { const b = e.currentTarget;
  if (!b.dataset.armed) { b.dataset.armed = 1; b.textContent = '再次点击确认'; setTimeout(() => { delete b.dataset.armed; b.textContent = '恢复出厂设置'; }, 4000); return; }
  await call('off'); await new Promise(r => setTimeout(r, 700)); const r = await call('command', 'factory'); if (!r.ok) return;
  toast('已恢复出厂设置，控制器正在重启', 'ok'); call('command', 'reboot'); setTimeout(() => { setConnected(null); scan(); }, 2500); };
$('btn-reboot').onclick = () => call('command', 'reboot').then(() => { toast('控制器正在重启，请重新连接'); setTimeout(() => { setConnected(null); scan(); }, 2500); });
$('btn-raw').onclick = async () => { const c = $('raw-cmd').value.trim(); if (!c) return; const r = await call('command', c); if (r.ok) toast(JSON.stringify(r.data)); };

// ---------- battery test (same logic as the phone page) ----------
// No time limit: the user judges each level. Coarse 40..100 %, then 5 % steps; limit = last stable - 5 %.
const BAT_COARSE = [40, 55, 70, 85, 100]; let bat = {};
function batShow() { const v = bat.list[bat.i];
  $('bat-phase').textContent = `电池检测 · ${bat.phase === 'coarse' ? '粗测' : '细测'}（${bat.i + 1}/${bat.list.length}）`;
  $('bat-step').textContent = `红色 ${v}%`; $('bat-bar').style.width = v + '%'; call('command', `battest ${Math.round(v * 2.55)} 0 0`); }
function batAnswer(flicker) { const v = bat.list[bat.i];
  if (!flicker) { bat.stable = v; bat.i++; if (bat.i < bat.list.length) return batShow(); return batFinish(bat.phase === 'coarse' && v === 100); }
  if (bat.phase === 'coarse') { const lo = bat.stable === null ? 20 : bat.stable, fine = []; for (let x = lo + 5; x < v; x += 5) fine.push(x);
    if (fine.length) { bat = { phase: 'fine', list: fine, i: 0, stable: bat.stable }; return batShow(); } }
  batFinish(false); }
async function batFinish(allStable) {
  const stable = bat.stable === null ? 20 : bat.stable, q = allStable ? 100 : stable;
  const pchan = allStable ? 100 : Math.max(20, stable - 5), psum = Math.max(30, Math.min(300, Math.round(pchan * 1.56)));
  await setKey('pchan', pchan); await setKey('psum', psum); await call('save'); await call('color', 255, 0, 0);
  $('s-pchan').value = pchan; SL.pchan.show(); $('s-psum').value = psum; SL.psum.show();
  const [lvl, bars, col, adv] = q >= 95 ? ['良好', 4, '#2ecc71', '电池电量充足，所有颜色都能稳定显示。'] : q >= 80 ? ['正常', 3, '#4fa8ff', '电池电量正常，日常使用不受影响。']
    : q >= 55 ? ['偏弱', 2, '#f5b942', '电池电量偏低，红色、橙色等颜色可能出现闪烁。已自动降低亮度以避免闪烁，建议近期更换电池。'] : ['电量不足', 1, '#ff5c6c', '电池电量不足，手环可能频繁闪烁或熄灭。请更换两颗 CR2032 纽扣电池。'];
  const found = allStable ? '全部亮度均稳定显示' : `红色 ${stable}% 及以下稳定显示`;
  const icon = (extra) => `<span class="batt" style="${extra}color:${col}">${[1, 2, 3, 4].map(i => `<i class="${i <= bars ? 'on' : ''}"></i>`).join('')}</span>`;
  $('bat-run').style.display = 'none'; $('bat-done').style.display = 'block'; showModal('bat-modal');
  $('bat-ico').innerHTML = icon('transform:scale(1.8);margin:18px;'); $('bat-title').textContent = '电池' + lvl; $('bat-title').style.color = col;
  $('bat-desc').innerHTML = `${adv}<br><br>检测结果：${found}。已将亮度上限自动调整为 <b>${pchan}%</b>${allStable ? '' : '（预留 5% 余量）'}。当前显示红色，请确认手环是否稳定。`;
  $('bat-res').innerHTML = `<div class="bres" style="background:${col}22;border:1px solid ${col}66">${icon('')}<div><b style="color:${col}">电池${lvl}</b>${adv}<br><span class="mut small">${found} · 亮度上限 ${pchan}%（合计 ${psum}%）</span></div></div>`;
}
$('btn-bat').onclick = () => { if (!state.connected) return toast('请先连接控制器', 'err');
  bat = { phase: 'coarse', list: BAT_COARSE, i: 0, stable: null }; $('bat-run').style.display = 'block'; $('bat-done').style.display = 'none'; showModal('bat-modal'); batShow(); };
$('btn-bat-ok-stable').onclick = () => batAnswer(false);
$('btn-bat-flash').onclick = () => batAnswer(true);
$('btn-bat-cancel').onclick = () => { hideModal('bat-modal'); call('off'); toast('已取消电池检测'); };
$('btn-bat-ok').onclick = () => hideModal('bat-modal');

// ---------- flashing ----------
async function loadPackages() {
  const list = await api().packages();
  $('pkg').innerHTML = list.map(p => `<option value="${p.path}">${p.error ? '损坏：' : ''}固件 ${p.version || ''} ${p.built ? '· ' + p.built.replace('T', ' ') : ''}</option>`).join('');
  $('pkg-info').textContent = list.length ? '已自动选择最新版本，校验通过' : '未找到固件包';
  scanFlash();
}
$('btn-pkg-pick').onclick = async () => { const p = await api().pick_package(); if (!p) return;
  if (p.error) return toast(p.error, 'err');
  const o = document.createElement('option'); o.value = p.path; o.textContent = `固件 ${p.version} · ${p.path}`; $('pkg').prepend(o); $('pkg').value = p.path; };
async function scanFlash() {
  const r = await api().scan(); if (!r.ok) return;
  state.ports = r.data;
  $('flash-ports').innerHTML = r.data.length ? '' : '<div class="empty">未找到串口设备</div>';
  r.data.forEach(d => { const el = document.createElement('label'); el.className = 'item';
    const one = r.data.length === 1 && !d.busy;   // a single board: select it, nobody should have to tick a lone checkbox
    el.innerHTML = `<input type="checkbox" class="check" value="${d.port}"${one ? ' checked' : ''}><div style="flex:1"><b>${d.port}</b><div class="mut small">${d.desc}</div></div>
      <span class="pill ${d.fw ? 'acc' : ''}">${d.fw ? '固件 ' + d.ver + (d.state === 'old' ? ' · 可更新' : '') : (d.busy ? '被占用' : '还没刷固件')}</span>`;
    $('flash-ports').appendChild(el); });
}
$('btn-flash-scan').onclick = scanFlash;
document.querySelectorAll('#flash-mode button').forEach(b => b.onclick = () => markSeg('flash-mode', b.dataset.v));
$('btn-flash').onclick = async () => {
  const ports = [...document.querySelectorAll('#flash-ports input:checked')].map(i => i.value);
  if (!ports.length) return toast('请选择要烧录的控制器', 'err');
  const appOnly = document.querySelector('#flash-mode button.on').dataset.v === 'app';
  $('flash-log').textContent = '';
  if (ports.some(p => state.connected)) setConnected(null);
  const r = await call('flash', ports, $('pkg').value, appOnly); if (r.ok) toast('开始烧录 ' + ports.join('、'));
};
$('btn-ota').onclick = () => { $('flash-log').textContent = ''; call('wifi_update', $('ota-host').value, $('pkg').value); };

// ---------- profiles ----------
const PF = ['name', 'venue', 'pcb', 'freq', 'dbm', 'bitus', 'period', 'notes'];
async function loadProfiles(selectName) {
  state.profiles = await api().profiles();
  $('prof-list').innerHTML = '';
  state.profiles.forEach((p, i) => { const el = document.createElement('div'); el.className = 'item';
    el.innerHTML = `<div class="ico"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg></div>
      <div style="flex:1"><b>${p.name}</b><div class="mut small">${[p.venue, p.freq + ' MHz', p.dbm + ' dBm'].filter(Boolean).join(' · ')}</div></div>`;
    el.onclick = () => showProfile(i); $('prof-list').appendChild(el); });
  const idx = Math.max(0, state.profiles.findIndex(p => p.name === selectName));
  if (state.profiles.length) showProfile(idx);
}
function showProfile(i) {
  state.prof = state.profiles[i];
  document.querySelectorAll('#prof-list .item').forEach((el, j) => el.classList.toggle('sel', i === j));
  PF.forEach(k => $('pf-' + k).value = state.prof[k] ?? '');
}
function formProfile() { const p = { ...(state.prof || {}) }; PF.forEach(k => p[k] = $('pf-' + k).value.trim()); return p; }
$('btn-prof-new').onclick = () => { state.prof = null; PF.forEach(k => $('pf-' + k).value = '');
  Object.assign({}, { freq: 433.92, dbm: 10, bitus: 500, period: 51 }); $('pf-freq').value = 433.92; $('pf-dbm').value = 10; $('pf-bitus').value = 500; $('pf-period').value = 51; $('pf-name').focus(); };
$('btn-prof-save').onclick = async () => { const p = formProfile(); if (!p.name) return toast('名称不能为空', 'err');
  const r = await call('save_profile', p); if (r.ok) { toast('已保存', 'ok'); loadProfiles(p.name); } };
$('btn-prof-del').onclick = async () => { if (!state.prof || !confirm('删除档案 ' + state.prof.name + '？')) return; await call('delete_profile', state.prof); loadProfiles(); };
$('btn-prof-apply').onclick = async () => { const r = await call('apply_profile', formProfile()); if (r.ok) toast('已应用并保存到控制器', 'ok'); };
$('btn-prof-read').onclick = async () => { const r = await call('config'); if (r.ok) ['freq', 'dbm', 'bitus', 'period'].forEach(k => $('pf-' + k).value = r.data[k]); };

// ---------- band adaptation (scan candidate frequencies, user reports response) ----------
let ad = null;
function adFreqs() { const f = +$('ad-from').value, t = +$('ad-to').value, st = +$('ad-step').value, out = [];
  if (!(st > 0) || t < f || f < 433.05 || t > 434.79) return null;
  for (let x = f; x <= t + 1e-6; x += st) out.push(Math.round(x * 10000) / 10000); return out; }
function adChips() { $('ad-chips').innerHTML = ad.list.map((f, i) => { const r = ad.res[i];
  const cls = r === 1 ? 'ok' : r === 0.5 ? 'warn' : r === 0 ? '' : i === ad.i ? 'acc' : ''; return `<span class="pill ${cls}">${f.toFixed(3)}${r === 1 ? ' ✓' : r === 0.5 ? ' ½' : ''}</span>`; }).join(''); }
async function adTest() {
  if (ad.i >= ad.list.length) return adFinish();
  ad.busy = true;   // answers are ignored while the radio switches frequency
  const f = ad.list[ad.i]; $('ad-freq').textContent = f.toFixed(4) + ' MHz'; $('ad-phase').textContent = `${ad.phase === 2 ? '第二轮（低功率，精确定位）' : '第一轮（最大功率，确定范围）'} · 正在测试（${ad.i + 1}/${ad.list.length}）`;
  adChips(); await call('off'); await new Promise(r => setTimeout(r, 700));
  const r = await call('set_key', 'freq', f); if (!r.ok) { adStop(); return; }
  if (!ad) return; ad.busy = false;
  ad.t0 = Date.now(); let k = 0;
  clearInterval(ad.timer);
  ad.timer = setInterval(() => {   // alternate red / blue each second so a response is easy to see
    const left = ad.dwell - (Date.now() - ad.t0) / 1000;
    $('ad-bar').style.width = Math.min(100, (1 - left / ad.dwell) * 100) + '%'; $('ad-left').textContent = `剩余 ${Math.max(0, Math.ceil(left))} 秒`;
    if (left <= 0) { adAnswer(0); return; }
    if (k++ % 4 === 0) call('color', ...(Math.floor(k / 4) % 2 ? [0, 0, 255] : [255, 0, 0]));
  }, 250);
}
function adAnswer(w) { if (!ad || ad.busy) return; clearInterval(ad.timer); ad.res[ad.i] = w; ad.i++; adTest(); }
async function adStop() { if (!ad) return; clearInterval(ad.timer); await call('off'); await new Promise(r => setTimeout(r, 700));
  await call('set_key', 'freq', ad.orig); await call('set_key', 'dbm', ad.origDbm); $('adapt-run').style.display = 'none'; $('adapt-form').style.display = 'flex'; ad = null; toast('已停止适配，已恢复原频率'); }
async function adFinish() {
  clearInterval(ad.timer); await call('off'); adChips();
  let hits = ad.list.filter((f, i) => ad.res[i] > 0);
  if (ad.phase === 1 && hits.length >= 3) {   // too many responses at full power: repeat them at low power to narrow down
    ad.phase1 = { list: ad.list, res: ad.res };
    await new Promise(r => setTimeout(r, 700)); const r = await call('set_key', 'dbm', 0); if (!r.ok) return adStop();
    ad.phase = 2; ad.list = hits; ad.res = hits.map(() => null); ad.i = 0;
    toast('第一轮完成。第二轮将以低功率重新测试有反应的频率，请将手环放在约 30 厘米处。'); return adTest();
  }
  await new Promise(r => setTimeout(r, 700)); await call('set_key', 'dbm', ad.origDbm);
  if (ad.phase === 2 && !hits.length) { hits = ad.list; ad.res = ad.list.map(() => 1); }   // nothing at low power: fall back to phase-1 range
  $('adapt-run').style.display = 'none'; $('adapt-form').style.display = 'flex';
  let best = null;
  if (hits.length) {   // weighted centre (full = 1, partial = 0.5) of the longest run of responding frequencies
    let runs = [], cur = [];
    ad.list.forEach((f, i) => { if (ad.res[i] > 0) cur.push([f, ad.res[i]]); else if (cur.length) { runs.push(cur); cur = []; } }); if (cur.length) runs.push(cur);
    const run = runs.sort((a, b) => b.length - a.length)[0];
    const wsum = run.reduce((a, [, w]) => a + w, 0); best = Math.round(run.reduce((a, [f, w]) => a + f * w, 0) / wsum * 2000) / 2000;
  }
  await new Promise(r => setTimeout(r, 700)); await call('set_key', 'freq', best ?? ad.orig);
  const box = $('ad-result'); box.style.display = 'block';
  if (best === null) { box.innerHTML = `<div class="bres" style="background:#ff5c6c22;border:1px solid #ff5c6c66"><div><b style="color:#ff8a96">未找到有效频率</b>在测试范围内手环均无反应。请将手环靠近控制器，扩大频率范围或延长每个频率的测试时间后重试。已恢复原频率。</div></div>`; ad = null; return; }
  box.innerHTML = `<div class="bres" style="background:#2ecc7122;border:1px solid #2ecc7166"><div style="flex:1"><b style="color:#7ff0ae">推荐频率 ${best.toFixed(4)} MHz</b>
    ${ad.phase1 ? `第一轮（最大功率）有反应：${ad.phase1.list.filter((f, i) => ad.phase1.res[i] > 0).map(f => f.toFixed(3)).join('、')}；第二轮（低功率）：` : ''}${ad.list.map((f, i) => ad.res[i] === 1 ? f.toFixed(3) + '（全部）' : ad.res[i] === 0.5 ? f.toFixed(3) + '（部分）' : null).filter(Boolean).join('、')}。已临时应用推荐频率，可保存为新档案。
    <div class="row" style="margin-top:10px"><input type="text" id="ad-name" placeholder="档案名称，例如：第二批手环" style="flex:1"><button class="primary" id="btn-ad-save">保存为档案并应用</button></div></div></div>`;
  $('btn-ad-save').onclick = async () => { const name = $('ad-name').value.trim(); if (!name) return toast('请填写档案名称', 'err');
    const r = await call('save_profile', { name, venue: '', pcb: '', freq: best, dbm: 10, bitus: 500, period: 51, notes: `适配向导推荐 ${best.toFixed(4)} MHz；低功率有反应 ${hits.map(f => f.toFixed(3)).join('/')}` });
    if (r.ok) { await call('save'); toast('档案已保存并应用', 'ok'); loadProfiles(name); } };
  ad = null;
}
$('btn-adapt').onclick = async () => {
  if (!state.connected) return toast('请先连接控制器', 'err');
  const list = adFreqs(); if (!list || !list.length || list.length > 40) return toast('频率范围须在 433.05–434.79 MHz 内，且不超过 40 个频率', 'err');
  const cfg = await call('config'); if (!cfg.ok) return;
  ad = { phase: 1, list, i: 0, res: list.map(() => null), dwell: Math.max(10, +$('ad-dwell').value || 30), orig: cfg.data.freq, origDbm: cfg.data.dbm, timer: null };
  await call('set_key', 'dbm', 10);
  $('adapt-form').style.display = 'none'; $('adapt-run').style.display = 'block'; $('ad-result').style.display = 'none'; adTest();
};
$('btn-ad-yes').onclick = () => adAnswer(1);
$('btn-ad-part').onclick = () => adAnswer(0.5);
$('btn-ad-no').onclick = () => adAnswer(0);
$('btn-ad-stop').onclick = adStop;

// ---------- shows + timeline editor ----------
const PAL = { red: [255, 0, 0], orange: [255, 80, 0], yellow: [255, 200, 0], green: [0, 255, 0], cyan: [0, 255, 255], blue: [0, 0, 255], purple: [200, 0, 255], pink: [255, 0, 120], white: [255, 255, 255], black: [0, 0, 0] };
const PAL_CN = { red: '红', orange: '橙', yellow: '黄', green: '绿', cyan: '青', blue: '蓝', purple: '紫', pink: '粉', white: '白', black: '黑' };
const MODES = [['beat', '♪ 跟随节拍'], ['steady', '━ 常亮'], ['strobe', '⚡ 爆闪'], ['off', '✕ 全黑']];
const MARK = { beat: '♪', steady: '━', strobe: '⚡', off: '✕' };
Object.entries(PAL).forEach(([k, c]) => { const el = document.createElement('div'); el.className = 'chip'; el.title = PAL_CN[k]; el.dataset.k = k;
  el.style.background = `rgb(${c})`; el.onclick = () => edSet(1, k); $('ed-chips').appendChild(el); });
MODES.forEach(([v, n]) => { const b = document.createElement('button'); b.textContent = n; b.dataset.v = v; b.onclick = () => edSet(2, v); $('ed-mode').appendChild(b); });

async function loadShows() {
  state.shows = await api().shows();
  $('show-list').innerHTML = state.shows.length ? '' : '<div class="empty">暂无复刻，可在右侧从视频生成</div>';
  state.shows.forEach((s, i) => { const el = document.createElement('div'); el.className = 'item' + (state.showSel === s.dir ? ' sel' : '');
    el.innerHTML = `<div class="ico"><svg viewBox="0 0 24 24"><path d="M5 3l14 9-14 9z"/></svg></div><div style="flex:1"><b>${s.name}</b>
      <div class="mut small">${s.error ? s.error : `${fmtT(s.duration)} · ${s.cues} 个换色点 · ${s.beats} 个鼓点${s.has_video ? '' : ' · 原视频文件不存在'}`}</div></div>`;
    el.onclick = () => openShow(s); $('show-list').appendChild(el); });
}
async function openShow(s) {
  const r = await call('load_show', s.dir); if (!r.ok) return;
  state.showSel = s.dir; state.show = r.data; state.ed = { sel: 0, cursor: 0, playhead: null, undo: [], peaks: null, snap: null };
  $('ed-title').textContent = s.name; loadShows().then(loadDevShows); edSelect(0);
  const pk = await call('show_peaks', s.dir, 20); if (pk.ok && state.showSel === s.dir) { state.ed.peaks = pk.data; drawTL(); }
}
$('btn-shows-refresh').onclick = loadShows;
// ---------- shows stored on the controller (played from the phone) ----------
async function loadDevShows() {
  const box = $('dev-show-list');
  if (!state.connected) { box.innerHTML = '<div class="empty">请先连接控制器</div>'; return; }
  const r = await api().device_shows();
  if (!r.ok) { box.innerHTML = `<div class="empty">无法读取：${r.err}（需要固件 0.8.0 或更高版本）</div>`; return; }
  const bySlot = Object.fromEntries(r.data.map(s => [s.slot, s])); box.innerHTML = '';
  const sel = state.shows.find(s => s.dir === state.showSel);
  if (sel && $('dev-show-name').dataset.for !== sel.dir) { $('dev-show-name').value = sel.name.slice(0, 16); $('dev-show-name').dataset.for = sel.dir; }
  for (let i = 0; i < 4; i++) { const s = bySlot[i]; const el = document.createElement('div'); el.className = 'item';
    el.innerHTML = `<div class="ico"><b>${i + 1}</b></div><div style="flex:1"><b>${s ? s.name : '空位'}</b><div class="mut small">${s ? `${fmtT(s.dur_ms / 1000)} · ${s.cues} 个换色点 · ${s.beats} 个鼓点` : '未保存节目'}</div></div>`;
    const put = document.createElement('button'); put.textContent = s ? '用选中复刻替换' : '写入选中复刻'; put.disabled = !sel;
    put.onclick = async (ev) => { ev.stopPropagation(); if (!sel) return;
      const name = $('dev-show-name').value.trim(); if (!name) return toast('请填写节目名称', 'err');
      const res = await call('upload_show', sel.dir, i, name); if (res.ok) toast('正在写入控制器…'); };
    el.appendChild(put);
    if (s) { const del = document.createElement('button'); del.className = 'danger'; del.textContent = '删除'; del.style.marginLeft = '8px';
      del.onclick = async (ev) => { ev.stopPropagation();
        if (!del.dataset.armed) { del.dataset.armed = 1; del.textContent = '确认删除'; setTimeout(() => { delete del.dataset.armed; del.textContent = '删除'; }, 3000); return; }
        const d = await call('delete_device_show', i); if (d.ok) { toast('已删除', 'ok'); loadDevShows(); } };
      el.appendChild(del); }
    box.appendChild(el); }
}
$('btn-dev-shows').onclick = loadDevShows;
$('btn-pick-video').onclick = async () => { const p = await api().pick_video(); if (p) $('g-video').value = p; };
$('btn-build').onclick = async () => {
  const [m, s] = ($('g-start').value.trim() + ':0').split(':'); const start = parseInt(m) * 60 + parseFloat(s);
  if (!$('g-video').value) return toast('请先选择视频文件', 'err');
  const r = await call('build_show', $('g-video').value, start, $('g-dur').value, $('g-name').value.trim() || 'show');
  if (r.ok) $('g-log').textContent = '开始生成…';
};
const zoom = () => +$('tl-zoom').value;
const ends = (i) => [state.show.colours[i][0], i + 1 < state.show.colours.length ? state.show.colours[i + 1][0] : state.show.duration_s];
function drawTL() {
  const cv = $('tl'), H = cv.height; if (!state.show) { cv.width = $('tl-wrap').clientWidth || 800; const c = cv.getContext('2d'); c.clearRect(0, 0, cv.width, H);
    c.fillStyle = '#6E6B67'; c.font = '13px Microsoft YaHei UI'; c.fillText('请在上方选择复刻', 16, 96); return; }
  const z = zoom(), dur = state.show.duration_s, W = Math.max($('tl-wrap').clientWidth, dur * z);
  if (cv.width !== Math.ceil(W)) cv.width = Math.ceil(W);
  const c = cv.getContext('2d'); c.clearRect(0, 0, cv.width, H);
  c.font = '11px Microsoft YaHei UI';
  for (let t = 0; t <= dur; t += (z >= 10 ? 10 : 30)) { c.fillStyle = '#3A3A40'; c.fillRect(t * z, 0, 1, 12); c.fillStyle = '#8D8A85'; c.fillText(`${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`, t * z + 3, 10); }
  state.show.colours.forEach((cue, i) => { const [a, b] = ends(i); const col = PAL[cue[1]] || [80, 80, 80];
    const x = a * z, w = Math.max(1, (b - a) * z);
    c.fillStyle = `rgba(${col},.88)`; roundRect(c, x + 1, 20, w - 2, 92, 6); c.fill();
    if (i === state.ed.sel) { c.strokeStyle = '#EDEBE7'; c.lineWidth = 2; roundRect(c, x + 1, 20, w - 2, 92, 6); c.stroke(); }
    if (w > 18) { c.fillStyle = 'rgba(0,0,0,.6)'; c.font = 'bold 14px Segoe UI Symbol'; c.fillText(MARK[cue[2]] || '', x + 7, 42); } });
  // waveform band (live sound) with the drum beats over it
  const wy = 150, wh = 30, pk = state.ed.peaks;
  c.fillStyle = '#141416'; c.fillRect(0, 120, cv.width, 60);
  if (pk && pk.length) { const per = pk.length / dur; c.fillStyle = 'rgba(237,235,231,.28)';
    const x0 = Math.max(0, Math.floor($('tl-wrap').scrollLeft)), x1 = x0 + $('tl-wrap').clientWidth + 2;
    for (let x = x0; x < Math.min(x1, cv.width); x++) { const i0 = Math.floor(x / z * per), i1 = Math.max(i0 + 1, Math.floor((x + 1) / z * per));
      let v = 0; for (let i = i0; i < i1 && i < pk.length; i++) v = Math.max(v, pk[i]); const h = Math.max(1, v * wh); c.fillRect(x, wy - h, 1, h * 2); } }
  c.fillStyle = 'rgba(255,138,76,.55)'; state.show.beats.forEach(t => c.fillRect(t * z, 122, 1, 56));
  if (state.ed.snap != null) { c.fillStyle = '#FF8A4C'; c.fillRect(state.ed.snap * z - 1, 16, 2, 166); }
  c.fillStyle = '#FF8A4C'; c.fillRect(state.ed.cursor * z - 1, 14, 2, H - 14);
  if (state.ed.playhead != null) { c.fillStyle = '#EDEBE7'; c.fillRect(state.ed.playhead * z - 1, 14, 2, H - 14); }
}
function roundRect(c, x, y, w, h, r) { r = Math.min(r, w / 2); c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }
function edSelect(i) {
  if (!state.show) return; const n = state.show.colours.length; state.ed.sel = Math.max(0, Math.min(i, n - 1));
  const cue = state.show.colours[state.ed.sel];
  document.querySelectorAll('#ed-chips .chip').forEach(ch => ch.classList.toggle('on', ch.dataset.k === cue[1]));
  markSeg('ed-mode', cue[2]); drawTL();
}
function edPush() { state.ed.undo.push(JSON.stringify(state.show.colours)); if (state.ed.undo.length > 60) state.ed.undo.shift(); state.ed.dirty = true; }
function edSet(idx, v) { if (!state.show) return; edPush(); state.show.colours[state.ed.sel][idx] = v; edSelect(state.ed.sel); }
let drag = null;
$('tl').onmousedown = (e) => { if (!state.show) return; const x = e.offsetX, z = zoom(), cues = state.show.colours;
  for (let i = 1; i < cues.length; i++) if (Math.abs(cues[i][0] * z - x) < 5) { edPush(); drag = i; return; }
  let t = Math.max(0, Math.min(state.show.duration_s, x / z)); const b = e.altKey ? null : nearestBeat(t, 6 / z); if (b != null) t = b;
  state.ed.cursor = t; $('ed-pos').textContent = fmtT(t);
  let idx = 0; cues.forEach((c, i) => { if (c[0] <= t) idx = i; }); edSelect(idx); };
window.addEventListener('mousemove', (e) => { if (drag == null) return; const cues = state.show.colours; const rect = $('tl').getBoundingClientRect();
  let t = (e.clientX - rect.left) / zoom(); const lo = cues[drag - 1][0] + 0.2, hi = (drag + 1 < cues.length ? cues[drag + 1][0] : state.show.duration_s) - 0.2;
  const b = e.altKey ? null : nearestBeat(t, 8 / zoom()); state.ed.snap = b; if (b != null) t = b;   // snap to a beat within 8 px
  cues[drag][0] = Math.round(Math.max(lo, Math.min(hi, t)) * 1000) / 1000; state.ed.sel = drag; drawTL(); });
window.addEventListener('mouseup', () => { if (drag != null) { state.ed.snap = null; edSelect(drag); drag = null; } });
function nearestBeat(t, tol) { const bs = state.show.beats; let lo = 0, hi = bs.length - 1; if (hi < 0) return null;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (bs[m] < t) lo = m; else hi = m; }
  const best = Math.abs(bs[lo] - t) < Math.abs(bs[hi] - t) ? bs[lo] : bs[hi]; return Math.abs(best - t) <= tol ? best : null; }
$('tl').onmousemove = (e) => { if (!state.show) return; const z = zoom(); $('tl').style.cursor = state.show.colours.some((c, i) => i && Math.abs(c[0] * z - e.offsetX) < 5) ? 'ew-resize' : 'pointer'; };
$('tl-zoom').oninput = drawTL;
$('tl-wrap').onscroll = () => { if (state.ed && state.ed.peaks) drawTL(); };   // waveform is drawn for the visible part only
$('btn-split').onclick = () => { if (!state.show) return; const [a, b] = ends(state.ed.sel), t = state.ed.cursor;
  if (!(a + 0.2 < t && t < b - 0.2)) return toast('请先在选中段内点击，定位光标位置', 'err');
  edPush(); const cue = state.show.colours[state.ed.sel]; state.show.colours.splice(state.ed.sel + 1, 0, [Math.round(t * 100) / 100, cue[1], cue[2]]); edSelect(state.ed.sel + 1); };
$('btn-merge').onclick = () => { if (state.show && state.ed.sel + 1 < state.show.colours.length) { edPush(); state.show.colours.splice(state.ed.sel + 1, 1); edSelect(state.ed.sel); } };
$('btn-del').onclick = () => { if (state.show && state.ed.sel > 0) { edPush(); state.show.colours.splice(state.ed.sel, 1); edSelect(state.ed.sel - 1); } };
$('btn-undo').onclick = () => { if (state.ed && state.ed.undo.length) { state.show.colours = JSON.parse(state.ed.undo.pop()); edSelect(state.ed.sel); } };
$('btn-save-show').onclick = async () => { if (!state.show) return; const r = await call('save_show', state.showSel, state.show); if (r.ok) { state.ed.dirty = false; toast('已保存', 'ok'); loadShows(); } };
$('p-vol').oninput = () => $('v-vol').textContent = $('p-vol').value;
$('p-lat').oninput = () => $('v-lat').textContent = $('p-lat').value + 'ms';
function play(wake, fromCursor) {
  if (!state.show) return toast('请先选择复刻', 'err');
  if (!state.connected) return toast('请先在“设备”页连接控制器', 'err');
  call('play_show', state.showSel, { wake, video: $('t-video').checked, volume: +$('p-vol').value, latency: +$('p-lat').value,
    from: fromCursor ? state.ed.cursor : 0, show: state.show });
}
$('btn-play-wake').onclick = () => play(true, false);
$('btn-play').onclick = () => play(false, true);
$('btn-stop').onclick = () => call('stop_show');
// ---------- original video in a popup; its clock drives the lights ----------
let vClock = null, vStopped = false;
function stopVideoShow() { if (vStopped) return; vStopped = true; clearInterval(vClock); call('stop_show'); }
let vSeeking = false;
function openShowVideo(e) {
  const v = $('show-video'); const end = e.start + e.duration; vStopped = false;
  const seek = $('v-seek'); seek.max = e.duration; seek.value = e.offset;
  const syncBtn = () => $('btn-vplay').classList.toggle('paused', v.paused);
  v.onplay = v.onpause = syncBtn; syncBtn();
  $('btn-vplay').onclick = () => { if (v.paused) v.play().catch(() => {}); else v.pause(); };
  seek.oninput = () => { vSeeking = true; v.currentTime = e.start + Number(seek.value); };
  seek.onchange = () => { vSeeking = false; };
  v.src = e.src; v.volume = Math.min(1, (e.volume || 35) / 100);
  $('video-title').textContent = state.show ? $('ed-title').textContent + ' · 原视频' : '原视频';
  v.onloadedmetadata = () => { v.currentTime = e.start + e.offset; v.play().catch(() => toast('无法播放这个视频文件', 'err')); };
  v.onerror = () => { toast('无法播放这个视频文件（建议使用 MP4）', 'err'); stopVideoShow(); };
  v.onended = stopVideoShow;
  clearInterval(vClock);
  vClock = setInterval(() => {
    const pos = v.currentTime - e.start;
    $('video-time').textContent = fmtT(Math.max(0, pos)) + ' / ' + fmtT(e.duration);
    if (!vSeeking) seek.value = Math.max(0, pos);
    if (v.currentTime >= end) { stopVideoShow(); return; }
    api().show_clock(pos);
  }, 50);
  showModal('video-modal');
}
function closeShowVideo(fromBackend) {
  clearInterval(vClock); vClock = null; const v = $('show-video');
  if (!v.paused) v.pause(); v.removeAttribute('src'); v.load();
  hideModal('video-modal');
  if (!fromBackend) stopVideoShow();
}
$('btn-video-close').onclick = () => closeShowVideo(false);
document.addEventListener('keydown', (ev) => {
  if (ev.code !== 'Space' || !$('video-modal').classList.contains('show')) return;
  if (ev.target.matches?.('input[type=text], textarea')) return;
  ev.preventDefault();      // also stops Space from "clicking" a focused button (e.g. 停止并关闭)
  if (!ev.repeat) $('btn-vplay').click();
});
// ---------- settings backup ----------
$('btn-export-settings').onclick = async () => {
  if (!state.connected) return toast('请先在“设备”页连接控制器', 'err');
  const r = await call('export_settings'); if (r.ok && r.data) { $('backup-msg').textContent = '已导出：' + r.data; toast('设置已导出', 'ok'); } };
$('btn-import-settings').onclick = async () => {
  if (!state.connected) return toast('请先在“设备”页连接控制器', 'err');
  const r = await call('import_settings'); if (!r.ok || !r.data) return;
  const bad = Object.keys(r.data.failed || {});
  $('backup-msg').textContent = `已恢复 ${r.data.applied.length} 项设置` + (bad.length ? `，${bad.length} 项未能应用：${bad.join('、')}` : '');
  toast(bad.length ? '部分设置未能恢复' : '设置已恢复并保存到控制器', bad.length ? 'err' : 'ok'); loadConfig(); };
window.addEventListener('resize', drawTL);

// ---------- helpdesk: plain-language fixes, flash progress, one-click diagnose ----------
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const stepsHTML = (info) => `<b class="t">${esc(info.title)}</b><ol>${(info.steps || []).map(x => `<li>${esc(x)}</li>`).join('')}</ol>`;
const fixHTML = (info, bad) => `<div class="fixcard${bad ? ' bad' : ''}">${stepsHTML(info)}</div>`;

function flashProgress(e) {
  const txt = e.pct < 100 ? '正在刷入…' : '等控制器重启…';
  if (guide.flashing) { $('g2-bar').style.width = e.pct + '%'; $('g2-pn').textContent = Math.round(e.pct) + '%'; $('g2-pt').textContent = txt; return; }
  $('flash-prog').hidden = false; $('flash-prog-bar').style.width = e.pct + '%'; $('flash-prog-n').textContent = Math.round(e.pct) + '%';
  $('flash-prog-t').textContent = `${e.port} ${txt}`;
}
function flashDone(e) {
  const ok = Object.values(e.results).every(v => v === '成功');
  toast(ok ? '刷机完成' : '刷机没有成功，看右侧的提示', ok ? 'ok' : 'err');
  $('flash-prog').hidden = true;
  const errs = Object.entries(e.errors || {});
  $('flash-err').hidden = !errs.length;
  $('flash-err').innerHTML = errs.map(([port, info]) => fixHTML({ title: `${port}：${info.title}`, steps: info.steps }, true)).join('');
  $('flash-err').className = '';
}
const flashBtnOld = $('btn-flash').onclick;
$('btn-flash').onclick = async () => { $('flash-err').innerHTML = ''; $('flash-err').hidden = true; $('flash-prog').hidden = true; return flashBtnOld(); };

let diagReport = '';
async function runDiag() {
  showModal('diag-modal');
  $('diag-sub').textContent = '正在检查…';
  $('diag-list').innerHTML = '<div class="guide-status"><span class="spin"></span>检查中，几秒钟就好</div>';
  const r = await call('diagnose'); if (!r.ok) { hideModal('diag-modal'); return; }
  const d = r.data; diagReport = d.report;
  const bad = d.items.filter(i => i.state !== 'ok').length;
  $('diag-sub').textContent = d.connected ? (bad ? `发现 ${bad} 个需要注意的地方` : '一切正常') : '还没有连接控制器，下面是电脑这边的检查结果';
  const mark = { ok: '✓', warn: '!', bad: '✕' };
  $('diag-list').innerHTML = d.items.map(i => `<div class="diag-row"><span class="st ${i.state}">${mark[i.state]}</span><div><b>${esc(i.name)}</b><span class="t">${esc(i.text)}</span></div></div>`).join('')
    || '<div class="mut">没有可显示的项目</div>';
}
$('btn-diag').onclick = runDiag; $('btn-diag2').onclick = runDiag; $('btn-diag-again').onclick = runDiag;
$('btn-diag-close').onclick = () => hideModal('diag-modal');
$('btn-diag-copy').onclick = async () => { if (!diagReport) return; await call('copy_text', diagReport); toast('诊断报告已复制，可以直接粘贴到群里', 'ok'); };

// ---------- first-run guide: connect -> flash -> phone ----------
const guide = { step: 0, port: null, timer: null, flashing: false, mode: 'full', lastHint: 0 };
function guideStep(n) {
  guide.step = n;
  document.querySelectorAll('#guide-modal .guide-body').forEach(b => {
    const on = +b.dataset.step === n;
    if (on && b.hidden) { b.hidden = false; b.animate({ opacity: [0, 1], transform: ['translateX(18px)', 'none'] }, { duration: T(420), easing: EASE.out }); }
    if (!on) b.hidden = true;
  });
  document.querySelectorAll('.guide-steps span').forEach(s => { const k = +s.dataset.s; s.className = k < n ? 'done' : (k === n ? 'on' : ''); });
}
async function guideScan() {
  if (guide.step !== 1 || !$('guide-modal').classList.contains('show')) return;
  const r = await api().scan();
  const rows = (r && r.ok) ? r.data : [];
  const usable = rows.find(d => d.state !== 'busy');
  if (usable) {
    guide.port = usable.port;
    $('g1-status').className = 'guide-status ok'; $('g1-fix').hidden = true;
    if (usable.state === 'ready') { $('g1-text').textContent = `找到控制器（${usable.port}），固件已是最新`; setTimeout(() => guidePhone(usable), 900); return; }
    guide.mode = usable.state === 'old' ? 'app' : 'full';
    $('g1-text').textContent = usable.state === 'old' ? `找到控制器（${usable.port}），有新固件可以更新` : `找到板子（${usable.port}），还没有刷固件`;
    setTimeout(guideFlashPage, 900); return;
  }
  $('g1-status').className = 'guide-status';
  if (rows.length) {
    $('g1-text').textContent = '找到了板子，但它被别的程序占用';
    $('g1-fix').hidden = false;
    $('g1-fix').innerHTML = stepsHTML({ title: '端口被别的程序占用了', steps: ['关掉串口助手、Arduino 或另一个 Afterglow Studio', '拔掉数据线重新插上'] });
  } else if (Date.now() - guide.lastHint > 5000) {
    guide.lastHint = Date.now(); $('g1-text').textContent = '正在寻找控制器…';
    const h = await api().scan_hint();
    if (guide.step === 1) { $('g1-fix').hidden = false; $('g1-fix').innerHTML = stepsHTML(h); }
  }
  guide.timer = setTimeout(guideScan, 1500);
}
function guideFlashPage() {
  guideStep(2);
  const upd = guide.mode === 'app';
  $('g2-title').textContent = upd ? '更新固件' : '刷入固件';
  $('g2-sub').textContent = upd ? '保留控制器里的设置和节目，大约 30 秒，期间不要拔线。' : '大约 1 分钟，期间不要拔线。';
  $('g2-fix').hidden = true; $('g2-bar').style.width = '0'; $('g2-pn').textContent = '0%'; $('g2-pt').textContent = '准备好了';
  $('btn-g2-go').textContent = upd ? '更新固件' : '刷入固件'; $('btn-g2-go').disabled = false;
}
$('btn-g2-go').onclick = async () => {
  const pkg = await api().latest_firmware(); if (!pkg) return toast('软件里没有找到固件包，请重新安装 Afterglow Studio', 'err');
  if (state.connected) { await call('disconnect'); setConnected(null); }
  guide.flashing = true; $('btn-g2-go').disabled = true; $('g2-fix').hidden = true; $('g2-pt').textContent = '正在连接板子…';
  const r = await call('flash', [guide.port], pkg.path, guide.mode === 'app');
  if (!r || !r.ok) { guide.flashing = false; $('btn-g2-go').disabled = false; }
};
async function guideFlashDone(e) {
  guide.flashing = false;
  const err = (e.errors || {})[guide.port];
  if (!err && e.results[guide.port] === '成功') {
    $('g2-bar').style.width = '100%'; $('g2-pn').textContent = '100%'; $('g2-pt').textContent = '完成';
    const r = await api().scan(); const row = ((r && r.data) || []).find(d => d.port === guide.port) || {};
    setTimeout(() => guidePhone(row), 700); return;
  }
  $('g2-bar').style.width = '0'; $('g2-pn').textContent = ''; $('g2-pt').textContent = '没有成功';
  $('g2-fix').hidden = false; $('g2-fix').className = 'fixcard bad';
  $('g2-fix').innerHTML = stepsHTML(err || { title: e.results[guide.port] || '刷机没有成功', steps: ['拔掉数据线重新插上，再试一次'] });
  $('btn-g2-go').disabled = false; $('btn-g2-go').textContent = '再试一次';
}
function guidePhone(row) {
  guideStep(3);
  $('g3-ssid').textContent = (row && row.ssid) || 'Afterglow-XXXX';
  // the controller only says whether the factory password is still in use, never the password itself
  const custom = row && row.pwdef === false;
  $('g3-pw').textContent = custom ? '你自己设置过的那个' : 'afterglow88';
  $('g3-pwnote').hidden = !custom;
}
async function openGuide(port) {
  clearTimeout(guide.timer); guide.port = port || null; guide.flashing = false;
  showModal('guide-modal');
  if (port) {
    const r = await api().scan(); const row = ((r && r.data) || []).find(d => d.port === port);
    if (row && row.state !== 'ready' && row.state !== 'busy') { guide.mode = row.state === 'old' ? 'app' : 'full'; guideFlashPage(); return; }
  }
  guideStep(1); $('g1-fix').hidden = true; $('g1-status').className = 'guide-status'; $('g1-text').textContent = '正在寻找控制器…'; guide.lastHint = 0;
  guideScan();
}
async function closeGuide() {
  clearTimeout(guide.timer); guide.step = 0; hideModal('guide-modal');
  await api().onboarding_done();
}
$('btn-guide-skip').onclick = closeGuide;
$('btn-guide').onclick = () => openGuide();
$('btn-g3-done').onclick = async () => { const port = guide.port; await closeGuide(); if (port) await connect(port); };

// ---------- start ----------
window.addEventListener('pywebviewready', async () => {
  const info = await api().app_info(); $('appver').textContent = 'v' + info.version;
  scan(); drawTL();
  const ob = await api().onboarding(); if (!ob.done) setTimeout(() => openGuide(), 600);
});


// first paint: put the nav highlight under the active item, then animate the first page in
requestAnimationFrame(() => { movePill(document.querySelector('nav a.active'), true); enterPage(document.querySelector('.page.active')); });
