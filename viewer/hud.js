// Jarvis HUD — dönen halkalar, durum renkleri ve animasyonlar (canvas 2D, kütüphane yok).
//
//   Hazır      : soluk camgöbeği, halkalar neredeyse durgun, hafif nefes alma
//   Dinliyor   : MAVİ — halkalar döner, çentikler gerçek mikrofon seviyesiyle oynar, dalgalar yayılır, radar taraması
//   Düşünüyor  : SARI — halkalar hızlı ve ters yönde döner, segment bandı dolup boşalır, tarama ışını,
//                yörüngede veri parçacıkları, iç noktalar sırayla yanar
//   Konuşuyor  : parlak camgöbeği — bant ve dalga halkası Gemini sesinin gerçek seviyesine göre oynar
//
// Durum, voice.js'in yayınladığı 'voice:state' olayından gelir; ses seviyesi Voice.analyser'dan.
(() => {
  const cv = document.getElementById('sky');
  const g = cv.getContext('2d');
  const TAU = Math.PI * 2;

  // ---- durum paletleri (renk RGB, dönüş hızı, parlaklık, animasyon yoğunluğu) --------------------
  const STATES = {
    idle:      { main: [95, 212, 230],  accent: [120, 200, 255], spin: 0.05, glow: 0.30, energy: 0.0, label: 'HAZIR' },
    listening: { main: [52, 160, 255],  accent: [140, 210, 255], spin: 0.85, glow: 0.62, energy: 0.7, label: 'DİNLİYOR' },
    thinking:  { main: [255, 196, 46],  accent: [255, 140, 30],  spin: 1.9,  glow: 0.70, energy: 1.0, label: 'DÜŞÜNÜYOR' },
    speaking:  { main: [120, 238, 255], accent: [80, 190, 255],  spin: 0.35, glow: 0.55, energy: 0.6, label: 'KONUŞUYOR' },
  };
  let mode = 'idle';
  const cur = { main: [...STATES.idle.main], accent: [...STATES.idle.accent], spin: 0.05, glow: 0.3, energy: 0 };
  document.addEventListener('voice:state', e => { mode = STATES[e.detail] ? e.detail : 'idle'; });

  let W = 0, H = 0, DPR = 1, ox = 0, oy = 0, R = 150;
  let bg = null;                       // önceden çizilmiş plan (blueprint) arka planı
  const freq = new Uint8Array(128);

  // ---- rastgele ama sabit detaylar (her yeniden çizimde titremesin) ----------------------------------
  const rnd = (seed => () => (seed = (seed * 16807) % 2147483647) / 2147483647)(42);
  const outerSegs = Array.from({ length: 14 }, () => [rnd() * TAU, 0.08 + rnd() * 0.45]);
  const midSegs = Array.from({ length: 9 }, () => [rnd() * TAU, 0.15 + rnd() * 0.6]);
  const particles = Array.from({ length: 70 }, () => ({ r: 0.55 + rnd() * 0.9, a: rnd() * TAU, s: (rnd() - 0.5) * 2, z: rnd() }));
  const dust = Array.from({ length: 90 }, () => ({ x: rnd(), y: rnd(), v: 0.2 + rnd() * 0.8, s: rnd() }));

  function resize() {
    DPR = Math.min(2, devicePixelRatio || 1);
    W = innerWidth; H = innerHeight;
    cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
    g.setTransform(DPR, 0, 0, DPR, 0, 0);
    R = Math.max(90, Math.min(W * 0.26, H * 0.245, 300));
    ox = W / 2; oy = Math.max(R * 1.25 + 64, H * 0.41);
    // konuşma metni halkanın altına, sohbet çubuğunun üstüne
    const talkTop = Math.min(oy + R * 1.24 + 6, H - 210);
    document.documentElement.style.setProperty('--talk-top', talkTop + 'px');
    bg = drawBlueprint();
  }

  function drawBlueprint() {
    const c = document.createElement('canvas');
    c.width = cv.width; c.height = cv.height;
    const b = c.getContext('2d');
    b.setTransform(DPR, 0, 0, DPR, 0, 0);
    const grd = b.createRadialGradient(ox, oy, 0, ox, oy, Math.max(W, H) * 0.75);
    grd.addColorStop(0, '#0b2230'); grd.addColorStop(0.55, '#06141d'); grd.addColorStop(1, '#020509');
    b.fillStyle = grd; b.fillRect(0, 0, W, H);
    // ızgara
    b.lineWidth = 1;
    for (let x = (ox % 32); x < W; x += 32) { b.strokeStyle = (Math.round((x - ox) / 32) % 5 === 0) ? 'rgba(90,190,220,.07)' : 'rgba(90,190,220,.035)'; b.beginPath(); b.moveTo(x + .5, 0); b.lineTo(x + .5, H); b.stroke(); }
    for (let y = (oy % 32); y < H; y += 32) { b.strokeStyle = (Math.round((y - oy) / 32) % 5 === 0) ? 'rgba(90,190,220,.07)' : 'rgba(90,190,220,.035)'; b.beginPath(); b.moveTo(0, y + .5); b.lineTo(W, y + .5); b.stroke(); }
    // teknik çizim parçaları: daireler, dikdörtgenler, ölçü çizgileri
    const r2 = (s => () => (s = (s * 48271) % 2147483647) / 2147483647)(7);
    b.strokeStyle = 'rgba(110,200,230,.09)';
    for (let i = 0; i < 26; i++) {
      const x = r2() * W, y = r2() * H, s = 20 + r2() * 120;
      if (Math.hypot(x - ox, y - oy) < R * 1.5) continue;
      b.beginPath();
      if (r2() < 0.5) b.arc(x, y, s / 2, 0, TAU); else b.rect(x, y, s, s * (0.3 + r2()));
      b.stroke();
      if (r2() < 0.5) { b.beginPath(); b.moveTo(x - s, y); b.lineTo(x + s, y); b.stroke(); }
    }
    b.font = '9px ui-monospace, Menlo, monospace'; b.fillStyle = 'rgba(120,210,235,.16)';
    const words = ['SYS.CORE', 'TR-TR', 'NODE 07', 'API LINK', 'GRID 3.2', 'TELEMETRY', 'REF-41', 'MK.V', 'AUX', 'PWR'];
    for (let i = 0; i < 22; i++) {
      const x = r2() * W, y = r2() * H;
      if (Math.hypot(x - ox, y - oy) < R * 1.45) continue;
      b.fillText(words[i % words.length] + ' ' + Math.floor(r2() * 900 + 100), x, y);
    }
    // kenar köşebentleri
    b.strokeStyle = 'rgba(120,210,235,.25)'; b.lineWidth = 1.5;
    const m = 14, L = 36;
    [[m, m, 1, 1], [W - m, m, -1, 1], [m, H - m, 1, -1], [W - m, H - m, -1, -1]].forEach(([x, y, dx, dy]) => {
      b.beginPath(); b.moveTo(x, y + dy * L); b.lineTo(x, y); b.lineTo(x + dx * L, y); b.stroke();
    });
    // vinyet
    const v = b.createRadialGradient(ox, oy, Math.min(W, H) * 0.35, ox, oy, Math.max(W, H) * 0.8);
    v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,.65)');
    b.fillStyle = v; b.fillRect(0, 0, W, H);
    return c;
  }

  addEventListener('resize', resize);
  resize();

  // ---- yardımcılar -------------------------------------------------------------------------------
  const lerp = (a, b, k) => a + (b - a) * k;
  const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.max(0, Math.min(1, a))})`;
  function arc(r, a0, a1, w, color) { g.strokeStyle = color; g.lineWidth = w; g.beginPath(); g.arc(ox, oy, r, a0, a1); g.stroke(); }
  function spacedText(text, x, y, spacing) {
    let total = 0; const ws = [...text].map(ch => { const w = g.measureText(ch).width; total += w + spacing; return w; });
    total -= spacing; let cx = x - total / 2;
    [...text].forEach((ch, i) => { g.fillText(ch, cx + ws[i] / 2, y); cx += ws[i] + spacing; });
  }

  // ---- canlılık: dinlerken yeni kelime gelince nabız ----------------------------------------------
  let lastTalking = false, wordPulse = 0, level = 0, phase = 0, last = performance.now();
  let fill = 0;              // düşünürken dolan bant (0..1)
  const ripples = [];

  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const S = STATES[mode];
    const k = 1 - Math.pow(0.002, dt);           // ~yumuşak geçiş
    for (let i = 0; i < 3; i++) { cur.main[i] = lerp(cur.main[i], S.main[i], k); cur.accent[i] = lerp(cur.accent[i], S.accent[i], k); }
    cur.spin = lerp(cur.spin, S.spin, k); cur.glow = lerp(cur.glow, S.glow, k); cur.energy = lerp(cur.energy, S.energy, k);
    phase += dt * cur.spin;
    const t = now / 1000, E = cur.energy, M = cur.main, A = cur.accent;

    // seviye: konuşurken gerçek ses, dinlerken kelime nabzı + doğal dalgalanma
    let target = 0;
    const an = window.Voice && Voice.analyser;
    if (mode === 'speaking' && an) { an.getByteFrequencyData(freq); target = freq.reduce((s, v) => s + v, 0) / freq.length / 255 * 1.8; }
    else if (mode === 'listening') {
      // gerçek mikrofon seviyesi (voice.js ölçer); konuşma başlayınca nabız + dalga
      const st = window.Voice && Voice.state, talking = !!(st && st.talking), ml = st ? st.micLevel || 0 : 0;
      if (talking && !lastTalking) { wordPulse = 1; ripples.push({ r: 0.62, a: 0.75 }); }
      lastTalking = talking;
      target = 0.12 + 0.08 * Math.sin(t * 5.3) + ml * 0.95 + wordPulse * 0.35;
    } else if (mode === 'thinking') target = 0.45 + 0.25 * Math.sin(t * 3);
    wordPulse = Math.max(0, wordPulse - dt * 2.2);
    level = lerp(level, target, 1 - Math.pow(0.001, dt));
    if (mode === 'listening' && Math.random() < dt * 1.6) ripples.push({ r: 0.62, a: 0.55 });
    fill = mode === 'thinking' ? (fill + dt * 0.55) % 1.25 : lerp(fill, 0.72, k);

    // --- arka plan + toz -----------------------------------------------------------------------
    g.setTransform(1, 0, 0, 1, 0, 0); g.drawImage(bg, 0, 0); g.setTransform(DPR, 0, 0, DPR, 0, 0);
    for (const d of dust) {
      d.y -= dt * d.v * (0.006 + E * 0.03); if (d.y < 0) { d.y = 1; d.x = Math.random(); }
      g.fillStyle = rgba(A, 0.08 + d.s * 0.18 * (0.4 + E)); g.fillRect(d.x * W, d.y * H, 1.2, 1.2);
    }

    // --- dış parıltı ---------------------------------------------------------------------------
    const glow = g.createRadialGradient(ox, oy, R * 0.5, ox, oy, R * 1.9);
    glow.addColorStop(0, rgba(M, 0.18 * cur.glow + level * 0.08)); glow.addColorStop(0.5, rgba(M, 0.06 * cur.glow)); glow.addColorStop(1, rgba(M, 0));
    g.fillStyle = glow; g.beginPath(); g.arc(ox, oy, R * 1.9, 0, TAU); g.fill();

    g.save(); g.shadowColor = rgba(M, 0.9); g.shadowBlur = 10 + 14 * cur.glow; g.lineCap = 'butt';

    // --- yayılan dalgalar (dinlerken) ----------------------------------------------------------
    for (let i = ripples.length - 1; i >= 0; i--) {
      const p = ripples[i]; p.r += dt * 0.55; p.a -= dt * 0.45;
      if (p.a <= 0 || p.r > 1.6) { ripples.splice(i, 1); continue; }
      arc(R * p.r, 0, TAU, 1.5, rgba(M, p.a * 0.6));
    }

    // 1) en dış ince halka + yönlendirme üçgenleri
    arc(R * 1.2, 0, TAU, 1, rgba(M, 0.22));
    for (let i = 0; i < 4; i++) {
      const a = -phase * 0.12 + i * TAU / 4, x = ox + Math.cos(a) * R * 1.2, y = oy + Math.sin(a) * R * 1.2;
      g.save(); g.translate(x, y); g.rotate(a + Math.PI / 2); g.fillStyle = rgba(M, 0.75);
      g.beginPath(); g.moveTo(0, -5); g.lineTo(5, 4); g.lineTo(-5, 4); g.closePath(); g.fill(); g.restore();
    }

    // 2) dış segmentli halka (yavaş, saat yönü)
    for (const [a0, len] of outerSegs) arc(R * 1.13, a0 + phase * 0.22, a0 + phase * 0.22 + len, 2.5, rgba(M, 0.55 + E * 0.25));

    // 3) çentikli kadran (ters yön) — dinlerken ses dalgası gibi oynar, düşünürken kovalayan ışık
    const N = 144, rot3 = -phase * 0.35, chase = (t * 1.6 * (mode === 'thinking' ? 2 : 1)) % 1;
    for (let i = 0; i < N; i++) {
      const a = rot3 + i * TAU / N, major = i % 12 === 0, mid = i % 4 === 0;
      let len = major ? 14 : mid ? 9 : 5, alpha = major ? 0.9 : 0.45;
      if (mode === 'listening' || mode === 'speaking') len += level * 16 * (0.5 + 0.5 * Math.sin(i * 0.55 + t * 9)) * (mode === 'speaking' && an ? freq[i % 64] / 255 * 1.6 : 1);
      if (E > 0.05) { const d = Math.abs(((i / N - chase) % 1 + 1) % 1); if (d < 0.08) alpha = 1, len += 6 * E * (1 - d / 0.08); }
      const r0 = R * 1.0, c = Math.cos(a), s = Math.sin(a);
      g.strokeStyle = rgba(major ? A : M, alpha); g.lineWidth = major ? 2 : 1.2;
      g.beginPath(); g.moveTo(ox + c * r0, oy + s * r0); g.lineTo(ox + c * (r0 + len), oy + s * (r0 + len)); g.stroke();
    }

    // 4) kalın segment bandı (~240°) — düşünürken dolup boşalır, konuşurken frekansla oynar
    const B0 = Math.PI * 0.72 + phase * 0.18, SPAN = TAU * 0.66, NB = 56, rIn = R * 0.79, rOut = R * 0.93;
    for (let i = 0; i < NB; i++) {
      const u = i / NB, a0 = B0 + u * SPAN, a1 = a0 + SPAN / NB * 0.72;
      let on;
      if (mode === 'thinking') on = u < fill ? 0.85 : 0.12;
      else if (mode === 'speaking' && an) on = 0.15 + Math.min(1, freq[(i * 2) % 96] / 255 * 1.4) * 0.8;
      else if (mode === 'listening') on = 0.2 + 0.7 * Math.max(0, Math.sin(u * 9 - t * 6) * level + level * 0.6);
      else on = u < fill ? 0.38 : 0.1;
      g.fillStyle = rgba(M, on);
      g.beginPath(); g.arc(ox, oy, rOut, a0, a1); g.arc(ox, oy, rIn, a1, a0, true); g.closePath(); g.fill();
    }
    // bant ucu: hareketli imleç
    const head = B0 + SPAN * (mode === 'thinking' ? Math.min(1, fill) : 0.72);
    arc(R * 0.96, head - 0.03, head + 0.03, 4, rgba(A, 0.95));

    // 5) vurgu yayları (turuncu/sarı aksan) — düşünürken iki yay birbirini kovalar
    const acA = -phase * 0.7;
    arc(R * 0.74, acA, acA + 0.9, 3, rgba(A, 0.85));
    arc(R * 0.74, acA + Math.PI, acA + Math.PI + 0.35 + 0.6 * E, 2, rgba(A, 0.5 + 0.4 * E));
    for (const [a0, len] of midSegs) arc(R * 0.69, a0 - phase * 0.45, a0 - phase * 0.45 + len, 1.2, rgba(M, 0.35));

    // 6) iç çift halka + üstte sırayla yanan noktalar
    arc(R * 0.64, 0, TAU, 2, rgba(M, 0.7)); arc(R * 0.6, 0, TAU, 1, rgba(M, 0.35));
    const dots = 5, seq = Math.floor(t * (mode === 'thinking' ? 8 : mode === 'listening' ? 4 : 1.2)) % (dots + 2);
    for (let i = 0; i < dots; i++) {
      const a = -Math.PI / 2 + (i - (dots - 1) / 2) * 0.16, lit = E > 0.05 ? (i === seq || i === seq - 1) : true;
      g.fillStyle = rgba(lit ? [255, 214, 80] : M, lit ? 0.95 : 0.3);
      g.beginPath(); g.arc(ox + Math.cos(a) * R * 0.86, oy + Math.sin(a) * R * 0.86, 2.6, 0, TAU); g.fill();
    }

    // 7) tarama ışını (düşünürken güçlü, dinlerken hafif)
    if (E > 0.05 && g.createConicGradient) {
      const sweepA = t * (mode === 'thinking' ? 3.2 : 1.6);
      const cg = g.createConicGradient(sweepA, ox, oy);
      cg.addColorStop(0, rgba(M, 0.28 * E)); cg.addColorStop(0.12, rgba(M, 0)); cg.addColorStop(1, rgba(M, 0));
      g.save(); g.shadowBlur = 0; g.fillStyle = cg; g.beginPath(); g.arc(ox, oy, R * 0.98, 0, TAU); g.moveTo(ox + R * 0.6, oy); g.arc(ox, oy, R * 0.6, 0, TAU, true); g.fill('evenodd'); g.restore();
    }

    // 8) yörüngedeki veri parçacıkları
    for (const p of particles) {
      p.a += dt * p.s * (0.15 + cur.spin * 0.6);
      const r = R * p.r, x = ox + Math.cos(p.a) * r, y = oy + Math.sin(p.a) * r;
      const al = (0.15 + 0.6 * E) * (0.4 + p.z * 0.6);
      if (al < 0.05) continue;
      g.fillStyle = rgba(p.z > 0.8 ? A : M, al); g.fillRect(x - 1, y - 1, 2 + p.z * 1.5, 2 + p.z * 1.5);
    }

    // 9) konuşurken dalga halkası
    if (mode === 'speaking' && an) {
      g.strokeStyle = rgba(A, 0.85); g.lineWidth = 1.5; g.beginPath();
      for (let i = 0; i <= 120; i++) {
        const a = i / 120 * TAU, v = freq[(i % 60) + 2] / 255, r = R * 0.62 + v * R * 0.14;
        const x = ox + Math.cos(a - Math.PI / 2) * r, y = oy + Math.sin(a - Math.PI / 2) * r;
        i ? g.lineTo(x, y) : g.moveTo(x, y);
      }
      g.stroke();
    }
    g.restore();

    // --- merkez: koyu disk, nişangâh, J.A.R.V.I.S. -----------------------------------------------
    const core = g.createRadialGradient(ox, oy, 0, ox, oy, R * 0.58);
    core.addColorStop(0, 'rgba(6,22,32,.96)'); core.addColorStop(0.8, 'rgba(4,14,22,.92)'); core.addColorStop(1, rgba(M, 0.25));
    g.fillStyle = core; g.beginPath(); g.arc(ox, oy, R * 0.58, 0, TAU); g.fill();
    g.strokeStyle = rgba(M, 0.12); g.lineWidth = 1;
    for (let i = 1; i <= 3; i++) { g.beginPath(); g.arc(ox, oy, R * 0.14 * i, 0, TAU); g.stroke(); }
    g.beginPath(); g.moveTo(ox - R * 0.5, oy); g.lineTo(ox + R * 0.5, oy); g.moveTo(ox, oy - R * 0.5); g.lineTo(ox, oy + R * 0.5); g.stroke();

    g.save();
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.font = `600 ${Math.round(R * 0.15)}px Rajdhani, "Orbitron", "Segoe UI", system-ui, sans-serif`;
    g.shadowColor = rgba(M, 0.95); g.shadowBlur = 16 + level * 20;
    g.fillStyle = 'rgba(235,248,255,.97)';
    spacedText('J.A.R.V.I.S.', ox, oy - R * 0.02, R * 0.012);
    g.shadowBlur = 6;
    g.font = `500 ${Math.max(9, Math.round(R * 0.055))}px ui-monospace, Menlo, monospace`;
    const flick = mode === 'thinking' ? 0.6 + 0.4 * Math.abs(Math.sin(t * 9)) : 0.9;
    g.fillStyle = rgba(M, flick);
    spacedText(S.label, ox, oy + R * 0.16, R * 0.012);
    g.restore();

    // --- halka çevresindeki HUD etiketleri (geniş ekranlarda) -------------------------------------
    if (W >= 720) {
      g.save(); g.font = '10px ui-monospace, Menlo, monospace'; g.textBaseline = 'middle';
      const clock = new Date().toLocaleTimeString('tr-TR');
      const notes = (typeof GRAPH !== 'undefined' && GRAPH.nodes) ? GRAPH.nodes.length : '—';
      const labels = [
        [-2.45, 'SES', 'tr-TR · GEMINI'], [-0.7, 'DURUM', S.label],
        [0.62, 'SAAT', clock], [2.5, 'İNDEKS', `${notes} NOT`],
      ];
      for (const [a, k1, v1] of labels) {
        const x0 = ox + Math.cos(a) * R * 1.22, y0 = oy + Math.sin(a) * R * 1.22;
        const right = Math.cos(a) > 0, x1 = x0 + (right ? 28 : -28), y1 = y0 + (Math.sin(a) > 0 ? 18 : -18), x2 = x1 + (right ? 70 : -70);
        g.strokeStyle = rgba(M, 0.45); g.lineWidth = 1;
        g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.lineTo(x2, y1); g.stroke();
        g.fillStyle = rgba(M, 0.85); g.beginPath(); g.arc(x0, y0, 2.2, 0, TAU); g.fill();
        g.textAlign = right ? 'left' : 'right';
        g.fillStyle = 'rgba(160,200,215,.65)'; g.fillText(k1, x2 + (right ? 6 : -6), y1 - 7);
        g.fillStyle = rgba(M, 0.95); g.fillText(v1, x2 + (right ? 6 : -6), y1 + 7);
      }
      g.restore();
    }

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  window.__hud = { setMode: m => { mode = STATES[m] ? m : 'idle'; } };   // test/demo için
})();
