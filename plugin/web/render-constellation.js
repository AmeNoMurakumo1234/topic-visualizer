/* render-constellation.js - view A: the force graph ("what does my idea space look like?")
 * CANONICAL SOURCE: the topic-visualizer plugin repo. Vendored copies: do not edit in place.
 * Owns: its SVG, force sim, pan/zoom (cursor-anchored), semantic zoom. Storage-blind. */
window.TopicsRenderers = window.TopicsRenderers || {};
window.TopicsRenderers.constellation = (function () {
  "use strict";
  let core, stage, svg, view, fogG, edgesG, nodesG;
  let tx = 0, ty = 0, scale = 1, labelRaf = null, animId = null, userMoved = false;

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
      <marker id="tvXArrow" viewBox="0 0 10 10" refX="8" refY="5"
        markerWidth="6" markerHeight="6" orient="auto">
        <path d="M0,0 L10,5 L0,10 z" fill="#b48be0"/>
      </marker>
    </defs>`;

  function mount(container, coreRef) {
    core = coreRef; stage = container;
    stage.innerHTML = `<svg>${DEFS}<g class="tv-view"><g class="tv-fog"></g><g class="tv-edges"></g><g class="tv-nodes"></g></g></svg>`;
    svg = stage.querySelector("svg");
    view = stage.querySelector(".tv-view");
    fogG = stage.querySelector(".tv-fog");
    edgesG = stage.querySelector(".tv-edges");
    nodesG = stage.querySelector(".tv-nodes");
    const r = stage.getBoundingClientRect();
    tx = r.width / 2; ty = r.height / 2; scale = 1; userMoved = false; apply();

    // pointer capture: move/up keep arriving even when the cursor leaves the
    // window (a plain mouseup listener loses the release -> stuck drag)
    stage.addEventListener("pointerdown", ev => {
      if (ev.button !== 0 || ev.target.closest(".node")) return;
      userMoved = true;
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
    // cursor-anchored zoom (behavioral contract: the point under the mouse stays fixed)
    stage.addEventListener("wheel", ev => { ev.preventDefault();
      userMoved = true;
      const rect = stage.getBoundingClientRect();
      const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      const next = Math.max(0.25, Math.min(3, scale * (ev.deltaY < 0 ? 1.12 : 0.9)));
      tx = mx - (mx - tx) * (next / scale); ty = my - (my - ty) * (next / scale);
      scale = next; apply(); }, { passive: false });
  }

  const apply = () => { if (view) { view.setAttribute("transform",
    `translate(${tx},${ty}) scale(${scale})`); scheduleLabels(); } };

  /* auto-fit: big graphs open pulled-back so the whole constellation is on screen
   * (and the semantic-zoom label budget engages). Never fights the user - any pan
   * or zoom disables it. */
  function fit() {
    if (!stage || !core.nodes.length) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of core.nodes) {
      if (n.x < x0) x0 = n.x; if (n.x > x1) x1 = n.x;
      if (n.y < y0) y0 = n.y; if (n.y > y1) y1 = n.y;
    }
    const r = stage.getBoundingClientRect(), pad = 90;
    const next = Math.max(0.25, Math.min(1,
      Math.min(r.width / (x1 - x0 + 2 * pad), r.height / (y1 - y0 + 2 * pad))));
    scale = next;
    tx = r.width / 2 - scale * (x0 + x1) / 2;
    ty = r.height / 2 - scale * (y0 + y1) / 2;
    apply();
  }

  function seedPositions() {
    // keep existing positions across re-renders; seed only the unplaced
    const roots = core.roots.filter(n => n.x === undefined);
    core.roots.forEach((n, i) => {
      if (n.x !== undefined) return;
      const a = i / Math.max(1, core.roots.length) * 2 * Math.PI;
      n.x = 420 * Math.cos(a); n.y = 300 * Math.sin(a); n.vx = 0; n.vy = 0;
    });
    const place = n => n.children.forEach((c, i) => {
      if (c.x === undefined) {
        const a = i / Math.max(1, n.children.length) * 2 * Math.PI;
        c.x = n.x + 150 * Math.cos(a) + Math.sin(i * 7) * 30;
        c.y = n.y + 150 * Math.sin(a) + Math.cos(i * 5) * 30;
        c.vx = 0; c.vy = 0;
      }
      place(c);
    });
    core.roots.forEach(place);
    void roots;
  }

  function render() {
    if (!stage) return;
    seedPositions();
    fogG.innerHTML = ""; edgesG.innerHTML = ""; nodesG.innerHTML = "";
    for (const n of core.nodes) {
      if (!n.parent) {
        const f = document.createElementNS(SVG_NS, "circle");
        f.setAttribute("class", "fog"); f.dataset.slug = n.slug;
        f.setAttribute("r", Math.min(340, 130 + core.subtree(n).length * 4));
        f.setAttribute("fill", "url(#tvFogGrad)");
        f.style.filter = `hue-rotate(${n.hue || 0}deg)`;
        fogG.appendChild(f);
      } else {
        const e = document.createElementNS(SVG_NS, "path");
        e.setAttribute("class", "edge"); e.dataset.a = n.slug; e.dataset.b = n.parent;
        e.style.stroke = `hsl(${(222 + (n.hue || 0)) % 360}, 65%, 72%)`;
        edgesG.appendChild(e);
      }
      const g = document.createElementNS(SVG_NS, "g");
      g.setAttribute("class", "node" + (n.parent ? "" : " root") +
        (n.state === "discussed" ? " discussed" : "") +
        (n.state === "seedling" ? " seedling" : "") +
        (n.state === "pruned" || n.state === "expired" ? " archived" : "") +
        (core.searchDim(n) ? " searchdim" : "") +
        (core.selected === n ? " selected" : ""));
      g.dataset.slug = n.slug;
      const r = 14 + Math.min(14, core.subtree(n).length * 2);
      const leaf = !n.children.length, R = leaf ? 11 : r * 1.6;
      n.pri = (n.parent ? 0 : 6) + (n.critical ? 4 : 0) +
              Math.min(4, Math.log2(core.subtree(n).length + 1)) +
              (n.state === "discussed" ? -2 : 0);
      const body = leaf
        ? `<path class="leafstar" transform="scale(${R / 8})"
             style="fill: hsl(${(222 + (n.hue || 0)) % 360}, 80%, 88%)"
             d="M0,-8 L2.2,-2.2 L8,0 L2.2,2.2 L0,8 L-2.2,2.2 L-8,0 L-2.2,-2.2 Z"></path>`
        : `<circle class="core" r="${R}" ${n.parent ? `style="filter: hue-rotate(${n.hue || 0}deg)"` : `style="fill: url(#tvSunGrad)"`}></circle>`;
      const beacon = (n.critical && n.state !== "discussed")
        ? `<circle class="beacon" r="${R + 6}">
             <animate attributeName="r" values="${R + 3};${R + 11};${R + 3}" dur="1.8s" repeatCount="indefinite"/>
             <animate attributeName="stroke-opacity" values="0.9;0.15;0.9" dur="1.8s" repeatCount="indefinite"/>
           </circle>` : "";
      const label = core.short(n.title);
      g.innerHTML = `${beacon}${body}
        <text class="label" y="${R + 13}" text-anchor="middle">${core.esc(label.slice(0, 42))}${label.length > 42 ? "..." : ""}</text>
        ${leaf ? "" : `<text class="count" y="4" text-anchor="middle">${n.children.length}</text>`}`;
      g.addEventListener("click", ev => { ev.stopPropagation(); core.select(n); });
      nodesG.appendChild(g);
    }
    // cross-links (multi-parent DAG): the extra avenues into a topic - dashed,
    // quieter than tree edges, drawn under the nodes
    for (const x of core.xlinks || []) {
      const e = document.createElementNS(SVG_NS, "path");
      e.setAttribute("class", "edge xlink");
      // parent -> child so the arrowhead lands on the CHILD (direction grammar)
      e.dataset.a = x.to.slug; e.dataset.b = x.from.slug;
      e.setAttribute("marker-end", "url(#tvXArrow)");
      edgesG.appendChild(e);
    }
    position(); scheduleLabels(); settle();
  }

  function position() {
    for (const g of nodesG.children) { const n = core.bySlug[g.dataset.slug];
      if (n) g.setAttribute("transform", `translate(${n.x},${n.y})`); }
    for (const f of fogG.children) { const n = core.bySlug[f.dataset.slug];
      if (n) { f.setAttribute("cx", n.x); f.setAttribute("cy", n.y); } }
    for (const e of edgesG.children) {
      const a = core.bySlug[e.dataset.a], b = core.bySlug[e.dataset.b];
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const mx = (a.x + b.x) / 2 + dy * 0.12, my = (a.y + b.y) / 2 - dx * 0.12;
      e.setAttribute("d", `M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`);
    }
  }

  function settle() {
    cancelAnimationFrame(animId);
    let ticks = 0;
    const maxTicks = core.nodes.length > 250 ? 130 : 220;
    const step = () => {
      const nodes = core.nodes;
      for (const a of nodes) for (const b of nodes) {
        if (a === b) continue;
        const dx = a.x - b.x, dy = a.y - b.y, d2 = Math.max(400, dx * dx + dy * dy);
        const f = 26000 / d2, d = Math.sqrt(d2);
        a.vx += dx / d * f; a.vy += dy / d * f;
      }
      for (const n of nodes) if (n.parent && core.bySlug[n.parent]) {
        const p = core.bySlug[n.parent], dx = p.x - n.x, dy = p.y - n.y,
              d = Math.sqrt(dx * dx + dy * dy) || 1, pull = (d - 140) * 0.02;
        n.vx += dx / d * pull; n.vy += dy / d * pull;
        p.vx -= dx / d * pull * 0.5; p.vy -= dy / d * pull * 0.5;
      }
      // extra avenues tug gently (a third of a tree edge) so linked families drift closer
      for (const x of core.xlinks || []) {
        const n = x.from, p = x.to, dx = p.x - n.x, dy = p.y - n.y,
              d = Math.sqrt(dx * dx + dy * dy) || 1, pull = (d - 190) * 0.007;
        n.vx += dx / d * pull; n.vy += dy / d * pull;
        p.vx -= dx / d * pull * 0.5; p.vy -= dy / d * pull * 0.5;
      }
      for (const n of nodes) { n.vx += -n.x * 0.0012; n.vy += -n.y * 0.0012;
        n.x += n.vx *= 0.82; n.y += n.vy *= 0.82; }
      position();
      // camera pulls back as the graph blooms (every ~15 ticks + once settled)
      if (!userMoved && (ticks % 15 === 0 || ticks === maxTicks - 1)) fit();
      if (++ticks < maxTicks) animId = requestAnimationFrame(step);
    };
    animId = requestAnimationFrame(step);
  }

  function updateLabels() {
    labelRaf = null;
    // active search overrides the zoom budget: matches are ALWAYS labeled
    const allowed = core.matched !== null ? core.matched
                  : core.labelAllowedSet(core.nodes, scale);
    for (const g of nodesG.children) {
      const n = core.bySlug[g.dataset.slug]; if (!n) continue;
      const label = g.querySelector("text.label"), count = g.querySelector("text.count");
      if (label) {
        const show = !allowed || allowed.has(n.slug);
        label.style.display = show ? "" : "none";
        if (show) core.styleLabel(label, scale);
      }
      if (count) count.style.display = scale >= 0.55 ? "" : "none";
    }
  }
  const scheduleLabels = () => { if (!labelRaf) labelRaf = requestAnimationFrame(updateLabels); };

  function unmount() {
    cancelAnimationFrame(animId);
    cancelAnimationFrame(labelRaf); labelRaf = null;
    if (stage) stage.innerHTML = "";
    stage = null;
  }

  return { mount, render, unmount,
           legend: `<span style="color:#f0b24a">&#9679;</span> root sun &nbsp;
                    <span style="color:#7fa7ff">&#9679;</span> open &nbsp;
                    <span style="color:#d9f2ff">&#10022;</span> frontier leaf &nbsp;
                    <span style="color:#ff9a4a">&#9678;</span> critical &nbsp;
                    <span style="color:#5a5f75">&#9679;</span> discussed`,
           hint: "drag = pan, wheel = zoom, click node = detail" };
})();
