/* render-starchart.js - view C: radial focus+context (after Lamping/Rao/Pirolli, CHI '95).
 * CANONICAL SOURCE: the topic-visualizer plugin repo. Vendored copies: do not edit in place.
 * The focus is the sun; children orbit on compressed rings; deeper content collapses
 * into "+N deeper" halos. Double-click or the panel's Focus button re-centers with
 * animation; breadcrumbs walk home. Storage-blind. */
window.TopicsRenderers = window.TopicsRenderers || {};
window.TopicsRenderers.starchart = (function () {
  "use strict";
  const RINGS = [0, 190, 330, 430, 500];         // hyperbolic-flavored compression
  const MAXDEPTH = RINGS.length - 1;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const DEFS = `
    <defs>
      <radialGradient id="tvStarGrad">
        <stop offset="0%" stop-color="#eaf2ff"/><stop offset="35%" stop-color="#7fa7ff"/>
        <stop offset="75%" stop-color="#3a5bbf" stop-opacity="0.55"/>
        <stop offset="100%" stop-color="#3a5bbf" stop-opacity="0"/>
      </radialGradient>
      <radialGradient id="tvSunGrad">
        <stop offset="0%" stop-color="#fff6dd"/><stop offset="35%" stop-color="#ffcf6e"/>
        <stop offset="75%" stop-color="#c98a2e" stop-opacity="0.6"/>
        <stop offset="100%" stop-color="#c98a2e" stop-opacity="0"/>
      </radialGradient>
      <radialGradient id="tvFogGrad">
        <stop offset="0%" stop-color="#5b7fe0" stop-opacity="0.35"/>
        <stop offset="60%" stop-color="#4160b8" stop-opacity="0.12"/>
        <stop offset="100%" stop-color="#4160b8" stop-opacity="0"/>
      </radialGradient>
    </defs>`;

  let core, stage, view, orbitsG, fogG, edgesG, nodesG, crumbsEl;
  let focus = null, visible = [];
  let tx = 0, ty = 0, scale = 1, labelRaf = null, animId = null;

  function mount(container, coreRef) {
    core = coreRef; stage = container;
    stage.innerHTML = `<div class="tv-crumbs"></div>
      <svg>${DEFS}<g class="tv-view"><g class="tv-orbits"></g><g class="tv-fog"></g>
      <g class="tv-edges"></g><g class="tv-nodes"></g></g></svg>`;
    crumbsEl = stage.querySelector(".tv-crumbs");
    view = stage.querySelector(".tv-view");
    orbitsG = stage.querySelector(".tv-orbits");
    fogG = stage.querySelector(".tv-fog");
    edgesG = stage.querySelector(".tv-edges");
    nodesG = stage.querySelector(".tv-nodes");
    focus = null;
    const r = stage.getBoundingClientRect();
    tx = r.width / 2; ty = r.height / 2; scale = 1; apply();

    // pointer capture: move/up keep arriving even when the cursor leaves the
    // window (a plain mouseup listener loses the release -> stuck drag)
    stage.addEventListener("pointerdown", ev => {
      if (ev.button !== 0 || ev.target.closest(".node") || ev.target.closest(".tv-crumbs")) return;
      stage.classList.add("dragging");
      try { stage.setPointerCapture(ev.pointerId); } catch (e) { /* capture is
        best-effort: a failed capture must never kill the drag itself */ }
      const sx = ev.clientX - tx, sy = ev.clientY - ty;
      const mv = e => { tx = e.clientX - sx; ty = e.clientY - sy; apply(); };
      const up = () => { stage.classList.remove("dragging");
        stage.removeEventListener("pointermove", mv);
        stage.removeEventListener("pointerup", up);
        stage.removeEventListener("pointercancel", up); };
      stage.addEventListener("pointermove", mv);
      stage.addEventListener("pointerup", up);
      stage.addEventListener("pointercancel", up);
    });
    stage.addEventListener("wheel", ev => { ev.preventDefault();
      const rect = stage.getBoundingClientRect();
      const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      const next = Math.max(0.3, Math.min(3, scale * (ev.deltaY < 0 ? 1.12 : 0.9)));
      tx = mx - (mx - tx) * (next / scale); ty = my - (my - ty) * (next / scale);
      scale = next; apply(); }, { passive: false });
  }

  const apply = () => { if (view) { view.setAttribute("transform",
    `translate(${tx},${ty}) scale(${scale})`); scheduleLabels(); } };

  function visWeight(n, depthLeft) {
    if (depthLeft <= 0 || !n.children.length) return 1;
    return n.children.reduce((s, c) => s + visWeight(c, depthLeft - 1), 0);
  }

  function render() {
    if (!stage) return;
    if (focus && !core.bySlug[focus.slug]) focus = null;   // focus pruned away
    visible = [];
    const place = (n, depth, a0, a1) => {
      const mid = (a0 + a1) / 2, r = RINGS[Math.min(depth, MAXDEPTH)];
      const hidden = depth >= MAXDEPTH ? Math.max(0, core.subtree(n).length - 1) : 0;
      n.tgt = { x: r * Math.cos(mid), y: r * Math.sin(mid), depth, hidden };
      if (!n.cur) n.cur = { x: 0, y: 0 };
      visible.push(n);
      if (depth >= MAXDEPTH) return;
      const kids = n.children,
            total = kids.reduce((s, c) => s + visWeight(c, MAXDEPTH - depth - 1), 0) || 1;
      let a = a0;
      for (const c of kids) {
        const span = (a1 - a0) * visWeight(c, MAXDEPTH - depth - 1) / total;
        place(c, depth + 1, a, a + span); a += span;
      }
    };
    const level1 = focus ? focus.children : core.roots;
    if (focus) {
      focus.tgt = { x: 0, y: 0, depth: 0, hidden: 0 };
      if (!focus.cur) focus.cur = { x: 0, y: 0 };
      visible.push(focus);
    }
    const total = level1.reduce((s, c) => s + visWeight(c, MAXDEPTH - 1), 0) || 1;
    let a = -Math.PI / 2;
    for (const c of level1) {
      const span = 2 * Math.PI * visWeight(c, MAXDEPTH - 1) / total;
      place(c, 1, a, a + span); a += span;
    }
    crumbs(); draw(); animate();
  }

  function draw() {
    orbitsG.innerHTML = ""; fogG.innerHTML = ""; edgesG.innerHTML = ""; nodesG.innerHTML = "";
    for (let d = 1; d <= MAXDEPTH; d++) {
      const o = document.createElementNS(SVG_NS, "circle");
      o.setAttribute("class", "orbit"); o.setAttribute("r", RINGS[d]);
      orbitsG.appendChild(o);
    }
    const inView = new Set(visible.map(n => n.slug));
    for (const n of visible) {
      if (n.tgt.depth <= 1 && n.children.length) {
        const f = document.createElementNS(SVG_NS, "circle");
        f.setAttribute("class", "fog"); f.dataset.slug = n.slug;
        f.setAttribute("r", Math.min(260, 90 + core.subtree(n).length * 3));
        f.setAttribute("fill", "url(#tvFogGrad)");
        f.style.filter = `hue-rotate(${n.hue || 0}deg)`;
        fogG.appendChild(f);
      }
      if (n.parent && inView.has(n.parent)) {
        const e = document.createElementNS(SVG_NS, "path");
        e.setAttribute("class", "edge"); e.dataset.a = n.slug; e.dataset.b = n.parent;
        e.style.stroke = `hsl(${(222 + (n.hue || 0)) % 360}, 65%, 72%)`;
        edgesG.appendChild(e);
      }
      const g = document.createElementNS(SVG_NS, "g");
      const isFocus = focus === n, rootlike = !n.parent && !focus;
      g.setAttribute("class", "node" + (isFocus ? " focus" : "") +
        (rootlike ? " rootlike" : "") + (core.selected === n ? " selected" : "") +
        (n.state === "discussed" ? " discussed" : "") +
        (n.state === "seedling" ? " seedling" : "") +
        (n.state === "pruned" || n.state === "expired" ? " archived" : "") +
        (core.searchDim(n) ? " searchdim" : ""));
      g.dataset.slug = n.slug;
      const depth = n.tgt.depth,
            r = isFocus ? 46 : Math.max(10, 30 - depth * 6) + Math.min(10, n.children.length * 1.5);
      const leaf = !n.children.length && !isFocus;
      n.pri = (isFocus ? 10 : 0) + (rootlike || depth <= 1 ? 5 : 0) + (n.critical ? 4 : 0) +
              Math.min(4, Math.log2(core.subtree(n).length + 1)) +
              (n.state === "discussed" ? -2 : 0);
      const body = leaf
        ? `<path class="leafstar" transform="scale(${Math.max(9, r * 0.75) / 8})"
             style="fill: hsl(${(222 + (n.hue || 0)) % 360}, 80%, 88%)"
             d="M0,-8 L2.2,-2.2 L8,0 L2.2,2.2 L0,8 L-2.2,2.2 L-8,0 L-2.2,-2.2 Z"></path>`
        : `<circle class="core" r="${r}" ${(rootlike || isFocus)
             ? `style="fill: url(#tvSunGrad)"`
             : `style="filter: hue-rotate(${n.hue || 0}deg)"`}></circle>`;
      const beacon = (n.critical && n.state !== "discussed")
        ? `<circle class="beacon" r="${r + 6}">
             <animate attributeName="r" values="${r + 3};${r + 11};${r + 3}" dur="1.8s" repeatCount="indefinite"/>
             <animate attributeName="stroke-opacity" values="0.9;0.15;0.9" dur="1.8s" repeatCount="indefinite"/>
           </circle>` : "";
      const label = depth <= 2 || isFocus ? core.short(n.title) : "";
      const cut = depth <= 1 ? 46 : 30;
      g.innerHTML = `
        ${n.tgt.hidden ? `<circle class="halo" r="${r + 7}"></circle>` : ""}
        ${beacon}${body}
        ${label ? `<text class="label ${depth >= 2 ? "tiny" : ""}" y="${r + 12}" text-anchor="middle">${label.slice(0, cut)}${label.length > cut ? "..." : ""}</text>` : ""}
        ${n.tgt.hidden ? `<text class="more" y="${-r - 6}" text-anchor="middle">+${n.tgt.hidden} deeper</text>` : ""}`;
      const t = document.createElementNS(SVG_NS, "title");
      t.textContent = core.short(n.title); g.appendChild(t);
      g.addEventListener("click", ev => { ev.stopPropagation();
        core.select(n, [{ label: "Focus here", className: "focusbtn",
                          onClick: () => setFocus(n) }]); });
      g.addEventListener("dblclick", ev => { ev.stopPropagation(); setFocus(n); });
      nodesG.appendChild(g);
    }
    // cross-links (multi-parent DAG): extra avenues, drawn only when both ends
    // are on the chart - dashed and quieter than the radial tree edges
    for (const x of core.xlinks || []) {
      if (!inView.has(x.from.slug) || !inView.has(x.to.slug)) continue;
      const e = document.createElementNS(SVG_NS, "path");
      e.setAttribute("class", "edge xlink");
      e.dataset.a = x.from.slug; e.dataset.b = x.to.slug;
      edgesG.appendChild(e);
    }
    position(); scheduleLabels();
  }

  function position() {
    for (const g of nodesG.children) { const n = core.bySlug[g.dataset.slug];
      if (n && n.cur) g.setAttribute("transform", `translate(${n.cur.x},${n.cur.y})`); }
    for (const f of fogG.children) { const n = core.bySlug[f.dataset.slug];
      if (n && n.cur) { f.setAttribute("cx", n.cur.x); f.setAttribute("cy", n.cur.y); } }
    for (const e of edgesG.children) {
      const a = core.bySlug[e.dataset.a], b = core.bySlug[e.dataset.b];
      if (!a || !b || !a.cur || !b.cur) continue;
      const dx = b.cur.x - a.cur.x, dy = b.cur.y - a.cur.y;
      const mx = (a.cur.x + b.cur.x) / 2 + dy * 0.12, my = (a.cur.y + b.cur.y) / 2 - dx * 0.12;
      e.setAttribute("d", `M ${a.cur.x} ${a.cur.y} Q ${mx} ${my} ${b.cur.x} ${b.cur.y}`);
    }
  }

  function animate() {
    cancelAnimationFrame(animId);
    const step = () => {
      let moving = false;
      for (const n of visible) {
        const dx = n.tgt.x - n.cur.x, dy = n.tgt.y - n.cur.y;
        if (Math.abs(dx) + Math.abs(dy) > 0.5) { moving = true;
          n.cur.x += dx * 0.16; n.cur.y += dy * 0.16; }
        else { n.cur.x = n.tgt.x; n.cur.y = n.tgt.y; }
      }
      position();
      if (moving) animId = requestAnimationFrame(step);
    };
    animId = requestAnimationFrame(step);
  }

  function setFocus(n) { focus = n; core.closePanel(); render(); }

  function crumbs() {
    const path = [];
    let p = focus;
    while (p) { path.unshift(p); p = p.parent ? core.bySlug[p.parent] : null; }
    let html = `<span data-c="core">Galactic Core</span>`;
    path.forEach((n, i) => {
      const last = i === path.length - 1;
      html += ` <span class="sep">&gt;</span> ` +
        (last ? `<span class="here">${core.short(n.title).slice(0, 34)}</span>`
              : `<span data-c="${n.slug}">${core.short(n.title).slice(0, 26)}</span>`);
    });
    crumbsEl.innerHTML = html;
    crumbsEl.querySelectorAll("span[data-c]").forEach(s => s.onclick = () =>
      setFocus(s.dataset.c === "core" ? null : core.bySlug[s.dataset.c]));
  }

  function updateLabels() {
    labelRaf = null;
    // active search overrides the zoom budget: matches are ALWAYS labeled
    const allowed = core.matched !== null ? core.matched
                  : core.labelAllowedSet(visible, scale);
    for (const g of nodesG.children) {
      const n = core.bySlug[g.dataset.slug]; if (!n) continue;
      const label = g.querySelector("text.label"), more = g.querySelector("text.more");
      if (label) {
        const show = !allowed || allowed.has(n.slug);
        label.style.display = show ? "" : "none";
        if (show) core.styleLabel(label, scale, { tiny: label.classList.contains("tiny") });
      }
      if (more) { more.style.fontSize = Math.max(9 / scale, 9) + "px";
                  more.style.strokeWidth = (3.5 / scale) + "px"; }
    }
  }
  const scheduleLabels = () => { if (!labelRaf) labelRaf = requestAnimationFrame(updateLabels); };

  function unmount() { cancelAnimationFrame(animId); focus = null;
                       if (stage) stage.innerHTML = ""; stage = null; }

  return { mount, render, unmount,
           legend: `<span style="color:#f0b24a">&#9679;</span> sun/root &nbsp;
                    <span style="color:#7fa7ff">&#9679;</span> open &nbsp;
                    <span style="color:#d9f2ff">&#10022;</span> frontier leaf &nbsp;
                    <span style="color:#ff9a4a">&#9678;</span> critical &nbsp;
                    <span style="color:#5a5f75">&#9679;</span> discussed &nbsp;
                    <span style="color:#f0b24a">&#9676;</span> +N deeper`,
           hint: "click = detail, double-click / Focus = re-center, drag = pan, wheel = zoom" };
})();
