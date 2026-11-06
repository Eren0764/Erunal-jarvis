// Jarvis / Bilgi Galaksisi — ortak ses arayüzü (tr-TR)
// Dinleme: MediaRecorder + Groq Whisper Large V3 (sunucudaki /listen). Konuşma: Gemini API ses üretimi (/speak).
// Yerel yapay zekâ modeli yok: tüm yapay zekâ işleri API üzerinden yapılır.

// Cümle bitti saymadan önce beklenecek sessizlik (ms). Bu süre içinde yeni konuşma gelirse
// tampona eklenir ve sayaç yeniden başlar; yalnızca düşünceyi gerçekten bitiren duraklama gönderir.
const FINISH_MS = 900;

// Tamponu tamamen atlayıp ANINDA çalışan kısa kesme sözcükleri.
const INTERRUPT_RE = /^(?:(?:dur|bekle|sus)\s*)+$/;

const ECHO_GUARD_MS = 700;   // konuşma bittikten sonra kendi sesimizin yankısını yok say

// Uyandırma sözcükleri ("Hey Jarvis", "Tahta") — brain.py WAKE_RE ile aynı. "Tahta" yalnızca cümle başında
// ve tek sözcük olarak sayılır ("tahtaya bakın" uyandırmaz). Yanıt metni sunucudan gelir (/boot → wake_reply).
const WAKE_RE = /^(?:(?:hello|[a-zçğıöşü]{1,4}) )?(?:jarvis|jarvıs|carvis|cervis|jervis|ciarvis|çarvis)(?![a-zçğıöşü'’])\s*|^(?:tahta|tata)(?![a-zçğıöşü])\s*/;

// ---------------------------------------------------------------------------
// Ses komutları (voice routes). LLM'e gitmeden ÖNCE sırayla denenir.
// Yeni komut eklemek için çekirdek mantığa dokunmayın:
//   VOICE_ROUTES.push({ name: 'örnek', pattern: /^merhaba$/, handler: (m, text) => { ... } });
// handler `false` döndürürse eşleşme yok sayılır ve sıradaki rotaya / LLM'e geçilir.
// ---------------------------------------------------------------------------
const VOICE_ROUTES = [
  { name: 'kesme', pattern: INTERRUPT_RE,
    handler: () => { Voice.interrupt(); Voice.flash('Durduruldu'); } },
  { name: 'yeni sohbet', pattern: /^(?:yeni sohbet|sohbeti (?:sıfırla|temizle)|baştan başla)$/,
    handler: () => { G().resetChat(); Voice.flash('Yeni sohbet başladı'); } },
  { name: 'paneli kapat', pattern: /^(?:kapat|paneli kapat|temizle|geri dön)$/,
    handler: () => { if (!G().clearFocus) return false; G().clearFocus(); } },
  { name: 'mikrofonu kapat', pattern: /^(?:mikrofonu kapat|dinlemeyi (?:bırak|durdur)|beni dinleme)$/,
    handler: () => { Voice.stopListening(); } },
  { name: 'not aç', pattern: /^(?:(.+?)\s+(?:notunu|notu|sayfasını)\s+(?:aç|göster)|(?:aç|göster)\s+(.+))$/,
    handler: (m) => {
      if (!G().findNode) return false;        // bu sayfada not yok -> beyne gönder
      const id = G().findNode(m[1] || m[2]);
      if (id == null) return false;           // bulunamadı -> soruyu beyne gönder
      G().focusNode(id);
      Voice.flash('Açıldı: ' + G().nodes[id].label);
    } },
];

const G = () => window.__app;      // her sayfa kendi ask/resetChat fonksiyonlarını yayınlar

const Voice = (() => {
  const statusEl = document.getElementById('status');
  const statusText = document.getElementById('statusText');
  const liveEl = document.getElementById('live');
  const micBtn = document.getElementById('mic');

  // --- durum ---
  const st = { listening: false, thinking: 0, preparing: false, speaking: false, flash: '', flashTimer: 0,
              talking: false, micLevel: 0, awake: false, awakeTimer: 0 };

  function render() {
    let mode = 'idle', text = 'Hazır';
    if (st.speaking) { mode = 'speaking'; text = 'Konuşuyor…'; }
    else if (st.thinking > 0 || st.preparing) { mode = 'thinking'; text = 'Düşünüyor…'; }
    else if (st.listening) { mode = 'listening'; text = st.awake ? 'Uyandım · dinliyorum…' : 'Dinliyor…'; }
    if (st.flash) text = st.flash;
    else if (mode === 'idle' && !audio.unlocked && pendingSpeech) text = 'Yanıtı duymak için sayfaya bir kez tıklayın';
    else if (mode === 'idle' && isMuted()) text = 'Hazır · sessiz mod (?mute=1)';
    if (statusEl.dataset.mode !== mode) document.dispatchEvent(new CustomEvent('voice:state', { detail: mode }));
    statusEl.dataset.mode = mode;
    statusText.textContent = text;
    micBtn.classList.toggle('on', st.listening);
    micBtn.setAttribute('aria-pressed', String(st.listening));
  }
  function flash(msg, ms = 2600) {
    st.flash = msg; clearTimeout(st.flashTimer);
    st.flashTimer = setTimeout(() => { st.flash = ''; render(); }, ms);
    render();
  }
  const isMuted = () => new URLSearchParams(location.search).get('mute') === '1';

  // --- ses kilidi: tarayıcılar ilk tıklamadan önce ses çalmayı engeller ---
  const audio = { ctx: null, analyser: null, unlocked: false, source: null, fetchCtl: null, gen: 0 };
  let pendingSpeech = null;

  function unlockAudio() {
    if (audio.unlocked) return;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      audio.ctx = new AC();
      audio.ctx.resume();
      audio.analyser = audio.ctx.createAnalyser();         // arayüz görselleştirmesi için ses seviyesi
      audio.analyser.fftSize = 256;
      audio.analyser.connect(audio.ctx.destination);
      const b = audio.ctx.createBuffer(1, 1, 22050), s = audio.ctx.createBufferSource();
      s.buffer = b; s.connect(audio.ctx.destination); s.start(0);   // sessiz "ısınma"
      audio.unlocked = true;
    } catch (e) { console.warn('AudioContext açılamadı', e); return; }
    document.removeEventListener('click', unlockAudio, true);
    if (pendingSpeech) { const t = pendingSpeech; pendingSpeech = null; playGeminiAudio(t); }
    render();
  }
  document.addEventListener('click', unlockAudio, true);   // YALNIZCA tıklama

  function stopPlayback() {
    if (audio.source) { try { audio.source.onended = null; audio.source.stop(); } catch {} audio.source = null; }
    if (audio.fetchCtl) { audio.fetchCtl.abort(); audio.fetchCtl = null; }
    if (st.speaking) speechEndedAt = performance.now();
    st.speaking = false; st.preparing = false;
  }

  // ---------------------------------------------------------------------------
  // Gemini sesini çalan TEK fonksiyon. Sessiz mod kontrolü burada ve yalnızca burada:
  // ?mute=1 varsa bu sekmede hiçbir şey konuşmaz (API çağrısı da yapılmaz).
  // ---------------------------------------------------------------------------
  async function playGeminiAudio(text) {
    if (new URLSearchParams(location.search).get('mute') === '1') { render(); return; }
    text = (text || '').trim();
    if (!text) return;
    if (!audio.unlocked) { pendingSpeech = text; render(); return; }   // ilk tıklamada çalınır

    stopPlayback();
    const gen = ++audio.gen, ctl = new AbortController();
    audio.fetchCtl = ctl; st.preparing = true; render();
    try {
      const res = await fetch('/speak', { method: 'POST', signal: ctl.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
      if (!res.ok) {
        let msg = 'Ses üretilemedi';
        try { msg = (await res.json()).error || msg; } catch {}
        throw new Error(msg);
      }
      const buf = await res.arrayBuffer();
      if (gen !== audio.gen) return;                         // bu arada kesildi
      if (audio.ctx.state === 'suspended') await audio.ctx.resume();
      const decoded = await audio.ctx.decodeAudioData(buf);
      if (gen !== audio.gen) return;
      const src = audio.ctx.createBufferSource();
      src.buffer = decoded; src.connect(audio.analyser);
      src.onended = () => { if (audio.source === src) { audio.source = null; st.speaking = false; speechEndedAt = performance.now(); render(); } };
      audio.source = src; audio.fetchCtl = null;
      st.preparing = false; st.speaking = true; render();
      src.start();
    } catch (e) {
      if (e.name === 'AbortError' || gen !== audio.gen) return;
      st.preparing = false; st.speaking = false;
      console.warn('Konuşma hatası:', e.message);
      flash('Ses yok: ' + e.message.slice(0, 140), 6000);
    } finally {
      if (gen === audio.gen && !st.speaking) { st.preparing = false; render(); }
    }
  }

  function interrupt() {
    audio.gen++;                 // geç gelen sesi de iptal et
    pendingSpeech = null;
    stopPlayback();
    clearBuffer();
    render();
    document.dispatchEvent(new CustomEvent('voice:interrupt'));
  }

  // ---------------------------------------------------------------------------
  // Dinleme: MediaRecorder + sessizlik algılama (yalnızca ses seviyesi ölçümü, yapay zekâ değil)
  // + Groq Whisper Large V3 (sunucudaki POST /listen). Tampon mantığı aynı:
  //   konuşma bitince FINISH_MS (900 ms) beklenir; bu sürede yeni konuşma gelirse aynı kayda eklenir
  //   ve sayaç baştan başlar; yalnızca düşünceyi gerçekten bitiren duraklama sesi gönderir.
  // Kesme sözcükleri ("dur", "bekle"): tek ve kısa bir ses patlaması FAST_GAP_MS sonra hemen
  //   Groq'a sorulur; sonuç kesme sözcüğüyse tampon beklenmeden ANINDA çalışır.
  // ---------------------------------------------------------------------------
  const VAD = {
    FRAME_MS: 20,          // ölçüm aralığı
    ONSET_FRAMES: 2,       // konuşma başladı demek için art arda gereken yüksek kare (~40 ms)
    MIN_SPEECH_MS: 220,    // bundan kısa sesler (öksürük, tık) gönderilmez
    FAST_GAP_MS: 280,      // kısa tek patlamadan sonra kesme kontrolü için bekleme
    FAST_MIN_MS: 150,      // bundan kısa tıkırtılar için kesme kontrolü yapılmaz
    FAST_MAX_MS: 1100,     // kesme sözcüğü sayılacak en uzun patlama
    MAX_UTTER_MS: 30000,   // tek cümle en fazla 30 sn
    IDLE_ROTATE_MS: 2500,  // sessizken kaydı tazele (gönderilen sesin başında uzun sessizlik olmasın)
    FLOOR_MIN: 0.002, ON_MIN: 0.015, ON_FACTOR: 3.2, OFF_RATIO: 0.65,
  };
  const MIME = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4', 'audio/webm']
    .find(t => window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) || '';

  const mic = { stream: null, ctx: null, analyser: null, data: null, loop: 0, rec: null, noise: 0.004,
                onFrames: 0, talking: false, lastVoiceAt: 0, utter: null, lastFastAt: 0 };
  let wantListening = false, speechEndedAt = 0, sendQueue = Promise.resolve(), lastHeard = '';

  const norm = s => s.toLocaleLowerCase('tr-TR').replace(/[.,!?;:…"“”'’]/g, ' ').replace(/\s+/g, ' ').trim();
  const now = () => performance.now();
  const inEcho = () => st.speaking || now() - speechEndedAt < ECHO_GUARD_MS;

  function showLive(text) { liveEl.textContent = text || ''; }
  function clearBuffer() {           // kesme: bekleyen cümleyi at, kaydı tazele
    if (mic.utter) mic.utter.cancelled = true;
    mic.utter = null;
    if (mic.rec) rotateRecorder(false);
    showLive('');
  }

  // --- kayıt: her cümle kendi bağımsız (başlıklı) ses dosyası olsun diye kaydedici yenilenir ---
  function newRecorder() {
    const r = new MediaRecorder(mic.stream, MIME ? { mimeType: MIME } : undefined);
    const box = { r, chunks: [], startedAt: now(), waiters: [] };
    r.ondataavailable = e => { if (e.data && e.data.size) box.chunks.push(e.data); box.waiters.splice(0).forEach(f => f()); };
    r.start();
    return box;
  }
  function blobOf(box) { return new Blob(box.chunks, { type: box.r.mimeType || MIME || 'audio/webm' }); }
  // Kaydı kapat, yenisini hemen başlat; keep=true ise kapanan kaydın sesini döndür.
  function rotateRecorder(keep) {
    const old = mic.rec;
    mic.rec = (wantListening && mic.stream) ? newRecorder() : null;   // dinleme kapanıyorsa yenisini açma
    if (!old) return Promise.resolve(null);
    return new Promise(resolve => {
      old.r.onstop = () => resolve(keep ? blobOf(old) : null);
      try { old.r.stop(); } catch { resolve(null); }
    });
  }
  // Kaydı durdurmadan şu ana kadarki sesi al (kesme sözcüğü kontrolü için)
  function snapshot() {
    const box = mic.rec;
    return new Promise(resolve => {
      box.waiters.push(() => resolve(blobOf(box)));
      try { box.r.requestData(); } catch { resolve(blobOf(box)); }
    });
  }

  async function transcribe(blob) {
    const res = await fetch('/listen', { method: 'POST', headers: { 'Content-Type': blob.type || 'audio/webm' }, body: blob });
    let data = {};
    try { data = await res.json(); } catch {}
    if (!res.ok) throw new Error(data.error || `Sunucu ${res.status} döndürdü`);
    return (data.text || '').trim();
  }

  // Tamamlanmış bir cümle: önce ses komutları, sonra beyin (/jarvis ya da /chat — yazılı soruyla aynı akış).
  function dispatch(sentence) {
    const w = norm(sentence).match(WAKE_RE);
    if (w) {                                   // "Hey Jarvis …" / "Tahta …": hitabı at, gerisini işle
      const rest = sentence.slice(sentence.toLocaleLowerCase('tr-TR').search(/jarvis|jarvıs|carvis|cervis|jervis|ciarvis|çarvis|tahta/))
        .replace(/^\S+?(?:[\s,!.:]+|$)/, '').trim();
      if (!rest) { awaken(); playGeminiAudio(wakeReply); return; }
      sentence = rest;
    }
    if (st.awake) setAwake(false);
    const n = norm(sentence);
    for (const route of VOICE_ROUTES) {
      const m = n.match(route.pattern);
      if (m && route.handler(m, sentence) !== false) return;
    }
    G().ask(sentence);
  }

  // Tam cümle: Groq -> metin -> ses komutları -> beyin (yazılı soruyla aynı akış). Sırayla işlenir.
  function finalize(u) {
    mic.utter = null;
    const usable = !u.cancelled && !u.echo && u.voicedMs >= VAD.MIN_SPEECH_MS;
    const audioP = rotateRecorder(usable);
    if (!usable) { showLive(''); return; }
    st.thinking++; render(); showLive('… metne çevriliyor');
    sendQueue = sendQueue.then(async () => {
      try {
        const blob = await audioP;
        if (!blob || u.cancelled) return;
        const text = await transcribe(blob);
        if (u.cancelled) return;
        lastHeard = text;
        if (!text) { showLive(''); flash('Anlaşılır bir konuşma duyulmadı', 2000); return; }
        showLive('“' + text + '”');
        dispatch(text);
      } catch (e) {
        showLive(''); flash('Dinleme hatası: ' + e.message.slice(0, 140), 6000);
        if (/Groq API anahtar/i.test(e.message) && G().openSettings) G().openSettings();
      } finally {
        st.thinking = Math.max(0, st.thinking - 1); render();
      }
    });
  }

  // Kısa tek patlama: kesme sözcüğü mü? Öyleyse tamponu atlayıp hemen çalıştır.
  async function fastCheck(u) {
    mic.lastFastAt = now();
    try {
      const text = await transcribe(await snapshot());
      const n = norm(text);
      if (INTERRUPT_RE.test(n) && !u.cancelled && (mic.utter === u || !mic.utter)) {
        u.cancelled = true;
        if (mic.utter === u) mic.utter = null;
        rotateRecorder(false);
        lastHeard = text; showLive('“' + text + '”');
        dispatch(n);
      }
    } catch { /* hızlı kontrol başarısızsa normal akış devam eder */ }
  }

  function tick() {
    const a = mic.analyser; if (!a) return;
    a.getFloatTimeDomainData(mic.data);
    let sum = 0; for (let i = 0; i < mic.data.length; i++) sum += mic.data[i] * mic.data[i];
    const rms = Math.sqrt(sum / mic.data.length), t = now();
    if (!mic.talking) mic.noise = Math.max(VAD.FLOOR_MIN, mic.noise * 0.95 + rms * 0.05);   // uyarlanır gürültü tabanı
    const on = Math.max(VAD.ON_MIN, mic.noise * VAD.ON_FACTOR), off = on * VAD.OFF_RATIO;
    st.micLevel = Math.min(1, rms / (on * 1.5));

    if (rms > on) mic.onFrames++; else mic.onFrames = 0;
    if (!mic.talking && mic.onFrames >= VAD.ONSET_FRAMES) {                // konuşma başladı
      mic.talking = true;
      if (!mic.utter) mic.utter = { start: t, voicedMs: 0, bursts: 0, burstStart: t, echo: inEcho(), cancelled: false, fastSent: false };
      else mic.utter.burstStart = t;                                     // duraklamadan sonra devam: aynı kayda ekle
      mic.utter.bursts++;
      st.talking = true; showLive('● konuşma algılandı');
    }
    if (mic.talking) {
      if (rms > off) { mic.lastVoiceAt = t; mic.utter.voicedMs += VAD.FRAME_MS; }
      else if (t - mic.lastVoiceAt > 120) { mic.talking = false; st.talking = false; mic.utter.lastBurstMs = mic.lastVoiceAt - mic.utter.burstStart; }
    }
    const u = mic.utter;
    if (u && !mic.talking) {
      const silence = t - mic.lastVoiceAt;
      if (!u.fastSent && u.bursts === 1 && silence >= VAD.FAST_GAP_MS && u.lastBurstMs >= VAD.FAST_MIN_MS && u.lastBurstMs <= VAD.FAST_MAX_MS
          && (!u.echo || t - mic.lastFastAt > 1500)) { u.fastSent = true; fastCheck(u); }
      if (silence >= FINISH_MS) finalize(u);                             // gerçekten biten düşünce
    }
    if (u && t - u.start > VAD.MAX_UTTER_MS) finalize(u);
    if (!mic.utter && mic.rec && t - mic.rec.startedAt > VAD.IDLE_ROTATE_MS) rotateRecorder(false);
  }

  async function startListening() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder)
      return flash('Bu tarayıcı mikrofon kaydını desteklemiyor', 5000);
    if (wantListening) return;
    wantListening = true;
    try {
      mic.stream = await navigator.mediaDevices.getUserMedia({ audio: {
        echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    } catch (e) {
      wantListening = false;
      return flash(e.name === 'NotAllowedError' ? 'Mikrofon izni verilmedi'
                 : e.name === 'NotFoundError' ? 'Mikrofon bulunamadı' : 'Mikrofon açılamadı: ' + e.message, 5000);
    }
    if (!wantListening) { mic.stream.getTracks().forEach(t => t.stop()); return; }
    const AC = window.AudioContext || window.webkitAudioContext;
    mic.ctx = new AC();
    mic.analyser = mic.ctx.createAnalyser(); mic.analyser.fftSize = 1024;
    mic.ctx.createMediaStreamSource(mic.stream).connect(mic.analyser);
    mic.data = new Float32Array(mic.analyser.fftSize);
    mic.rec = newRecorder();
    mic.talking = false; mic.onFrames = 0; mic.utter = null;
    mic.loop = setInterval(tick, VAD.FRAME_MS);
    st.listening = true; render();
    reportListening(true);                   // daemon.py bu sırada uyandırma sözcüğü aramaz (Groq kotası)
    mic.stream.getAudioTracks()[0].onended = () => { stopListening(); flash('Mikrofon bağlantısı kesildi', 4000); };
  }

  function stopListening() {
    wantListening = false;
    clearInterval(mic.loop); mic.loop = 0;
    if (mic.utter && !mic.utter.cancelled) finalize(mic.utter);      // söylenmiş olanı yine de gönder
    const rec = mic.rec; mic.rec = null;
    if (rec) { rec.r.onstop = () => {}; try { if (rec.r.state !== 'inactive') rec.r.stop(); } catch {} }
    if (mic.stream) mic.stream.getTracks().forEach(t => t.stop());
    if (mic.ctx) mic.ctx.close().catch(() => {});
    Object.assign(mic, { stream: null, ctx: null, analyser: null, talking: false, utter: null });
    st.listening = false; st.talking = false; st.micLevel = 0; render();
    reportListening(false);
  }
  if (!navigator.mediaDevices || !window.MediaRecorder) { micBtn.disabled = true; micBtn.title = 'Bu tarayıcı mikrofon kaydını desteklemiyor'; }
  micBtn.title = micBtn.disabled ? micBtn.title : 'Konuşarak sor (Groq Whisper, Türkçe)';
  micBtn.addEventListener('click', () => (wantListening ? stopListening() : startListening()));

  function reportListening(on) {
    fetch('/ui/state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ listening: on }) }).catch(() => {});
  }

  // --- uyandırma: daemon.py "Hey Jarvis"/"Tahta" duyunca POST /wake → /events (SSE) → bu sayfa ---
  let wakeReply = 'Dinliyorum, Hocam.';
  fetch('/boot').then(r => r.json()).then(b => { if (b.wake_reply) wakeReply = b.wake_reply; }).catch(() => {});
  const postJSON = (url, data) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data || {}) });

  function setAwake(on) {
    st.awake = on; clearTimeout(st.awakeTimer);
    if (on) st.awakeTimer = setTimeout(() => { st.awake = false; render(); }, 15000);
    render();
  }
  function awaken() { setAwake(true); if (!wantListening) startListening(); }
  function dropMuteParam() {                 // sessiz moddan çık: ?mute=1 adresten kalkar (kontrol yine playGeminiAudio'da)
    const u = new URL(location.href);
    if (u.searchParams.get('mute') !== '1') return;
    u.searchParams.delete('mute');
    history.replaceState(history.state, '', u);
    render();
  }
  async function onWake(d) {
    // Birden fazla sayfa açıksa olayı yalnızca biri üstlenir. Öncelik: sesi çalabilen görünür sekme,
    // sesi çalabilen arka plan sekmesi, sesi kilitli görünür sekme, sesi kilitli arka plan sekmesi.
    const visible = document.visibilityState === 'visible';
    const wait = audio.unlocked ? (visible ? 0 : 200) : (visible ? 400 : 600);
    if (wait) await new Promise(r => setTimeout(r, wait));
    let claimed = false;
    try { claimed = (await (await postJSON('/wake/claim', { seq: d.seq })).json()).ok; } catch {}
    if (!claimed) return;
    dropMuteParam();
    interrupt();
    awaken();
    const spoken = audio.unlocked;           // ses kilidi açık değilse "Dinliyorum" sesini daemon.py çalar
    if (spoken) playGeminiAudio(d.reply || wakeReply);
    else speechEndedAt = performance.now() + 1800;   // daemon'un sesini mikrofon duymasın
    flash(d.reply || wakeReply, 2500);
    postJSON('/wake/ack', { seq: d.seq, spoken }).catch(() => {});
    if (d.text) dispatch(d.text);            // "Hey Jarvis, aşağı kaydır" — komut aynı cümledeyse hemen işle
  }
  if (window.EventSource) {
    const es = new EventSource('/events');
    es.addEventListener('wake', e => { try { onWake(JSON.parse(e.data)); } catch {} });
    es.addEventListener('unmute', () => dropMuteParam());
  }
  if (new URLSearchParams(location.search).get('mute') === '1') postJSON('/mute').catch(() => {});
  if (new URLSearchParams(location.search).get('wake') === '1') {   // daemon.py pencere yokken sayfayı açtı
    const u = new URL(location.href); u.searchParams.delete('wake'); history.replaceState(history.state, '', u);
    window.addEventListener('load', () => { awaken(); flash(wakeReply, 2500); });
  }

  // --- galaksiden gelen olaylar ---
  document.addEventListener('app:thinking', e => { st.thinking = Math.max(0, st.thinking + (e.detail ? 1 : -1)); render(); });
  document.addEventListener('app:answer', e => { if (e.detail && e.detail.answer) playGeminiAudio(e.detail.answer); });
  document.addEventListener('app:reset', () => interrupt());

  render();
  return { playGeminiAudio, interrupt, flash, startListening, stopListening, dispatch, onWake,
           get analyser() { return audio.analyser; },
           get state() { return { ...st, unlocked: audio.unlocked, utterance: !!mic.utter, lastHeard, pendingSpeech } } };
})();

window.VOICE_ROUTES = VOICE_ROUTES;
window.Voice = Voice;
