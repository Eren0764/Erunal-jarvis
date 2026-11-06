// memory.js — "Hafıza" çekmecesi: Jarvis'in kaydettiği notları (captures/) listeler, tek tek siler,
// hepsini sıfırlar. Her iki sayfada da çalışır (index.html ve galaxy.html).
//
//  * Sunucu: GET /remember, DELETE /remember/<dosya>, DELETE /remember/all (server.py).
//  * Onay cümleleri sunucudan gelir ve Gemini sesiyle okunur ('app:answer' -> voice.js -> playGeminiAudio).
//    Tarayıcının kendi konuşma motoru KULLANILMAZ.
//  * Değişiklikler BroadcastChannel ile diğer sekmelere duyurulur; galaksi sayfası silinen yıldızı
//    söndürüp grafiği yeniden yüklemeden günceller (window.__galaxy.syncGraph).
//  * Anahtar ya da not içeriği konsola yazılmaz.
const Memory = (() => {
  const $ = id => document.getElementById(id);
  const chan = 'BroadcastChannel' in window ? new BroadcastChannel('jarvis-memory') : null;
  const speak = text => text && document.dispatchEvent(new CustomEvent('app:answer', { detail: { answer: text } }));
  const req = (method, url) => fetch(url, { method, headers: { 'Content-Type': 'application/json' } });

  // ------------------------------------------------------------------ stil (sayfanın tema değişkenleri)
  const css = document.createElement('style');
  css.textContent = `
  #memDrawer { position: fixed; top: 12px; right: 12px; bottom: 12px; width: min(400px, calc(100% - 24px)); z-index: 20;
    display: flex; flex-direction: column; padding: 18px 18px 14px; transform: translateX(calc(100% + 24px));
    transition: transform .35s cubic-bezier(.2,.8,.2,1); }
  #memDrawer.open { transform: none; }
  #memDrawer h2 { margin: 0; font-size: 17px; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; }
  #memDrawer .sum { margin: 4px 0 12px; font-size: 12px; color: var(--muted); }
  #memDrawer .x { all: unset; cursor: pointer; position: absolute; top: 12px; right: 16px; font-size: 22px; color: var(--muted); }
  #memList { flex: 1; overflow-y: auto; margin: 0 -6px; padding: 0 6px; }
  #memList .empty { color: var(--muted); font-size: 13px; padding: 18px 4px; line-height: 1.6; }
  .memItem { border: 1px solid var(--edge); border-radius: 12px; padding: 11px 12px; margin-bottom: 9px;
    background: rgba(255,255,255,.025); transition: opacity .45s, transform .45s, max-height .45s .1s, margin .45s .1s, padding .45s .1s;
    max-height: 260px; overflow: hidden; }
  .memItem.gone { opacity: 0; transform: translateX(40px) scale(.96); max-height: 0; margin: 0; padding-top: 0; padding-bottom: 0; }
  .memItem .top { display: flex; gap: 8px; align-items: flex-start; }
  .memItem h3 { flex: 1; margin: 0; font-size: 14px; font-weight: 600; line-height: 1.35; cursor: default; }
  .memItem.link h3 { cursor: pointer; } .memItem.link h3:hover { color: var(--accent); }
  .memItem .meta { font-size: 11px; color: var(--muted); margin: 3px 0 6px; font-variant-numeric: tabular-nums; }
  .memItem p { margin: 0; font-size: 12.5px; color: #c3cbe0; line-height: 1.5; display: -webkit-box;
    -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .memItem .del { all: unset; cursor: pointer; font-size: 12px; padding: 3px 10px; border-radius: 999px;
    border: 1px solid rgba(255,138,122,.35); color: var(--danger); white-space: nowrap; }
  .memItem .del:hover { background: rgba(255,138,122,.12); }
  .memItem .del:disabled { opacity: .5; cursor: default; }
  #memReset { all: unset; cursor: pointer; margin-top: 12px; text-align: center; padding: 11px; border-radius: 12px;
    font-weight: 600; letter-spacing: .06em; color: #fff; background: linear-gradient(90deg, rgba(255,90,70,.75), rgba(255,138,122,.55));
    box-shadow: 0 0 22px rgba(255,100,80,.25); }
  #memReset:hover { box-shadow: 0 0 30px rgba(255,100,80,.45); }
  #memReset:disabled { opacity: .35; cursor: default; box-shadow: none; }
  #memMsg { min-height: 18px; margin-top: 8px; font-size: 12.5px; text-align: center; color: var(--muted); }
  #memMsg.bad { color: var(--danger); } #memMsg.ok { color: #7dffb8; }
  #memConfirm { position: fixed; inset: 0; z-index: 30; display: none; place-items: center; background: rgba(0,0,0,.55); }
  #memConfirm.show { display: grid; }
  #memConfirm .box { width: min(380px, calc(100% - 32px)); padding: 22px 22px 18px; text-align: center; animation: memPop .25s ease; }
  #memConfirm p { margin: 0 0 18px; font-size: 15px; line-height: 1.5; }
  #memConfirm .row { display: flex; gap: 10px; justify-content: center; }
  #memConfirm button { all: unset; cursor: pointer; padding: 9px 18px; border-radius: 999px; font-weight: 600; font-size: 13px; }
  #memConfirm .yes { background: var(--danger); color: #1a0705; }
  #memConfirm .no { border: 1px solid var(--edge); color: var(--ink); }
  @keyframes memPop { from { opacity: 0; transform: scale(.94); } to { opacity: 1; transform: none; } }
  @media (prefers-reduced-motion: reduce) { #memDrawer, .memItem { transition: none; } }`;
  document.head.appendChild(css);

  // ------------------------------------------------------------------ yapı
  const drawer = document.createElement('aside');
  drawer.id = 'memDrawer'; drawer.className = 'glass'; drawer.setAttribute('aria-label', 'Hafıza');
  drawer.innerHTML = `
    <button class="x" id="memClose" aria-label="Kapat" title="Kapat">×</button>
    <h2>Hafıza</h2>
    <div class="sum" id="memSum">Yükleniyor…</div>
    <div id="memList" role="list"></div>
    <button type="button" id="memReset">Hafızayı Sıfırla</button>
    <div id="memMsg" role="status" aria-live="polite"></div>`;
  const confirmEl = document.createElement('div');
  confirmEl.id = 'memConfirm'; confirmEl.setAttribute('role', 'alertdialog'); confirmEl.setAttribute('aria-modal', 'true');
  confirmEl.innerHTML = `<div class="box glass"><p>Tüm kayıtlı hafızayı silmek istediğinizden emin misiniz?</p>
    <div class="row"><button type="button" class="no" id="memNo">Vazgeç</button><button type="button" class="yes" id="memYes">Evet, sıfırla</button></div></div>`;
  document.body.append(drawer, confirmEl);

  const msg = (t, cls) => { $('memMsg').textContent = t || ''; $('memMsg').className = cls || ''; };
  let items = [];

  function fmtSize(c) { return `~${c.tokens.toLocaleString('tr-TR')} token · ${c.chars.toLocaleString('tr-TR')} karakter`; }

  function render() {
    const list = $('memList');
    list.replaceChildren();
    const total = items.reduce((a, c) => a + c.tokens, 0);
    $('memSum').textContent = items.length ? `${items.length} kayıt · toplam ~${total.toLocaleString('tr-TR')} token` : 'Kayıt yok';
    $('memReset').disabled = !items.length;
    if (!items.length) {
      const e = document.createElement('div'); e.className = 'empty';
      e.textContent = 'Hafıza boş. Jarvis\'e “Bunu hatırla: …” dediğinizde not buraya kaydedilir.';
      list.appendChild(e);
      return;
    }
    const g = window.__galaxy;
    [...items].reverse().forEach(c => {                     // en yenisi üstte
      const el = document.createElement('div');
      el.className = 'memItem' + (g ? ' link' : ''); el.setAttribute('role', 'listitem'); el.dataset.file = c.filename;
      el.innerHTML = `<div class="top"><h3></h3><button type="button" class="del">Sil</button></div><div class="meta"></div><p></p>`;
      el.querySelector('h3').textContent = c.title;
      el.querySelector('.meta').textContent = `${c.date}  ·  ${fmtSize(c)}`;
      el.querySelector('p').textContent = c.excerpt;
      el.querySelector('.del').setAttribute('aria-label', `“${c.title}” notunu sil`);
      el.querySelector('.del').addEventListener('click', () => removeOne(c, el));
      if (g) el.querySelector('h3').addEventListener('click', () => {
        const n = g.nodes.find(n => n.path === 'captures/' + c.filename);
        if (n) g.focusNode(n.id);
      });
      list.appendChild(el);
    });
  }

  async function refresh() {
    try {
      const r = await fetch('/remember');
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Hafıza okunamadı');
      items = d.captures || [];
      render();
    } catch (e) { $('memSum').textContent = ''; msg(e.message, 'bad'); }
  }

  async function removeOne(c, el) {
    el.querySelector('.del').disabled = true; msg('');
    try {
      const r = await req('DELETE', '/remember/' + encodeURIComponent(c.filename));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Silinemedi');
      el.classList.add('gone');
      speak(d.spoken);                                     // Gemini sesi: "İlgili not hafızadan silindi, Hocam."
      msg(`“${c.title}” silindi.`, 'ok');
      setTimeout(() => { items = items.filter(x => x.filename !== c.filename); render(); }, 560);
      changed(d);
    } catch (e) { el.querySelector('.del').disabled = false; msg(e.message, 'bad'); }
  }

  function askReset() { confirmEl.classList.add('show'); $('memNo').focus(); }
  function closeConfirm() { confirmEl.classList.remove('show'); }
  async function resetAll() {
    closeConfirm(); msg('Sıfırlanıyor…');
    try {
      const r = await req('DELETE', '/remember/all');
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Sıfırlanamadı');
      document.querySelectorAll('.memItem').forEach((el, i) => setTimeout(() => el.classList.add('gone'), i * 60));
      speak(d.spoken);                                     // Gemini sesi: "Tüm hafıza sıfırlandı, Hocam."
      msg('Tüm hafıza silindi.', 'ok');
      setTimeout(() => { items = []; render(); }, 600);
      changed(d);
    } catch (e) { msg(e.message, 'bad'); }
  }

  // ------------------------------------------------------------------ eşitleme
  // info: sunucu yanıtı ({removed: [...], capture: {...}}). Yerelde uygula + diğer sekmelere duyur.
  function apply(info) {
    const removed = (info.removed || []).map(f => 'captures/' + f);
    if (window.__galaxy && window.__galaxy.syncGraph) window.__galaxy.syncGraph(removed);
    if (drawer.classList.contains('open')) refresh();
    const nc = document.getElementById('noteCount');
    if (nc && typeof info.count === 'number') updateCount();
  }
  async function updateCount() {
    try {
      const t = await (await fetch('/graph-data.js', { cache: 'no-store' })).text();
      const n = JSON.parse(t.slice(t.indexOf('{'), t.lastIndexOf('}') + 1)).nodes.length;
      document.getElementById('noteCount').textContent = `${n} not / ders dosyası indekslendi`;
    } catch {}
  }
  function changed(info) {
    if (!info || !(info.removed || info.capture)) return;
    apply(info);
    if (chan) chan.postMessage({ removed: info.removed || [], capture: !!info.capture, count: info.count });
  }
  if (chan) chan.onmessage = e => apply(e.data || {});

  // Sesli hafıza komutları (galaksi sayfası /chat kullandığı için doğrudan /jarvis'e gider).
  async function voice(text) {
    try {
      const r = await fetch('/jarvis', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
      const d = await r.json();
      const reply = typeof d.error === 'string' ? d.error : d.reply;
      if (window.Voice) Voice.flash(reply, 5000);
      speak(reply);
      if (d.memory && d.memory.confirm === 'reset') { open(); askReset(); }
      else if (d.memory) changed(d.memory);
    } catch { if (window.Voice) Voice.flash('Sunucuya ulaşılamadı', 4000); }
  }

  // ------------------------------------------------------------------ aç / kapat
  function open() {
    drawer.classList.add('open'); msg(''); refresh();
    document.querySelectorAll('[data-memory-button]').forEach(b => b.setAttribute('aria-expanded', 'true'));
  }
  function close() {
    drawer.classList.remove('open'); closeConfirm();
    document.querySelectorAll('[data-memory-button]').forEach(b => b.setAttribute('aria-expanded', 'false'));
  }
  document.querySelectorAll('[data-memory-button]').forEach(b =>
    b.addEventListener('click', () => drawer.classList.contains('open') ? close() : open()));
  $('memClose').addEventListener('click', close);
  $('memReset').addEventListener('click', askReset);
  $('memNo').addEventListener('click', closeConfirm);
  $('memYes').addEventListener('click', resetAll);
  confirmEl.addEventListener('click', e => { if (e.target === confirmEl) closeConfirm(); });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (confirmEl.classList.contains('show')) closeConfirm(); else if (drawer.classList.contains('open')) close();
  });

  return { open, close, refresh, changed, voice, askReset };
})();
window.Memory = Memory;

// Sesli komutlar: hafıza cümleleri her iki sayfada da aynı yoldan (/jarvis) işlenir.
if (typeof VOICE_ROUTES !== 'undefined') {
  VOICE_ROUTES.unshift(
    { name: 'hafıza aç', pattern: /^(?:jarvis )?hafızayı (?:aç|göster)$/, handler: () => Memory.open() },
    { name: 'hafıza', pattern: /^(?:jarvis )?(?:(?:tüm )?hafızayı (?:sıfırla|sil|temizle|boşalt)|evet (?:sıfırla|sil|eminim)|sıfırlamayı onayla(?:yorum)?|hafızadan .+ sil|.+ (?:notunu|notu|kaydını|kaydı) (?:hafızadan )?sil|(?:bunu )?(?:hatırla|aklında tut|not al) .+)$/,
      handler: (m, sentence) => Memory.voice(sentence) },
  );
}
