// Design preview only (index.html?mock): fake backend so the page renders in a normal browser.
(function () {
  const show = { duration_s: 300, beats: Array.from({ length: 400 }, (_, i) => i * 0.7 + 0.3), source: 'x.mp4',
    colours: [[0, 'red', 'beat'], [33, 'orange', 'beat'], [95, 'blue', 'beat'], [111, 'yellow', 'beat'], [135, 'blue', 'beat'],
      [155, 'cyan', 'beat'], [180, 'orange', 'steady'], [210, 'orange', 'beat'], [234, 'white', 'strobe'], [266, 'blue', 'beat']] };
  const ok = (data) => Promise.resolve({ ok: true, data });
  window.pywebview = { api: {
    app_info: () => Promise.resolve({ version: '0.4.3' }),
    scan: () => location.search.includes('porterr') ? ok([{ port: 'COM5', desc: 'USB-SERIAL CH340 (COM5)', error: 'SerialTimeoutException: Write timeout', state: 'error' }]) :
      ok(location.search.includes('guide=1') ? [] : [
      { port: 'COM4', desc: 'USB-SERIAL CH340 (COM4)', fw: 'afterglow-fw', ver: '0.9.2', mac: 'A0B1C2D3E4F5', ssid: 'Afterglow-E4F5', state: 'ready' },
      { port: 'COM9', desc: 'USB-SERIAL CH340 (COM9)', unknown: true, state: 'blank' }]),
    port_error_hint: (port, error) => Promise.resolve({ kind: 'port_error', title: `找到了板子（${port}），但读不到它`, steps: ['按一下 EN 键'], detail: `${port}：${error}` }),
    scan_hint: () => Promise.resolve({ kind: 'driver', title: '电脑认出了板子，但缺少 CH340 驱动',
      steps: ['在浏览器搜索“CH340 驱动”，到芯片厂家官网下载（CH340 是“沁恒”官网）', '安装后拔掉数据线再插上', '回到这里，会自动重新检测'] }),
    latest_firmware: () => Promise.resolve({ path: 'p', version: '0.9.2' }),
    diagnose: () => ok({ connected: true, report: 'Afterglow 诊断报告', items: [
      { name: '固件版本', state: 'warn', text: '0.9.0，可以更新到 0.9.2（“烧录 / 更新”页面，选“仅更新程序”）' },
      { name: '射频模块', state: 'ok', text: 'E07 工作正常' }, { name: '发射', state: 'ok', text: '没有发射错误' },
      { name: '麦克风', state: 'warn', text: '接上了但几乎没声音：检查 SD、WS、SCK 三根线，L/R 要接 GND' },
      { name: '手机热点', state: 'ok', text: 'Afterglow-E4F5 已开启，当前 1 台手机连接' }, { name: '上次重启', state: 'ok', text: '正常上电' }] }),
    copy_text: () => Promise.resolve(true), disconnect: () => ok({}),
    flash: (ports) => { let pct = 0; const iv = setInterval(() => { pct += 9; window.onBackend({ type: 'flash_progress', port: ports[0], pct: Math.min(pct, 100) });
      if (pct >= 100) { clearInterval(iv); window.onBackend({ type: 'flash_done', results: { [ports[0]]: '失败：板子没有进入刷机模式' },
        errors: { [ports[0]]: { kind: 'no_boot', title: '板子没有进入刷机模式', steps: ['按住 ESP32 上的 BOOT 键不放，再点一次“刷入固件”', '看到进度开始走了，就可以松开 BOOT 键', '还不行就换一根数据线'] } } }); } }, 120); return ok({}); },
    onboarding: () => Promise.resolve({ done: !location.search.includes('guide=1') }),
    onboarding_done: () => Promise.resolve(true),
    connect: () => ok({ fw: 'afterglow-fw', ver: '0.9.2', proto: 1, built: 'Nov 12 2026', mac: 'A0B1C2D3E4F5', ssid: 'Afterglow-E4F5' }),
    status: () => Promise.resolve({ ok: true, connected: true, data: { mode: 'hold', color: '#0000ff', mic: true, bpm: 170.5, beats: Math.floor(Date.now() / 350), level: 0.018, frames: 12345, freq: 433.9198, dbm: 10, wifi_clients: 1, uptime_s: 93780, boots: 12, reset: "poweron" } }),
    config: () => ok({ freq: 433.92, dbm: 10, msens: 1.8, bright: 150, mbase: 0, mhold: 120, pchan: 80, psum: 125, mstyle: 4, auto: 0, wifi: 1, ka: 1 }),
    set_key: () => ok({}), save: () => ok({}), color: () => ok({}), off: () => ok({}), mic: () => ok({}), micmon: () => ok({}), command: () => ok({}),
    get_log: () => Promise.resolve(['14:00:01 > status', '14:00:01 < {"ok":true,"mode":"mic"}']),
    packages: () => Promise.resolve([{ path: 'p', name: 'afterglow-fw', version: '0.9.2', built: '2026-11-12T14:19:59' }]),
    profiles: () => Promise.resolve([{ name: '默认（标准频率）', venue: '', pcb: 'CEMENT V1.1r3', freq: 433.92, dbm: 10, bitus: 500, period: 51, notes: '' }]),
    loop_devices: () => Promise.resolve([{ index: 1, name: '扬声器 (Realtek High Definition Audio)' }]),
    shows: () => Promise.resolve([{ name: '示例复刻', dir: 'd', duration: 300, cues: 10, beats: 400, has_video: true }]),
    export_settings: () => ok('C:/Users/me/Documents/Afterglow设置_E4F5_20261113.json'), import_settings: () => ok({ applied: ['freq', 'dbm', 'pchan'], failed: {}, config: {} }),
    device_shows: () => ok([{ slot: 0, name: '示例节目 1', dur_ms: 300000, cues: 39, beats: 477 }]), upload_show: () => ok({}), delete_device_show: () => ok({}),
    load_show: () => ok(JSON.parse(JSON.stringify(show))), show_peaks: () => ok(Array.from({ length: 6000 }, (_, i) => Math.abs(Math.sin(i / 37) * Math.sin(i / 5.3)) * (0.4 + 0.6 * ((i % 14) < 2)))), save_show: () => ok({}), play_show: () => ok({}), stop_show: () => ok({}),
  } };
  setTimeout(() => { window.dispatchEvent(new Event('pywebviewready'));
    setTimeout(() => { document.querySelector('#dev-list .item button')?.click();
      const page = new URLSearchParams(location.search).get('page');   // ?mock&page=music: open a page (README screenshots)
      if (page) setTimeout(() => document.querySelector(`[data-page="${page}"]`)?.click(), 1500); }, 300); }, 50);
  // design previews: ?mock&guide=1|2|2err|3  or  ?mock&diag
  const q = new URLSearchParams(location.search);
  setTimeout(() => {
    const g = q.get('guide');
    if (g === '2' || g === '2err') { openGuide('COM9').then(() => { if (g === '2') { guide.flashing = true; flashProgress({ port: 'COM9', pct: 64 }); } else document.getElementById('btn-g2-go').click(); }); }
    if (g === '3') { showModal('guide-modal'); guidePhone({ ssid: 'Afterglow-E4F5' }); }
    if (q.has('diag')) runDiag();
  }, 900);
})();
