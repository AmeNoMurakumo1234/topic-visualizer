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

  /* ---------- tiny utils ---------- */
  const short = t => String(t || "").replace(/^OPEN THREAD:\s*/i, "")
                                    .replace(/\s*\([^)]*\)\s*$/, "");
  const weight = t => (String(t || "").match(/\(([^)]*)\)\s*$/) || [])[1] || "";
  const subtree = n => { const out = [n]; n.children.forEach(c => out.push(...subtree(c))); return out; };

  /* ---------- demo mode: deterministic synthetic tree (seed 42) ----------
   * The scale-testing + screenshot tool. Same seed => the IDENTICAL tree in every
   * view. Includes a mega-fanout root (the "done with cars" prune case), two 12-deep
   * chains, organic preferential growth, ~10% critical, ~22% discussed. */
  function demoData(count) {
    let s = 42 >>> 0;
    const rnd = () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296;
    const pick = a => a[Math.floor(rnd() * a.length)];
    const AREAS = ["the sim", "prose registers", "the GUI", "fate anchors", "the ledger",
      "publishing", "artwork", "Lyra", "the world map", "combat", "the economy",
      "memory systems", "beat design", "the audit", "chapter assembly", "naming",
      "the schedule", "QA rituals", "the spine", "cars"];
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
    return out;
  }

  /* ---------- tree building + family hues ---------- */
  function buildTree(raw) {
    const bySlug = {}, nodes = raw.map(r => ({ ...r, children: [], parent: r.parentSlug }));
    nodes.forEach(n => { bySlug[n.slug] = n; });
    nodes.forEach(n => {
      if (n.parent && bySlug[n.parent]) bySlug[n.parent].children.push(n);
      else n.parent = null;
    });
    const roots = nodes.filter(n => !n.parent);
    // FAMILY HUES (color-by-group, the #1 graph-beauty move): golden-angle spacing per
    // root lineage; every view tints from n.hue. Rotation is relative to the base blue.
    roots.forEach((root, i) => {
      const hue = Math.round(i * 137.5) % 360;
      (function tint(n) { n.hue = hue; n.children.forEach(tint); })(root);
    });
    return { nodes, bySlug, roots };
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

  /* ---------- starfield + twinkle (celestial backdrop, painted once) ---------- */
  function paintStars(stage, canvas) {
    const r = stage.getBoundingClientRect();
    canvas.width = r.width; canvas.height = r.height;
    const ctx = canvas.getContext("2d");
    let s = 7 >>> 0; const rnd = () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296;
    for (let i = 0; i < 240; i++) {
      const x = rnd() * canvas.width, y = rnd() * canvas.height, big = rnd() > 0.94;
      ctx.globalAlpha = big ? 0.8 : 0.15 + rnd() * 0.35;
      ctx.fillStyle = big ? "#cfe0ff" : "#8fa5d8";
      ctx.beginPath(); ctx.arc(x, y, big ? 1.4 : 0.7, 0, 7); ctx.fill();
    }
    for (const t of stage.querySelectorAll(".twinkle")) t.remove();
    for (let i = 0; i < 14; i++) {
      const t = document.createElement("div");
      t.className = "twinkle";
      t.style.left = (rnd() * 100) + "%"; t.style.top = (rnd() * 100) + "%";
      t.style.animationDelay = (rnd() * 3.2) + "s";
      stage.appendChild(t);
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
      onChange: () => {},          // shell sets this: re-render the active renderer
      short, weight, subtree, demoData,
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
        const qToks = (core.searchQuery.toLowerCase().match(/[a-z0-9]{3,}/g) || []);
        core.matched = new Set(core.nodes
          .filter(n => scoreText(qToks, n.title + " " + n.body) > 0)
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
        const t = TopicsCore.buildTree(core.nodes.map(n => ({ ...n, parentSlug: n.parent })));
        core.nodes = t.nodes; core.bySlug = t.bySlug; core.roots = t.roots;
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

    core.load = async function () {
      const raw = core.demo ? demoData(core.demo) : await adapter.load();
      const t = buildTree(raw);
      core.nodes = t.nodes; core.bySlug = t.bySlug; core.roots = t.roots;
      core.selected = null;
      if (dom.statEl) dom.statEl.textContent =
        `${core.nodes.length} open topic(s), ${core.roots.length} root(s)` +
        (core.demo ? " (demo)" : "");
      core.onChange();
    };

    /* --- state actions (demo mode mutates locally; live mode hits the adapter) --- */
    core.setState = async function (n, state, note) {
      if (!core.demo) await adapter.setState(n.slug, state, core.actor, note || "");
      n.state = state;
      core.closePanel(); core.onChange();
    };
    core.pruneSubtree = async function (n) {
      const all = subtree(n);
      if (!core.demo) await adapter.prune(all.map(t => t.slug), core.actor);
      const gone = new Set(all.map(t => t.slug));
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
      core.selected = n;
      const kids = subtree(n).length - 1;
      const stateChip = n.state === "discussed" ? " | DISCUSSED"
                       : (n.critical ? " | CRITICAL" : "");
      dom.panel.className = "open";
      dom.panel.innerHTML = `<h2>${short(n.title)}</h2>
        <div class="meta">${weight(n.title) || "no time-weight"} | by ${n.author} | ${String(n.created).slice(0, 10)}
          | ${n.children.length} child(ren), ${kids} descendant(s)${stateChip}<br/>slug: ${n.slug}</div>
        <div class="body"></div>
        <span class="extra"></span>
        ${n.state === "discussed"
          ? `<button class="reopen">Reopen topic</button>`
          : `<button class="discuss">Mark discussed</button>`}
        <button class="prune">Prune this branch</button>
        <button class="close">Close</button>`;
      dom.panel.querySelector(".body").textContent =
        String(n.body || "").replace(/^parent:.*$/mi, "").replace(/^priority:.*$/mi, "").trim();
      dom.panel.querySelector(".close").onclick = () => { core.closePanel(); core.onChange(); };
      dom.panel.querySelector(".prune").onclick = () => core.confirmPrune(n);
      const re = dom.panel.querySelector(".reopen");
      if (re) re.onclick = () => core.setState(n, "open", "reopened via the topic tree");
      const di = dom.panel.querySelector(".discuss");
      if (di) di.onclick = () => core.setState(n, "discussed", "discussed - marked via the topic tree");
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

    /* --- prune-with-consequence (descendant count, honest reversibility) --- */
    core.confirmPrune = function (n) {
      const all = subtree(n);
      dom.confirmBox.innerHTML = `<h3>Prune "${short(n.title).slice(0, 60)}"?</h3>
        <p>This prunes <b>${all.length} topic(s)</b> (this node + ${all.length - 1} descendant(s)).
        ${core.demo ? "Demo mode: local only." : "Reversible: a pruned topic can be reopened from the store."}</p>
        <button class="go">Prune ${all.length}</button>
        <button class="no">Cancel</button>`;
      dom.confirmModal.className = "open";
      dom.confirmBox.querySelector(".no").onclick = () => { dom.confirmModal.className = ""; };
      dom.confirmBox.querySelector(".go").onclick = async () => {
        dom.confirmModal.className = "";
        await core.pruneSubtree(n);
      };
    };

    return core;
  }

  return { create, demoData, buildTree, short, weight, subtree };
})();
