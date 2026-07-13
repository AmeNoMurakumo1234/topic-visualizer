/* topics-core.js - the shared heart of the Topic Visualizer (storage-blind).
 * CANONICAL SOURCE: the topic-visualizer plugin repo (web/topics-core.js).
 * Other installations (e.g. the birthplace message board) VENDOR this file verbatim;
 * fix bugs here first, then re-copy. The adapter law: this module never knows the
 * storage - it talks to an injected adapter { name, load, setState, prune, }.
 *
 * raw topic shape (adapter contract):
 *   { slug, title, body, author, created, parentSlug|null,
 *     state: "open"|"discussed", critical: bool }
 */
window.TopicsCore = (function () {
  "use strict";

  /* Motion gate: idle every PERPETUAL animation (ambient twinkles, the meteor, the
   * beacon pulse, the SMIL node pulses) when the viewer asked for reduced motion OR an
   * automation/headless browser is driving (navigator.webdriver). A page that never
   * stops animating never reaches a stable frame - which is exactly what hangs
   * screenshot capture (seen on two machines). So a bot gets a still, capturable render
   * and motion-sensitive users get calm. Pure browser signals - no env vars, works on
   * any machine. */
  const REDUCED = (() => {
    try {
      // ?still / ?static: a deterministic, tool-agnostic lever - append it to freeze the
      // page for a clean screenshot no matter what your capture tool signals.
      const q = new URLSearchParams(location.search);
      if (q.has("still") || q.has("static")) return true;
      return (typeof matchMedia === "function"
              && matchMedia("(prefers-reduced-motion: reduce)").matches)
             || !!(navigator && navigator.webdriver);
    } catch (e) { return false; }
  })();
  try { if (REDUCED) document.documentElement.classList.add("reduced-motion"); } catch (e) {}

  /* ---------- tiny utils ---------- */
  // esc: the ONE HTML/attribute escape. Topic titles, bodies, and notes are
  // AI-authored text from arbitrary conversations - every innerHTML
  // interpolation in core AND the renderers must route through this (XSS
  // audit 2026-07-11: six raw sinks shipped before this existed).
  const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                            .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const short = t => String(t || "").replace(/^OPEN THREAD:\s*/i, "")
                                    .replace(/\s*\([^)]*\)\s*$/, "");
  const weight = t => (String(t || "").match(/\(([^)]*)\)\s*$/) || [])[1] || "";
  const subtree = n => { const out = [n]; n.children.forEach(c => out.push(...subtree(c))); return out; };

  /* ---------- demo mode: deterministic synthetic tree (seed 42) ----------
   * The scale-testing + screenshot tool. Same seed => the IDENTICAL tree in every
   * view. Includes a mega-fanout root (the big-branch prune case), two 12-deep chains,
   * organic preferential growth, ~10% critical, ~22% discussed. */
  function demoData(count) {
    let s = 42 >>> 0;
    const rnd = () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296;
    const pick = a => a[Math.floor(rnd() * a.length)];
    const AREAS = ["auth", "the API", "onboarding", "billing", "the dashboard", "search",
      "notifications", "the data model", "caching", "the CLI", "permissions", "logging",
      "the mobile app", "analytics", "deploys", "the docs", "rate limiting", "the queue",
      "settings", "the changelog"];
    const ASPECTS = ["pacing", "curation", "token cost", "visual design", "calibration",
      "drift", "coverage", "tooling", "doctrine", "automation", "metrics", "workflow",
      "onboarding", "pruning", "search", "export", "grounding", "voice", "continuity", "scale"];
    const FORMS = [t => `should ${t} fan out or stay flat?`, t => `what does ${t} cost at scale?`,
      t => `who owns ${t}?`, t => `is ${t} a stage or an inspector?`,
      t => `when does ${t} graduate to canon?`, t => `does ${t} need its own instrument?`,
      t => `${t}: build now or trigger later?`, t => `how do we measure ${t}?`];
    const WEIGHTS = ["~10 min", "~20 min", "~30 min", "~1 hour", "errand", "deep dive"];
    const out = [];
    const mk = (parentSlug) => {
      const area = pick(AREAS), q = pick(FORMS)(pick(ASPECTS));
      const critical = rnd() < 0.10, state = (!critical && rnd() < 0.22) ? "discussed" : "open";
      out.push({ slug: `demo-${out.length}`,
        title: `OPEN THREAD: ${area}: ${q} (${pick(WEIGHTS)})`,
        body: `Synthetic stress-test topic (demo mode, not stored).${critical ? "\npriority: critical" : ""}\n\nTopic space: ${area}.\nTHE QUESTION: ${q}`,
        author: "demo", created: "2026-07-11", parentSlug, state, critical });
      return out[out.length - 1];
    };
    const rootCount = 8 + Math.floor(rnd() * 6), roots = [];
    for (let i = 0; i < rootCount; i++) roots.push(mk(null));
    for (let i = 0; i < 35 && out.length < count; i++) mk(roots[0].slug);
    for (let c = 1; c <= 2; c++) {
      let p = roots[c];
      for (let d = 0; d < 12 && out.length < count; d++) p = mk(p.slug);
    }
    while (out.length < count) mk(out[Math.floor(rnd() * out.length)].slug);
    // ~3% multi-parent cross-links (rediscovered-via-another-avenue), so the DAG
    // is visible at demo scale; buildTree drops any accidental self/dup edges
    for (const t of out) {
      if (rnd() < 0.03 && t.parentSlug) {
        const other = out[Math.floor(rnd() * out.length)];
        if (other.slug !== t.slug && other.slug !== t.parentSlug) {
          t.extraParents = [{ slug: other.slug, note: "rediscovered via another avenue (demo)" }];
        }
      }
    }
    return out;
  }

  /* ---------- tree building + family hues ---------- */
  function buildTree(raw) {
    const bySlug = {}, nodes = raw.map(r => ({ ...r, children: [], parent: r.parentSlug,
                                               extraParents: r.extraParents || [] }));
    nodes.forEach(n => { bySlug[n.slug] = n; });
    nodes.forEach(n => {
      if (!n.parent || !bySlug[n.parent]) { n.parent = null; return; }
      // cycle cut: walking up from the would-be parent must never reach n -
      // a cyclic store (hostile adapter, corrupted db) used to hang every view
      let cur = bySlug[n.parent], hops = 0, cyclic = false;
      while (cur && hops++ < nodes.length) {
        if (cur.slug === n.slug) { cyclic = true; break; }
        cur = cur.parent ? bySlug[cur.parent] : null;
      }
      if (cyclic) { n.parent = null; return; }
      bySlug[n.parent].children.push(n);
    });
    nodes.forEach(n => {
      // extra avenues (multi-parent DAG): keep only edges whose parent is loaded
      n.extraParents = n.extraParents.filter(x => bySlug[x.slug] && x.slug !== n.slug);
    });
    const roots = nodes.filter(n => !n.parent);
    // FAMILY HUES (color-by-group, the #1 graph-beauty move): golden-angle spacing per
    // root lineage; every view tints from n.hue. Rotation is relative to the base blue.
    roots.forEach((root, i) => {
      const hue = Math.round(i * 137.5) % 360;
      (function tint(n) { n.hue = hue; n.children.forEach(tint); })(root);
    });
    // cross-links for the renderers: one flat list of {from(child), to(parent), note}
    const xlinks = [];
    nodes.forEach(n => n.extraParents.forEach(x =>
      xlinks.push({ from: n, to: bySlug[x.slug], note: x.note })));
    return { nodes, bySlug, roots, xlinks };
  }

  /* ---------- semantic zoom helpers ----------
   * THE CONTRACT: any label shown is READABLE (constant ~12px screen size) or absent.
   * Inline styles only - stylesheets override SVG presentation attributes (a bug we
   * shipped once; see the plugin PORTING.md behavioral contract). */
  const labelBudget = scale => scale >= 0.9 ? Infinity : scale >= 0.55 ? 40 : 16;
  function labelAllowedSet(list, scale) {
    const budget = labelBudget(scale);
    if (budget === Infinity) return null;   // null = all allowed
    return new Set(list.slice().sort((a, b) => (b.pri || 0) - (a.pri || 0))
                        .slice(0, budget).map(n => n.slug));
  }
  function styleLabel(el, scale, opts) {
    const base = (opts && opts.tiny) ? 10.5 : 12;
    el.style.fontSize = (base / scale) + "px";
    el.style.strokeWidth = (3.5 / scale) + "px";
    el.style.fontWeight = scale < 0.55 ? "600" : "";
  }

  /* ---------- deep-space backdrop (painted ONCE per resize, deterministic) ----------
   * Layers, faintest first: ridged-noise NEBULA filaments along a galactic band ->
   * a distant SPIRAL GALAXY -> a banded RINGED PLANET (rings occlude correctly) ->
   * temperature-varied STARFIELD w/ glints -> edge VIGNETTE. A rare CSS meteor and
   * the twinkles are the only motion. Everything deliberately mostly-transparent:
   * the sky must never compete with the data. */
  function paintStars(stage, canvas) {
    const r = stage.getBoundingClientRect();
    const w = canvas.width = r.width, h = canvas.height = r.height;
    if (!w || !h) return;
    const ctx = canvas.getContext("2d");
    let s = 7 >>> 0; const rnd = () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296;
    const diag = Math.hypot(w, h);

    /* --- nebula: multi-octave RIDGED value noise, masked to a diagonal band.
       Painted on a small offscreen canvas and scaled up (the smoothing IS the
       softness). Ridge = 1-|2n-1| turns blobby noise into filaments. --- */
    (function nebula() {
      const NW = 190, NH = Math.max(60, Math.round(190 * h / w));
      const octs = [[7, 5, 0.42], [14, 9, 0.3], [28, 17, 0.18], [56, 33, 0.10]]
        .map(([gw, gh, amp]) => {
          const g = new Float32Array((gw + 1) * (gh + 1));
          for (let i = 0; i < g.length; i++) g[i] = rnd();
          return { gw, gh, amp, g };
        });
      const sample = (o, u, v) => {
        const gx = u * o.gw, gy = v * o.gh, x0 = Math.floor(gx), y0 = Math.floor(gy);
        const fx = gx - x0, fy = gy - y0, W = o.gw + 1;
        const a = o.g[y0 * W + x0], b = o.g[y0 * W + x0 + 1],
              c = o.g[(y0 + 1) * W + x0], d = o.g[(y0 + 1) * W + x0 + 1];
        const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
        return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
      };
      const off = document.createElement("canvas");
      off.width = NW; off.height = NH;
      const octx = off.getContext("2d");
      const img = octx.createImageData(NW, NH);
      // band: from lower-left to upper-right (same diagonal the old art used)
      const bx0 = 0.05, by0 = 0.9, bx1 = 0.95, by1 = 0.1;
      const bdx = bx1 - bx0, bdy = by1 - by0, blen2 = bdx * bdx + bdy * bdy;
      const h2rgb = (hue, sat, li) => {
        const a2 = sat * Math.min(li, 1 - li);
        const f = k => { const kk = (k + hue / 30) % 12;
          return li - a2 * Math.max(-1, Math.min(kk - 3, Math.min(9 - kk, 1))); };
        return [f(0) * 255, f(8) * 255, f(4) * 255];
      };
      for (let y = 0; y < NH; y++) {
        for (let x = 0; x < NW; x++) {
          const u = x / NW, v = y / NH;
          // base fbm + ridged detail = cloud with filament veins
          let n = octs[0].amp * sample(octs[0], u, v)
                + octs[1].amp * sample(octs[1], u, v);
          let ridge = 0;
          for (const o of [octs[2], octs[3]]) {
            const rv = sample(o, u, v);
            ridge += o.amp * (1 - Math.abs(2 * rv - 1));
          }
          n = n + ridge * 1.4;                       // veins glow brighter
          // distance to the band spine (0 at spine, 1 at edge)
          const tproj = Math.max(0, Math.min(1,
            ((u - bx0) * bdx + (v - by0) * bdy) / blen2));
          const px2 = bx0 + tproj * bdx, py2 = by0 + tproj * bdy;
          const dist = Math.hypot(u - px2, (v - py2) * (h / w)) / 0.34;
          const mask = Math.max(0, 1 - dist * dist);
          const val = Math.pow(Math.max(0, n - 0.55), 1.6) * mask;
          if (val <= 0.002) continue;
          // hue drifts indigo -> violet along the band, teal at the far end
          const hue = tproj > 0.8 ? 190 : 232 + 55 * sample(octs[1], v, u);
          const [rr, gg, bb] = h2rgb(hue, 0.7, 0.62);
          const i4 = (y * NW + x) * 4;
          img.data[i4] = rr; img.data[i4 + 1] = gg; img.data[i4 + 2] = bb;
          img.data[i4 + 3] = Math.min(255, val * 430);
        }
      }
      octx.putImageData(img, 0, 0);
      ctx.globalCompositeOperation = "screen";
      ctx.globalAlpha = 0.5;
      ctx.drawImage(off, 0, 0, w, h);
      ctx.globalAlpha = 1;
      // a soft bright heart where the band peaks
      const core = ctx.createRadialGradient(w * 0.55, h * 0.42, 0, w * 0.55, h * 0.42, diag * 0.07);
      core.addColorStop(0, "hsla(228, 75%, 70%, 0.07)");
      core.addColorStop(1, "hsla(228, 75%, 70%, 0)");
      ctx.fillStyle = core;
      ctx.beginPath(); ctx.arc(w * 0.55, h * 0.42, diag * 0.07, 0, 7); ctx.fill();
    })();

    /* --- a distant spiral galaxy, small and tilted (upper right) --- */
    (function galaxy() {
      const gx = w * 0.86, gy = h * 0.16, size = Math.min(w, h) * 0.055;
      ctx.save();
      ctx.translate(gx, gy); ctx.rotate(0.5); ctx.scale(1, 0.42);
      const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, size * 2.4);
      glow.addColorStop(0, "rgba(210, 220, 255, 0.10)");
      glow.addColorStop(0.4, "rgba(160, 175, 240, 0.05)");
      glow.addColorStop(1, "rgba(160, 175, 240, 0)");
      ctx.fillStyle = glow;
      ctx.beginPath(); ctx.arc(0, 0, size * 2.4, 0, 7); ctx.fill();
      ctx.fillStyle = "#dfe7ff";
      for (let arm = 0; arm < 2; arm++) {
        for (let i = 0; i < 90; i++) {
          const tt = i / 90, ang = arm * Math.PI + tt * 3.6,
                rad = size * 0.25 + tt * size * 2.1 + (rnd() - 0.5) * size * 0.3;
          ctx.globalAlpha = (1 - tt) * 0.35 * (0.4 + rnd() * 0.6);
          ctx.fillRect(Math.cos(ang) * rad, Math.sin(ang) * rad, 1, 1);
        }
      }
      ctx.globalAlpha = 0.5;
      ctx.beginPath(); ctx.arc(0, 0, size * 0.22, 0, 7);
      ctx.fillStyle = "#f2ecdc"; ctx.fill();
      ctx.restore();
      ctx.globalAlpha = 1;
    })();

    /* --- the ringed planet (lower-left): banded body, rings occluding correctly
       (far arc BEHIND the body, near arc in front), ring shadow on the body --- */
    (function planet() {
      ctx.globalCompositeOperation = "source-over";
      const px = w * 0.06, py = h * 1.04, pr = Math.min(w, h) * 0.34, tilt = -0.42;
      const ring = (front) => {
        ctx.save();
        ctx.translate(px, py); ctx.rotate(tilt);
        for (const [rx, a] of [[1.55, 0.17], [1.78, 0.10]]) {
          ctx.strokeStyle = `rgba(170, 195, 250, ${front ? a : a * 0.55})`;
          ctx.lineWidth = pr * 0.045;
          ctx.beginPath();
          // far half sweeps over the top; near half sweeps under the bottom
          ctx.ellipse(0, 0, pr * rx, pr * rx * 0.24, 0,
                      front ? 0 : Math.PI, front ? Math.PI : 2 * Math.PI);
          ctx.stroke();
        }
        ctx.restore();
      };
      // atmosphere halo, then the far ring arc, then the body over it
      const halo = ctx.createRadialGradient(px, py, pr * 0.92, px, py, pr * 1.25);
      halo.addColorStop(0, "rgba(120, 160, 255, 0.10)");
      halo.addColorStop(1, "rgba(120, 160, 255, 0)");
      ctx.fillStyle = halo;
      ctx.beginPath(); ctx.arc(px, py, pr * 1.25, 0, 7); ctx.fill();
      ring(false);
      const body = ctx.createRadialGradient(
        px + pr * 0.55, py - pr * 0.65, pr * 0.1, px, py, pr);
      body.addColorStop(0, "rgba(150, 180, 235, 0.42)");
      body.addColorStop(0.35, "rgba(70, 95, 160, 0.38)");
      body.addColorStop(0.75, "rgba(22, 30, 58, 0.72)");
      body.addColorStop(1, "rgba(8, 11, 24, 0.92)");
      ctx.fillStyle = body;
      ctx.beginPath(); ctx.arc(px, py, pr, 0, 7); ctx.fill();
      // latitudinal cloud bands + the ring's shadow, clipped to the disc
      ctx.save();
      ctx.beginPath(); ctx.arc(px, py, pr, 0, 7); ctx.clip();
      ctx.translate(px, py); ctx.rotate(tilt * 0.55);
      for (let i = 0; i < 6; i++) {
        const by2 = -pr * 0.75 + i * pr * 0.3 + (rnd() - 0.5) * pr * 0.06;
        ctx.fillStyle = `rgba(${i % 2 ? "150, 180, 235" : "10, 14, 30"}, ${0.05 + rnd() * 0.05})`;
        ctx.fillRect(-pr, by2, pr * 2, pr * (0.1 + rnd() * 0.1));
      }
      ctx.rotate(-tilt * 0.55 + tilt);
      ctx.strokeStyle = "rgba(4, 6, 14, 0.5)";      // ring shadow
      ctx.lineWidth = pr * 0.09;
      ctx.beginPath(); ctx.ellipse(0, pr * 0.12, pr * 1.5, pr * 0.36, 0, 0, 7); ctx.stroke();
      ctx.restore();
      ring(true);
    })();

    /* --- starfield: temperature-varied, denser inside the band --- */
    const TINTS = ["#cfe0ff", "#cfe0ff", "#e8eeff", "#ffe9c9", "#c9d4ff", "#ffd9d0"];
    for (let i = 0; i < 320; i++) {
      const x = rnd() * w, y = rnd() * h, roll = rnd();
      const big = roll > 0.955, mid = roll > 0.85;
      ctx.globalAlpha = big ? 0.9 : mid ? 0.55 : 0.12 + rnd() * 0.3;
      ctx.fillStyle = TINTS[Math.floor(rnd() * TINTS.length)];
      ctx.beginPath();
      ctx.arc(x, y, big ? 1.5 : mid ? 1.0 : 0.6, 0, 7); ctx.fill();
      if (big) {                                       // cross glint
        ctx.globalAlpha = 0.35;
        ctx.fillRect(x - 4.5, y - 0.4, 9, 0.8);
        ctx.fillRect(x - 0.4, y - 4.5, 0.8, 9);
      }
    }
    ctx.globalAlpha = 1;

    /* --- vignette: pull the eye toward the center where the data lives --- */
    const vin = ctx.createRadialGradient(w / 2, h / 2, diag * 0.32, w / 2, h / 2, diag * 0.62);
    vin.addColorStop(0, "rgba(0, 0, 0, 0)");
    vin.addColorStop(1, "rgba(2, 3, 8, 0.42)");
    ctx.fillStyle = vin;
    ctx.fillRect(0, 0, w, h);

    /* --- motion: twinkles + ONE rare meteor (CSS-animated, ~29s cycle) --- */
    for (const t of stage.querySelectorAll(".twinkle, .meteor")) t.remove();
    if (!REDUCED) {                                  // skip perpetual motion under reduced/automation
      for (let i = 0; i < 14; i++) {
        const t = document.createElement("div");
        t.className = "twinkle";
        t.style.left = (rnd() * 100) + "%"; t.style.top = (rnd() * 100) + "%";
        t.style.animationDelay = (rnd() * 3.2) + "s";
        stage.appendChild(t);
      }
      const m = document.createElement("div");
      m.className = "meteor";
      m.style.top = (8 + rnd() * 30) + "%";
      stage.appendChild(m);
    }
  }

  /* ---------- the core object ---------- */
  function create(adapter, dom, options) {
    // dom: { panel, confirmModal, confirmBox, statEl }
    const core = {
      adapter, dom,
      demo: options && options.demo ? Math.min(1500, options.demo) : 0,
      actor: (options && options.actor) || "human",
      nodes: [], bySlug: {}, roots: [],
      selected: null,
      reduced: REDUCED,            // renderers skip SMIL pulses when motion is gated off
      onChange: () => {},          // shell sets this: re-render the active renderer
      short, weight, subtree, demoData, esc,
      labelBudget, labelAllowedSet, styleLabel, paintStars,
    };

    /* --- search (the Seam spec): filters every view by ranked match. Server-side
       semantic ranking when the adapter offers it; client-side keyword scoring as the
       universal fallback (works on any adapter). --- */
    core.searchQuery = "";
    core.matched = null;                 // null = no active search; Set(slug) otherwise
    const scoreText = (qToks, text) => {
      const toks = (text.toLowerCase().match(/[a-z0-9]{3,}/g) || []);
      if (!toks.length || !qToks.length) return 0;
      const tf = {};
      for (const w of toks) tf[w] = (tf[w] || 0) + 1;
      let hit = 0;
      for (const q of qToks) hit += Math.sqrt(tf[q] || 0);
      return hit / Math.sqrt(toks.length + 8);
    };
    // FACET terms filter by state/beacon ("critical", "discussed"...) and combine
    // with free text; mirrors the server's _FACETS - keep the two in sync
    const FACETS = {
      critical: n => n.critical, beacon: n => n.critical,
      seedling: n => n.state === "seedling", open: n => n.state === "open",
      discussed: n => n.state === "discussed", pruned: n => n.state === "pruned",
      expired: n => n.state === "expired",
      archived: n => n.state === "pruned" || n.state === "expired",
    };
    core.setSearch = async function (q) {
      core.searchQuery = String(q || "").trim();
      if (!core.searchQuery) { core.matched = null; core.onChange(); return; }
      let ranked = null;
      if (!core.demo && adapter.search) {
        try { ranked = await adapter.search(core.searchQuery); } catch (e) { ranked = null; }
      }
      if (ranked) {
        core.matched = new Set(ranked.map(r => r.slug));
      } else {
        const words = core.searchQuery.toLowerCase().split(/\s+/);
        const facets = words.filter(w => FACETS[w]).map(w => FACETS[w]);
        const qToks = (words.filter(w => !FACETS[w]).join(" ")
                       .match(/[a-z0-9]{3,}/g) || []);
        core.matched = new Set(core.nodes
          .filter(n => facets.every(f => f(n)))
          .filter(n => !qToks.length || scoreText(qToks, n.title + " " + n.body) > 0)
          .map(n => n.slug));
      }
      core.onChange();
    };
    // renderers consult these two in one line each:
    core.searchDim = n => core.matched !== null && !core.matched.has(n.slug);
    core.labelForced = n => core.matched !== null && core.matched.has(n.slug);

    /* --- quick-add: the human's two-second door --- */
    core.quickAdd = async function (title, parentSlug) {
      if (!title.trim()) return;
      if (core.demo) {
        core.nodes.push({ slug: "demo-q" + core.nodes.length, title: title.trim(),
          body: "", author: "human", created: "", parentSlug: parentSlug || null,
          state: "open", critical: false, children: [], parent: parentSlug || null });
        const pos = {};
        core.nodes.forEach(o => { pos[o.slug] = { x: o.x, y: o.y, vx: o.vx, vy: o.vy }; });
        const t = TopicsCore.buildTree(core.nodes.map(n2 => ({ ...n2, parentSlug: n2.parent })));
        core.nodes = t.nodes; core.bySlug = t.bySlug; core.roots = t.roots;
        core.xlinks = t.xlinks;
        core.nodes.forEach(o => { if (pos[o.slug]) Object.assign(o, pos[o.slug]); });
        core.onChange(); return;
      }
      if (adapter.create) {
        await adapter.create([{ title: title.trim(), parent_slug: parentSlug || null,
                                state: "open", created_by: core.actor }]);
        await core.load();
      }
    };

    /* --- seam health strip (adapters without a health endpoint just hide it) --- */
    core.health = async function () {
      if (core.demo || !adapter.health) return null;
      try { return await adapter.health(); } catch (e) { return null; }
    };

    /* --- archive explorer: the past stays visitable (nothing is ever lost, only
       resting). Adapters that support it get ghosts; others silently ignore. --- */
    core.showArchive = false;
    core.setArchive = async function (on) {
      core.showArchive = !!on;
      await core.load();
    };

    core.load = async function () {
      let raw;
      try {
        raw = core.demo ? demoData(core.demo) : await adapter.load(core.showArchive);
      } catch (e) {
        if (dom.statEl) dom.statEl.textContent = "could not reach the topics store";
        core.onChange();
        return;
      }
      const t = buildTree(raw);
      core.nodes = t.nodes; core.bySlug = t.bySlug; core.roots = t.roots;
      core.xlinks = t.xlinks;
      core.selected = null;
      if (dom.statEl) {
        const archived = core.nodes.filter(
          n => n.state === "pruned" || n.state === "expired").length;
        dom.statEl.textContent =
          `${core.nodes.length - archived} open topic(s), ${core.roots.length} root(s)` +
          (archived ? ` + ${archived} archived` : "") + (core.demo ? " (demo)" : "");
      }
      core.onChange();
    };

    /* --- state actions (demo mode mutates locally; live mode hits the adapter) --- */
    core.setState = async function (n, state, note) {
      if (!core.demo) await adapter.setState(n.slug, state, core.actor, note || "");
      n.state = state;
      core.closePanel(); core.onChange();
    };
    /* --- survivor-aware prune set (the multi-parent law; MIRRORS the server's
       set_state prune logic - keep the two in sync): a descendant reachable via a
       live extra parent OUTSIDE the pruned set is SPARED, not pruned. --- */
    core.pruneSet = function (n) {
      const live = t => t.state === "seedling" || t.state === "open" || t.state === "discussed";
      const closure = start => {
        const out = [start], fr = [start];
        while (fr.length) {
          const c = fr.pop();
          for (const k of c.children) {
            if (live(k) && !out.includes(k)) { out.push(k); fr.push(k); }
          }
        }
        return out;
      };
      let set = closure(n);
      const spared = [];
      for (;;) {
        const inSet = new Set(set.map(t => t.slug));
        const t = set.find(t2 => t2 !== n && t2.extraParents.some(
          x => !inSet.has(x.slug) && core.bySlug[x.slug] && live(core.bySlug[x.slug])));
        if (!t) break;
        const keep = new Set(closure(t).map(q => q.slug));
        set = set.filter(q => !keep.has(q.slug));
        spared.push(t);
      }
      return { prune: set, spared };
    };

    core.pruneSubtree = async function (n, shownSlugs) {
      const { prune } = core.pruneSet(n);
      if (!core.demo) {
        const res = await adapter.prune(shownSlugs || prune.map(t => t.slug), core.actor);
        core.closePanel();
        await core.load();          // survivors were re-parented server-side; reload
        if (res && res.error) {     // e.g. "subtree changed since the confirm dialog"
          dom.confirmBox.innerHTML = `<h3>Prune refused</h3>
            <p>${esc(res.error)}</p><button class="no">OK</button>`;
          dom.confirmModal.className = "open";
          dom.confirmBox.querySelector(".no").onclick = () => {
            dom.confirmModal.className = "";
          };
        }
        return;
      }
      const gone = new Set(prune.map(t => t.slug));
      core.nodes = core.nodes.filter(t => !gone.has(t.slug));
      core.nodes.forEach(t => { t.children = t.children.filter(c => !gone.has(c.slug)); });
      core.roots = core.nodes.filter(t => !t.parent);
      if (dom.statEl) dom.statEl.textContent =
        `${core.nodes.length} open topic(s), ${core.roots.length} root(s)` +
        (core.demo ? " (demo)" : "");
      core.closePanel(); core.onChange();
    };

    /* --- shared detail panel; renderers may add extra buttons via hook --- */
    core.closePanel = function () {
      dom.panel.className = ""; core.selected = null;
    };
    core.select = function (n, extraButtons) {
      n = core.bySlug[n.slug] || n;   // re-resolve: renderer closures may hold
                                      // node objects replaced by core.load()
      core.selected = n;
      const kids = subtree(n).length - 1;
      const archived = n.state === "pruned" || n.state === "expired";
      const pill = archived ? `<span class="pill archived">${n.state} - archived</span>`
                 : n.state === "discussed" ? `<span class="pill done">discussed</span>`
                 : n.state === "seedling" ? `<span class="pill seed">seedling</span>`
                 : `<span class="pill open">open</span>`;
      const beacon = (n.critical && !archived)
        ? `<span class="pill beacon">critical</span>` : "";
      const w = weight(n.title);
      // AVENUES IN: primary parent + every extra road that leads here. AVENUES OUT:
      // primary children + every topic that lists THIS node as an extra parent -
      // a cross-link has two endpoints, and BOTH panels must tell its story.
      // TRIAGED (owner): each row shows the FAR node's state, lists sort by
      // importance (critical > open > seedling > discussed > archived; handled
      // rows dim), and long lists cap at 8 with a click-to-expand.
      const AV_CAP = 8;
      const farRank = t => !t ? 5
        : (t.state === "pruned" || t.state === "expired") ? 4
        : t.state === "discussed" ? 3
        : (t.critical ? 0 : t.state === "seedling" ? 2 : 1);
      const farPills = t => {
        if (!t) return "";
        const arch = t.state === "pruned" || t.state === "expired";
        return (t.critical && !arch ? `<span class="avpill crit">critical</span>` : "")
          + (t.state === "seedling" ? `<span class="avpill seed">seedling</span>` : "")
          + (t.state === "discussed" ? `<span class="avpill done">discussed</span>` : "")
          + (arch ? `<span class="avpill arch">${t.state}</span>` : "");
      };
      const avenue = (slug, note, extra, arrow, removable) => {
        const p2 = core.bySlug[slug];
        const handled = p2 && (p2.state === "discussed" || p2.state === "pruned"
                               || p2.state === "expired");
        const chips = farPills(p2);
        const x = removable && adapter.attach && adapter.attachRemove && !core.demo
          ? `<button class="avx" data-slug="${esc(slug)}" title="detach this avenue">&times;</button>` : "";
        return `<div class="avenue${handled ? " dimrow" : ""}" data-slug="${esc(slug)}">
          ${chips || x ? `<div class="avtop">${chips}${x}</div>` : ""}
          <div class="avmain">
            <span class="ava${extra ? " x" : ""}">${arrow}</span>
            <span class="avt" title="${esc(slug)}">${p2 ? esc(short(p2.title)) : esc(slug)}</span>
          </div>
          ${note ? `<div class="avn">${esc(note)}</div>` : ""}
        </div>`;
      };
      const expanded = !!core._avenuesExpandOnce;
      core._avenuesExpandOnce = false;
      const capList = (rows, renderRow) => {
        const shown = expanded ? rows : rows.slice(0, AV_CAP);
        return shown.map(renderRow).join("")
          + (rows.length > shown.length
             ? `<button class="avmore">show ${rows.length - shown.length} more
                (important first, handled last)</button>` : "")
          + (expanded && rows.length > AV_CAP
             ? `<button class="avmore avless">show less</button>` : "");
      };
      const inExtras = n.extraParents.slice()
        .sort((a, b) => farRank(core.bySlug[a.slug]) - farRank(core.bySlug[b.slug]));
      const avenuesIn = (n.parent ? avenue(n.parent, "", false, "&#8593;", false) : "")
        + capList(inExtras, x => avenue(x.slug, x.note, true, "&#8618;", true));
      const crossKids = core.nodes.filter(
        t => t !== n && t.extraParents.some(x => x.slug === n.slug));
      const outList = n.children.map(c => ({ slug: c.slug, note: "", extra: false }))
        .concat(crossKids.map(c => ({
          slug: c.slug,
          note: (c.extraParents.find(x => x.slug === n.slug) || {}).note || "",
          extra: true })))
        .sort((a, b) => farRank(core.bySlug[a.slug]) - farRank(core.bySlug[b.slug]));
      const avenuesOut = capList(outList,
        o => avenue(o.slug, o.note, o.extra, o.extra ? "&#8618;" : "&#8595;", false));
      dom.panel.className = "open";
      dom.panel.innerHTML = `
        <div class="phead">
          <h2>${esc(short(n.title))}</h2>
          <div class="pills">${pill}${beacon}${w ? `<span class="pill tw">${esc(w)}</span>` : ""}</div>
        </div>
        <div class="meta">by <b>${esc(n.author)}</b> &middot; ${String(n.created).slice(0, 10)}
          &middot; ${n.children.length} child(ren), ${kids} descendant(s)
          <span class="slugline">${esc(n.slug)}</span></div>
        <div class="body"></div>
        ${avenuesIn ? `<div class="avhead">avenues in</div>${avenuesIn}` : ""}
        ${avenuesOut ? `<div class="avhead">avenues out</div>${avenuesOut}` : ""}
        ${adapter.attach && !core.demo ? `
        <div class="avadd">
          <input class="av-in" type="text" list="tvSlugsAv" placeholder="+ add avenue (parent slug)"/>
          <datalist id="tvSlugsAv">${core.nodes.filter(t => t.slug !== n.slug)
            .map(t => `<option value="${esc(t.slug)}">`).join("")}</datalist>
        </div>` : ""}
        <div class="pactions">
          <span class="extra"></span>
          ${(n.state !== "open" && n.state !== "seedling")
            ? `<button class="reopen primary">${archived ? "Resurrect" : "Reopen"} topic</button>`
            : `<button class="discuss">Mark discussed</button>`}
          ${adapter.edit && !core.demo ? `<button class="edit">Edit</button>` : ""}
          ${archived ? "" : `<button class="prune">Prune branch</button>`}
          <button class="close">Close</button>
        </div>`;
      dom.panel.querySelector(".body").textContent =
        String(n.body || "").replace(/^parent:.*$/gmi, "").replace(/^priority:.*$/gmi, "")
          .replace(/^stage:.*$/gmi, "").trim();
      dom.panel.querySelector(".close").onclick = () => { core.closePanel(); core.onChange(); };
      const pr = dom.panel.querySelector(".prune");
      if (pr) pr.onclick = () => core.confirmPrune(n);
      const re = dom.panel.querySelector(".reopen");
      if (re) re.onclick = () => core.setState(n, "open",
        archived ? "resurrected from the archive" : "reopened via the topic tree");
      const di = dom.panel.querySelector(".discuss");
      if (di) di.onclick = () => core.setState(n, "discussed", "discussed - marked via the topic tree");
      const ed = dom.panel.querySelector(".edit");
      if (ed) ed.onclick = () => core.editPanel(n);
      // avenue title click = jump to that parent
      dom.panel.querySelectorAll(".avenue .avt").forEach(el => {
        el.onclick = () => {
          const p2 = core.bySlug[el.closest(".avenue").dataset.slug];
          if (p2) core.select(p2);
        };
      });
      // "+N more" expands the capped avenue lists in place; "show less" collapses
      // them again (also collapses on the next selection). The re-render must NOT
      // jump the scroll back to top.
      dom.panel.querySelectorAll(".avmore").forEach(el => {
        const collapsing = el.classList.contains("avless");
        el.onclick = () => {
          const st = dom.panel.scrollTop;
          core._avenuesExpandOnce = !collapsing;
          core.select(n, extraButtons);
          // restore INSTANTLY - scroll-behavior:smooth would animate the restore
          // from the top, which reads as a glitch (browser clamps to the new max)
          dom.panel.style.scrollBehavior = "auto";
          dom.panel.scrollTop = st;
          dom.panel.style.scrollBehavior = "";
        };
      });
      dom.panel.querySelectorAll(".avx").forEach(el => {
        el.onclick = async () => {
          await adapter.attach(n.slug, el.dataset.slug, "", core.actor, true);
          const slug = n.slug;
          await core.load();
          if (core.bySlug[slug]) core.select(core.bySlug[slug]);
        };
      });
      const avIn = dom.panel.querySelector(".av-in");
      if (avIn) avIn.onkeydown = async e => {
        if (e.key !== "Enter" || !avIn.value.trim()) return;
        const res = await adapter.attach(n.slug, avIn.value.trim(),
                                         "added via the topic tree", core.actor, false);
        if (res && res.error) { avIn.value = ""; avIn.placeholder = res.error; return; }
        const slug = n.slug;
        await core.load();
        if (core.bySlug[slug]) core.select(core.bySlug[slug]);
      };
      if (extraButtons) {
        const mount = dom.panel.querySelector(".extra");
        for (const b of extraButtons) {
          const btn = document.createElement("button");
          btn.textContent = b.label; btn.className = b.className || "";
          btn.onclick = b.onClick; mount.appendChild(btn);
        }
      }
      core.onChange();
    };

    /* --- panel edit: title / body / re-parent / beacon, saved in one act. Only
       offered when the adapter can edit (capability detection - the board cannot). --- */
    core.editPanel = function (n) {
      const options = core.nodes
        .filter(t => t.slug !== n.slug)
        .map(t => `<option value="${esc(t.slug)}">`).join("");
      dom.panel.innerHTML = `<h2>Edit topic</h2>
        <div class="editform">
          <label>Title</label><input class="e-title" type="text" maxlength="200"/>
          <label>Body</label><textarea class="e-body" rows="6"></textarea>
          <label>Parent slug (blank = root)</label>
          <input class="e-parent" type="text" list="tvSlugs" placeholder="root"/>
          <datalist id="tvSlugs">${options}</datalist>
          <label class="e-crit-row"><input class="e-crit" type="checkbox"/>
            critical beacon (rare - the loud voice you must not waste)</label>
          <div class="e-err"></div>
          <button class="save">Save</button>
          <button class="back">Cancel</button>
        </div>`;
      dom.panel.querySelector(".e-title").value = n.title;
      dom.panel.querySelector(".e-body").value = n.body || "";
      dom.panel.querySelector(".e-parent").value = n.parent || "";
      dom.panel.querySelector(".e-crit").checked = !!n.critical;
      dom.panel.querySelector(".back").onclick = () => core.select(n);
      dom.panel.querySelector(".save").onclick = async () => {
        const parentSlug = dom.panel.querySelector(".e-parent").value.trim();
        const res = await adapter.edit(n.slug, {
          title: dom.panel.querySelector(".e-title").value.trim() || n.title,
          body: dom.panel.querySelector(".e-body").value,
          parent_slug: parentSlug,               // "" re-roots; server cycle-guards
          critical: dom.panel.querySelector(".e-crit").checked,
        }, core.actor);
        if (res && res.error) {
          dom.panel.querySelector(".e-err").textContent = res.error;
          return;
        }
        const slug = n.slug;
        await core.load();
        const again = core.bySlug[slug];
        if (again) core.select(again);
      };
    };

    /* --- prune-with-consequence (descendant count, honest reversibility) --- */
    core.confirmPrune = function (n) {
      const { prune: all, spared } = core.pruneSet(n);
      const shown = all.map(t => t.slug);        // what the human is confirming
      dom.confirmBox.innerHTML = `<h3>Prune "${esc(short(n.title).slice(0, 60))}"?</h3>
        <p>This prunes <b>${all.length} topic(s)</b> (this node + ${all.length - 1} descendant(s)).
        ${spared.length ? `<br/><b>${spared.length} topic(s) SURVIVE</b> - they are also
          reachable via another avenue, which becomes their home.` : ""}
        ${core.demo ? "Demo mode: local only." : "Reversible: a pruned topic can be reopened from the store."}</p>
        <button class="go">Prune ${all.length}</button>
        <button class="no">Cancel</button>`;
      dom.confirmModal.className = "open";
      dom.confirmBox.querySelector(".no").onclick = () => { dom.confirmModal.className = ""; };
      dom.confirmBox.querySelector(".go").onclick = async () => {
        dom.confirmModal.className = "";
        await core.pruneSubtree(n, shown);
      };
    };

    return core;
  }

  return { create, demoData, buildTree, short, weight, subtree };
})();
