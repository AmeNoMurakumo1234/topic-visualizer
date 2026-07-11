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
      if (n.parent && bySlug[n.parent]) bySlug[n.parent].children.push(n);
      else n.parent = null;
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

    /* --- archive explorer: the past stays visitable (nothing is ever lost, only
       resting). Adapters that support it get ghosts; others silently ignore. --- */
    core.showArchive = false;
    core.setArchive = async function (on) {
      core.showArchive = !!on;
      await core.load();
    };

    core.load = async function () {
      const raw = core.demo ? demoData(core.demo) : await adapter.load(core.showArchive);
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

    core.pruneSubtree = async function (n) {
      const { prune } = core.pruneSet(n);
      if (!core.demo) {
        await adapter.prune(prune.map(t => t.slug), core.actor);
        core.closePanel();
        await core.load();          // survivors were re-parented server-side; reload
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
      const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
      // AVENUES IN: primary parent + every extra road that leads here (the DAG)
      const avenue = (slug, note, extra) => {
        const p2 = core.bySlug[slug];
        return `<div class="avenue" data-slug="${slug}">
          <span class="ava${extra ? " x" : ""}">${extra ? "&#8618;" : "&#8593;"}</span>
          <span class="avt" title="${esc(slug)}">${p2 ? esc(short(p2.title)) : esc(slug)}</span>
          ${note ? `<span class="avn">${esc(note)}</span>` : ""}
          ${extra && adapter.attach && adapter.attachRemove && !core.demo
            ? `<button class="avx" data-slug="${slug}" title="detach this avenue">&times;</button>` : ""}
        </div>`;
      };
      const avenues = (n.parent ? avenue(n.parent, "", false) : "")
        + n.extraParents.map(x => avenue(x.slug, x.note, true)).join("");
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
        ${avenues ? `<div class="avhead">avenues in</div>${avenues}` : ""}
        ${adapter.attach && !core.demo ? `
        <div class="avadd">
          <input class="av-in" type="text" list="tvSlugsAv" placeholder="+ add avenue (parent slug)"/>
          <datalist id="tvSlugsAv">${core.nodes.filter(t => t.slug !== n.slug)
            .map(t => `<option value="${t.slug}">`).join("")}</datalist>
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
        .map(t => `<option value="${t.slug}">`).join("");
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
      dom.confirmBox.innerHTML = `<h3>Prune "${short(n.title).slice(0, 60)}"?</h3>
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
        await core.pruneSubtree(n);
      };
    };

    return core;
  }

  return { create, demoData, buildTree, short, weight, subtree };
})();
