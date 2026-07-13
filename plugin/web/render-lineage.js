/* render-lineage.js - view B: the collapsible tidy tree ("let me work this branch").
 * CANONICAL SOURCE: the topic-visualizer plugin repo. Vendored copies: do not edit in place.
 * Owns: its world div (wires + cards), pan/zoom (cursor-anchored), collapse state.
 * Deliberately NO label culling: collapsing is this view's zoom-out. Storage-blind. */
window.TopicsRenderers = window.TopicsRenderers || {};
window.TopicsRenderers.lineage = (function () {
  "use strict";
  const W = 220, GX = 80, GY = 18, ROWH = 74;
  const SVG_NS = "http://www.w3.org/2000/svg";
  let core, stage, world, wires, cards;
  let tx = 20, ty = 20, scale = 1;

  function mount(container, coreRef) {
    core = coreRef; stage = container;
    stage.innerHTML = `<div class="tv-world"><svg class="tv-wires"></svg><div class="tv-cards"></div></div>`;
    world = stage.querySelector(".tv-world");
    wires = stage.querySelector(".tv-wires");
    cards = stage.querySelector(".tv-cards");
    tx = 20; ty = 20; scale = 1; apply();

    // pointer capture: the drag keeps receiving move/up EVEN when the cursor
    // leaves the window - a plain mouseup listener loses the release out there
    // and the view stays glued to the mouse (owner-caught stuck-drag bug)
    stage.addEventListener("pointerdown", ev => {
      if (ev.button !== 0 || ev.target.closest(".tnode")) return;
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
      const next = Math.max(0.3, Math.min(2.5, scale * (ev.deltaY < 0 ? 1.12 : 0.9)));
      tx = mx - (mx - tx) * (next / scale); ty = my - (my - ty) * (next / scale);
      scale = next; apply(); }, { passive: false });
  }

  const apply = () => { if (world) world.style.transform =
    `translate(${tx}px,${ty}px) scale(${scale})`; };

  /* Two-pass layout: cards are VARIABLE height (wrapped titles, multi-line chips),
   * so first build + MEASURE the real card heights, then stack rows on the measured
   * heights - a fixed row slot is exactly the overlap bug we shipped once. */
  function render() {
    if (!stage) return;
    cards.innerHTML = "";
    wires.innerHTML = `<defs><marker id="tvXArrowL" viewBox="0 0 10 10" refX="10" refY="5"
      markerWidth="7" markerHeight="7" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#b48be0"/></marker></defs>`;
    const visible = [];
    // Lineage is a DRILL-DOWN view ("work this branch"), NOT a whole-forest overview - that is what
    // Constellation is for. Rendering every node expanded is what makes it unusable at scale, so on
    // any tree past a handful of nodes we default to COLLAPSED beyond the top level and let the user
    // open the branch they want. Small trees stay fully open (nothing to gain by hiding them).
    const autoDepth = Object.keys(core.bySlug || {}).length <= 35 ? Infinity : 1;
    const collect = (n, depth) => {
      if (n.open === undefined) n.open = depth < autoDepth;   // user carets override this per-node
      n.lx = 40 + depth * (W + GX);
      visible.push(n);
      if (n.open) n.children.forEach(c => collect(c, depth + 1));
    };
    core.roots.forEach(r => collect(r, 0));

    // pass 1: build every card (position set later), measure real heights
    const domOf = {};
    for (const n of visible) {
      const d = document.createElement("div");
      d.className = "tnode" + (n.parent ? "" : " root") + (core.selected === n ? " selected" : "")
        + (!n.children.length ? " leaf" : "")
        + (n.state === "discussed" ? " discussed" : "")
        + (n.state === "seedling" ? " seedling" : "")
        + (n.state === "pruned" || n.state === "expired" ? " archived" : "")
        + (core.searchDim(n) ? " searchdim" : "")
        + (n.critical && n.state !== "discussed" ? " critical" : "");
      if (n.parent && n.state !== "discussed") {
        d.style.borderLeft = `3px solid hsl(${(222 + (n.hue || 0)) % 360}, 70%, 62%)`;
      }
      const s = core.short(n.title), w = core.weight(n.title);
      d.innerHTML = `<div class="sum">${core.esc(s.slice(0, 72))}${s.length > 72 ? "..." : ""}</div>
        <div class="chips">${w ? `<span class="chip">${core.esc(w)}</span>` : ""}
          ${n.children.length ? `<span class="chip kids">${n.children.length} child(ren)</span>`
                              : `<span class="chip frontier">frontier</span>`}
          ${n.critical ? `<span class="chip crit">critical</span>` : ""}
          ${n.state === "discussed" ? `<span class="chip done">discussed</span>` : ""}
          ${n.state === "seedling" ? `<span class="chip seed">seedling</span>` : ""}
          ${n.extraParents && n.extraParents.length
            ? `<span class="chip xlink" title="also reachable via ${core.esc(n.extraParents
                 .map(x => x.slug).join(", "))}">&#8618; ${n.extraParents.length
                 + (n.parent ? 1 : 0)} in</span>` : ""}
          ${(core.xlinks || []).some(x => x.to === n)
            ? `<span class="chip xlink" title="extra avenue INTO ${core.esc((core.xlinks || [])
                 .filter(x => x.to === n).map(x => x.from.slug).join(", "))}">&#8618; ${
                 (core.xlinks || []).filter(x => x.to === n).length} out</span>` : ""}
        </div>
        ${n.children.length ? `<div class="caret">${n.open ? "-" : "+"}</div>` : ""}`;
      d.addEventListener("click", ev => {
        if (ev.target.classList.contains("caret")) { n.open = !n.open; render(); return; }
        core.select(n);
      });
      cards.appendChild(d);
      domOf[n.slug] = d;
    }
    for (const n of visible) n.lh = domOf[n.slug].offsetHeight || ROWH;

    // pass 2: stack rows on MEASURED heights; parents center on their children's
    // span, a parent taller than that span pushes the next row down, and a
    // per-column clamp keeps same-depth neighbors from ever touching
    let cursor = 40;
    const colBottom = {};
    const settle = n => {
      if (colBottom[n.lx] !== undefined) n.ly = Math.max(n.ly, colBottom[n.lx] + GY);
      colBottom[n.lx] = n.ly + n.lh;
    };
    const place = n => {
      const kids = n.open ? n.children : [];
      if (!kids.length) {
        n.ly = cursor; settle(n); cursor = Math.max(cursor, n.ly + n.lh + GY);
        return;
      }
      kids.forEach(place);
      const first = kids[0], last = kids[kids.length - 1];
      n.ly = (first.ly + last.ly + last.lh) / 2 - n.lh / 2;
      settle(n);
      cursor = Math.max(cursor, n.ly + n.lh + GY);
    };
    core.roots.forEach(place);

    let maxX = 0, maxY = 0;
    for (const n of visible) {
      maxX = Math.max(maxX, n.lx + W + 60); maxY = Math.max(maxY, n.ly + n.lh + 60);
      const d = domOf[n.slug];
      d.style.left = n.lx + "px"; d.style.top = n.ly + "px";
      if (n.parent) {
        const p = core.bySlug[n.parent];
        if (p) {
          const path = document.createElementNS(SVG_NS, "path");
          const x1 = p.lx + W, y1 = p.ly + (p.lh || ROWH) / 2,
                x2 = n.lx, y2 = n.ly + (n.lh || ROWH) / 2, mx = (x1 + x2) / 2;
          path.setAttribute("d", `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
          path.setAttribute("class", "wire");
          path.style.stroke = `hsl(${(222 + (n.hue || 0)) % 360}, 55%, 65%)`;
          wires.appendChild(path);
        }
      }
    }
    // cross-link wires (multi-parent DAG): dashed violet curves from each EXTRA
    // avenue to the child. GRAMMAR MATTERS (owner-caught): in this view the left
    // edge means "parent side" and the right edge means "child side", so a cross
    // wire ALWAYS leaves the parent's RIGHT edge and enters the child's LEFT edge
    // (looping backward when the child sits left of the parent) - nearest-edge
    // anchoring made an outgoing link read as a second parent. Arrowheads point
    // at the child. Drawn only when both cards are visible.
    const shown = new Set(visible.map(n => n.slug));
    for (const n of visible) {
      for (const x of (n.extraParents || [])) {
        const p = core.bySlug[x.slug];
        if (!p || !shown.has(p.slug)) continue;
        const path = document.createElementNS(SVG_NS, "path");
        const x1 = p.lx + W, y1 = p.ly + (p.lh || ROWH) / 2,
              x2 = n.lx, y2 = n.ly + (n.lh || ROWH) / 2;
        // gradual attach: horizontal tangent at BOTH card edges, easing into the
        // curve with a reach proportional to the span - and a PORT DOT at the
        // parent edge, so an attached wire can never be mistaken for one merely
        // passing behind the card (passing lines have no dot, no flat approach)
        const reach = Math.max(80, Math.min(220,
          Math.hypot(x2 - x1, y2 - y1) * 0.35));
        path.setAttribute("d",
          `M ${x1} ${y1} C ${x1 + reach} ${y1}, ${x2 - reach} ${y2}, ${x2} ${y2}`);
        path.setAttribute("class", "wire xwire");
        path.setAttribute("marker-end", "url(#tvXArrowL)");
        wires.appendChild(path);
        const port = document.createElementNS(SVG_NS, "circle");
        port.setAttribute("cx", x1); port.setAttribute("cy", y1);
        port.setAttribute("r", 3.5); port.setAttribute("class", "xport");
        wires.appendChild(port);
      }
    }
    wires.setAttribute("width", maxX); wires.setAttribute("height", maxY);
    wires.style.width = maxX + "px"; wires.style.height = maxY + "px";
  }

  function unmount() { if (stage) stage.innerHTML = ""; stage = null; }

  return { mount, render, unmount,
           legend: `<span style="color:#f0b24a">&#9632;</span> root &nbsp;
                    <span style="color:#6ea8ff">&#9632;</span> open &nbsp;
                    <span style="color:#7fd4ff">&#9632;</span> frontier leaf &nbsp;
                    <span style="color:#ff9a4a">&#9632;</span> critical &nbsp;
                    <span style="color:#5a5f75">&#9632;</span> discussed`,
           hint: "drag = pan, wheel = zoom, circle = expand/collapse, card = detail" };
})();
