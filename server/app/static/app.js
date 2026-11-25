'use strict';
/* WhisperVM-Frontend: PCM-Aufnahme -> WebSocket -> Live-Transkript.
   Keine Ablage im Browser (kein localStorage, kein IndexedDB). */
const $ = id => document.getElementById(id);
const RATE = 16000, LIMIT = 60;

let ws = null, ctx = null, node = null, stream = null, timer = null;
let elapsed = 0, finalText = '', copied = false, exported = false;

const ui = {
  status: t => { $('status').textContent = t; },
  state: s => {
    $('bStart').disabled = s !== 'ready';
    $('bStop').disabled = s !== 'recording';
    $('bCopy').disabled = $('bExport').disabled = s !== 'locked';
    $('bNext').disabled = !(s === 'locked' && copied && exported);
  },
};

const STATE_TEXT = {
  ready: 'bereit',
  recording: 'Aufnahme läuft…',
  locked: 'Diktat fertig – bitte kopieren UND exportieren',
};

function connect() {
  return new Promise((resolve, reject) => {
    if (ws && ws.readyState === WebSocket.OPEN) return resolve();
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.binaryType = 'arraybuffer';
    ws.onopen = resolve;
    ws.onerror = () => { ui.status('Verbindungsfehler'); reject(); };
    ws.onclose = e => {
      ui.status(e.code === 4401
        ? 'Nicht angemeldet / Sitzung abgelaufen – Seite neu laden'
        : 'Verbindung getrennt – Seite neu laden');
      ui.state('offline');
    };
    ws.onmessage = e => onEvent(JSON.parse(e.data));
  });
}

function onEvent(ev) {
  if (ev.ev === 'state') {
    ui.state(ev.state);
    ui.status(STATE_TEXT[ev.state] || ev.state);
    if (ev.state === 'locked') { copied = exported = false; ui.state('locked'); }
  } else if (ev.ev === 'partial') {
    $('log').textContent = ev.text + ' …';
  } else if (ev.ev === 'final') {
    finalText = ev.text;
    renderFinal(ev);
    copied = exported = false;
    ui.state('locked');
    ui.status(STATE_TEXT.locked + confText(ev.conf));
  }
}

// Farbverlauf fuer Wort-Konfidenz: rot (0%) -> orange (50%) -> gruen (100%).
// Stueckweise linear im Hue, damit genau bei p=0,5 orange liegt.
function confColor(p) {
  const hue = p < 0.5 ? 39 * (p / 0.5) : 39 + 81 * ((p - 0.5) / 0.5);
  return `hsl(${Math.round(hue)}, 80%, 60%)`;
}

function renderFinal(ev) {
  const log = $('log');
  log.innerHTML = '';
  if (ev.words && ev.words.length) {
    for (const w of ev.words) {
      const s = document.createElement('span');
      s.className = 'wconf';
      s.style.color = confColor(w.p);
      s.title = `Sicherheit: ${Math.round(w.p * 100)}%`;
      s.textContent = w.w;
      log.appendChild(s);
      log.appendChild(document.createTextNode(' '));
    }
  } else {
    log.textContent = ev.text;
  }
}

function confText(conf) {
  return conf == null ? '' : ` – Sicherheit: ${Math.round(conf * 100)}%`;
}

async function start() {
  try {
    await connect();
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch {
    ui.status('Mikrofon-Zugriff verweigert (HTTPS/Localhost nötig?)');
    return;
  }
  ctx = new AudioContext({ sampleRate: RATE });
  if (ctx.state === 'suspended') await ctx.resume();
  await ctx.audioWorklet.addModule('/static/pcm-worklet.js');
  const src = ctx.createMediaStreamSource(stream);
  node = new AudioWorkletNode(ctx, 'pcm-capture');
  node.port.onmessage = e => sendPcm(e.data);
  src.connect(node);
  node.connect(ctx.destination);            // Worklet gibt Stille aus
  ws.send(JSON.stringify({ cmd: 'start', lang: $('lang').value }));
  elapsed = 0; tick();
  timer = setInterval(() => { tick(); if (++elapsed >= LIMIT) stop(); }, 1000);
}

function stop() {
  clearInterval(timer); timer = null;
  if (stream) stream.getTracks().forEach(t => t.stop());
  if (ctx) ctx.close();
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify({ cmd: 'stop' }));
  ui.state('processing');
  ui.status('Transkription läuft…');
}

function tick() {
  const m = Math.floor(elapsed / 60), s = String(elapsed % 60).padStart(2, '0');
  $('time').textContent = `${m}:${s}`;
}

function sendPcm(f32) {
  let peak = 0;
  for (let i = 0; i < f32.length; i += 8) peak = Math.max(peak, Math.abs(f32[i]));
  const lvl = $('lvl');
  if (lvl) lvl.style.width = Math.min(100, Math.round(peak * 400)) + '%';
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const data = ctx.sampleRate === RATE ? f32 : resample(f32, ctx.sampleRate);
  const buf = new Int16Array(data.length);
  for (let i = 0; i < data.length; i++) {
    const v = Math.max(-1, Math.min(1, data[i]));
    buf[i] = v < 0 ? v * 32768 : v * 32767;
  }
  ws.send(buf.buffer);
}

function resample(src, from) {
  const ratio = from / RATE, len = Math.floor(src.length / ratio);
  const out = new Float32Array(len);
  for (let i = 0; i < len; i++) {
    const pos = i * ratio, i0 = Math.floor(pos), f = pos - i0;
    out[i] = src[i0] * (1 - f) + src[Math.min(i0 + 1, src.length - 1)] * f;
  }
  return out;
}

$('bStart').onclick = start;
$('bStop').onclick = stop;
$('bCopy').onclick = async () => {
  await navigator.clipboard.writeText(finalText);
  copied = true; ui.state('locked');
  ui.status(exported ? 'gesichert – „Neues Diktat“ frei' : 'kopiert – Export fehlt noch');
};
$('bExport').onclick = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([finalText + '\n'],
    { type: 'text/plain;charset=utf-8' }));
  a.download = 'diktat-' + new Date().toISOString().replace(/[:.]/g, '-') + '.txt';
  a.click();
  URL.revokeObjectURL(a.href);
  exported = true; ui.state('locked');
  ui.status(copied ? 'gesichert – „Neues Diktat“ frei' : 'exportiert – Kopieren fehlt noch');
};
$('bNext').onclick = () => {
  ws.send(JSON.stringify({ cmd: 'reset' }));
  $('log').textContent = ''; finalText = '';
};
$('bReload').onclick = () => location.reload();

connect().then(() => ui.status('bereit')).catch(() => {});

fetch('/api/version').then(r => r.json())
  .then(d => { $('ver').textContent = d.version; }).catch(() => {});
