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
  let tx = 20, ty = 20, scale = 1, ac = null;
  let critsRevealed = false;               // reveal beacons once per mount (initial state)

  function mount(container, coreRef) {
    core = coreRef; stage = container;
    if (ac) ac.abort();
    ac = new AbortController();
    critsRevealed = false;
    stage.innerHTML = `<div class="tv-world"><svg class="tv-wires"></svg><div class="tv-cards"></div></div>`;
    // AFTER the innerHTML reset, or it is wiped. anchoredRelayout keeps the view still across the
    // row add/remove, the way toggleOpen does for a collapse.
    core.discussedToggle(stage, "lineage", anchoredRelayout);
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
    }, { signal: ac.signal });
    stage.addEventListener("wheel", ev => { ev.preventDefault();
      const rect = stage.getBoundingClientRect();
      const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
      const next = Math.max(0.3, Math.min(2.5, scale * (ev.deltaY < 0 ? 1.12 : 0.9)));
      tx = mx - (mx - tx) * (next / scale); ty = my - (my - ty) * (next / scale);
      scale = next; apply(); }, { passive: false, signal: ac.signal });
  }

  const apply = () => { if (world) world.style.transform =
    `translate(${tx}px,${ty}px) scale(${scale})`; };

  // toggle a node's expand state while keeping IT fixed on screen (a collapse must never make the
  // clicked node jump or scroll out of view). Uses the node's own ly, which persists across render.
  function toggleOpen(n) {
    const lyBefore = n.ly;
    n.open = !n.open;
    if (!n.open) n.children.forEach(c => { c.revealed = false; });  // a full collapse clears partial reveals
    render();
    ty += (lyBefore - n.ly) * scale; apply();
  }
  // panel actions on the tree, so you never have to hunt the tiny +/- caret:
  //  - Expand/Collapse all children
  //  - "Show critical/discussed/seedling (N)" - PARTIAL reveal of just that category's hidden children
  //  - "Hide this branch" - un-reveal a single revealed child, leaving its siblings shown
  const CATS = [
    { label: "critical", test: c => c.critical },
    { label: "discussed", test: c => c.state === "discussed" },
    { label: "seedling", test: c => c.state === "seedling" },
  ];
  // hide a specific child + its subtree - the inverse of following an avenue-out to reveal one child.
  // Works whether the child shows via a partial reveal OR under a fully-open parent: in the open case
  // we DEMOTE the parent to partial (reveal every sibling, drop just this one) so the rest of the view
  // is untouched. The parent is held visually anchored across the relayout.
  function hideBranch(n) {
    const par = n.parent && core.bySlug[n.parent];
    const lyBefore = par ? par.ly : 0;
    if (par && par.open) { par.open = false; par.children.forEach(c => { if (c !== n) c.revealed = true; }); }
    n.revealed = false; n.open = false;
    render();
    if (par) { ty += (lyBefore - par.ly) * scale; apply(); }
  }
  function selectNode(n) {
    const btns = [];
    if (n.children.length) {
      btns.push({ label: n.open ? "Collapse all" : "Expand all", className: "expandbtn",
                  onClick: () => { toggleOpen(n); selectNode(n); } });
      for (const cat of CATS) {
        const hidden = n.children.filter(c => cat.test(c) && !(n.open || c.revealed));
        if (hidden.length) btns.push({
          label: `Show ${cat.label} (${hidden.length})`, className: "revealbtn",
          onClick: () => { hidden.forEach(c => { c.revealed = true; }); render(); selectNode(n); } });
      }
    }
    const par = n.parent && core.bySlug[n.parent];   // any non-root child can be hidden from its parent
    if (par) btns.push({
      label: "Hide this branch", className: "hidebtn",
      onClick: () => { hideBranch(n); selectNode(par); } });
    core.select(n, btns.length ? btns : undefined);
  }

  /* ONE visibility rule, shared by BOTH layout passes.
   *
   * PARTIAL expand: when a node is not fully open, still show any children individually revealed (by
   * navigating to them) - a thin thread to the node you asked for, not its whole fan. Then drop
   * hidden-discussed cards.
   *
   * This used to live only inside collect() (pass 1), so pass 2 - which owns the geometry - still
   * stacked rows for cards pass 1 had dropped. Hiding discussed topics therefore left their rows
   * RESERVED: measured on the real tree, hiding two discussed roots left 243px of dead space at the
   * top and moved ZERO surviving cards, while the canvas height did not change at all. A filter that
   * pass 2 does not know about cannot affect the layout, so it has to be one rule, not two.
   *
   * It also removes a latent NaN: place() read n.lh, which only pass 1 sets, so laying out a card
   * that pass 1 had skipped used a STALE-or-undefined height and could poison a whole column. */
  const kidsOf = n => (n.open ? n.children : n.children.filter(c => c.revealed))
    .filter(c => !core.hiddenDiscussed(c, "lineage"));
  const shownRoots = () => core.roots.filter(r => !core.hiddenDiscussed(r, "lineage"));

  /* Hiding or showing discussed cards adds or removes whole rows, so every card below the change
   * moves. Expanding a node already compensates for that (toggleOpen holds the clicked node still);
   * the discussed toggle went through a bare re-render and did not, so the branch you were reading
   * jumped by however many rows vanished above it. Anchor on the deepest node that survives BOTH
   * states: the selection when it is on screen, else the topmost card. */
  let shownSlugs = new Set();          // what render() actually laid out, for anchor survival checks
  function anchorChain() {
    const laid = [...shownSlugs].map(s => core.bySlug[s]).filter(Boolean);
    const start = (core.selected && shownSlugs.has(core.selected.slug))
      ? core.selected
      : laid.reduce((top, n) => (top === null || n.ly < top.ly ? n : top), null);
    const chain = [];
    for (let n = start; n; n = n.parent ? core.bySlug[n.parent] : null) {
      if (shownSlugs.has(n.slug)) chain.push({ node: n, ly: n.ly });
    }
    return chain;
  }
  function anchoredRelayout(commit) {
    const chain = anchorChain();
    commit();                          // flips the flag; core re-renders us through onChange
    // Deepest survivor first: if the anchor was itself the discussed card that just vanished, fall
    // back to its nearest surviving ancestor rather than throwing the view to the top of the tree.
    const keep = chain.find(e => shownSlugs.has(e.node.slug));
    if (keep) { ty += (keep.ly - keep.node.ly) * scale; apply(); }
  }

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
    // initial state: small trees open fully; on a big tree open only SHALLOW + NARROW nodes, so a node
    // with LOTS of children is never dumped fully-expanded on first visit. Criticals are surfaced anyway
    // via the reveal pass below (partial expansion). User carets override this per node.
    const small = Object.keys(core.bySlug || {}).length <= 35, FANCAP = 7;
    if (!critsRevealed) {                    // one-time per Lineage mount: reveal the path to every
      critsRevealed = true;                  // critical node, so beacons always show on first visit
      (core.nodes || []).forEach(t => { if (t.critical) core.revealPath(t); });
    }
    const collect = (n, depth) => {
      if (n.open === undefined) n.open = small || (depth < 1 && n.children.length <= FANCAP);
      n.lx = 40 + depth * (W + GX);
      visible.push(n);
      kidsOf(n).forEach(c => collect(c, depth + 1));
    };
    shownRoots().forEach(r => collect(r, 0));
    shownSlugs = new Set(visible.map(n => n.slug));

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
      const shownKids = n.open ? n.children.length : n.children.filter(c => c.revealed).length;
      const partial = !n.open && shownKids > 0 && shownKids < n.children.length;
      d.innerHTML = `<div class="sum">${core.esc(s.slice(0, 72))}${s.length > 72 ? "..." : ""}</div>
        <div class="chips">${w ? `<span class="chip">${core.esc(w)}</span>` : ""}
          ${n.children.length
            ? `<span class="chip kids${partial ? " partial" : ""}">${partial
                ? `${shownKids} of ${n.children.length} shown`
                : `${n.children.length} child(ren)`}</span>`
            : `<span class="chip frontier">frontier</span>`}
          ${n.critical ? `<span class="chip crit">critical</span>` : ""}
          ${n.state === "discussed" ? `<span class="chip done">discussed</span>` : ""}
          ${n.state === "seedling" ? `<span class="chip seed">seedling</span>` : ""}
          ${n.extraParents && n.extraParents.length
            ? `<span class="chip xlink" title="also reachable via ${core.esc(n.extraParents
                 .map(x => x.slug).join(", "))}">&#8618; ${n.extraParents.length
                 + (n.parent ? 1 : 0)} in</span>` : ""}
          ${(core.xlinks || []).some(x => x.to === n)
            ? `<span class="chip xlink" title="extra avenue OUT to ${core.esc((core.xlinks || [])
                 .filter(x => x.to === n).map(x => x.from.slug).join(", "))}">&#8618; ${
                 (core.xlinks || []).filter(x => x.to === n).length} out</span>` : ""}
        </div>
        ${n.children.length ? `<div class="caret" title="${n.open ? "collapse" : partial
            ? "partially expanded - click to show all" : "expand"}">${
            n.open ? "−" : partial ? "⋯" : "+"}</div>` : ""}`;
      d.addEventListener("click", ev => {
        if (ev.target.classList.contains("caret")) { toggleOpen(n); return; }
        selectNode(n);
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
      const kids = kidsOf(n);            // SAME rule as collect - see kidsOf
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
    shownRoots().forEach(place);

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
    const shown = shownSlugs;   // also the anchor-survival record for anchoredRelayout
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
        path.setAttribute("class", "wire xwire" + (x.kind === "co_parent" ? " coparent" : ""));
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

    // a just-navigated node (panel avenue click set core._centerOn) - bring it to the middle
    if (core._centerOn && visible.indexOf(core._centerOn) >= 0) {
      const t = core._centerOn, r = stage.getBoundingClientRect();
      tx = r.width / 2 - (t.lx + W / 2) * scale;
      ty = r.height / 2 - (t.ly + (t.lh || ROWH) / 2) * scale;
      apply();
    }
    core._centerOn = null;
  }

  function unmount() {
    if (ac) { ac.abort(); ac = null; }   // drop the pan/zoom listeners on the shared container
    if (stage) stage.innerHTML = ""; stage = null;
  }

  return { mount, render, unmount,
           legend: `<span style="color:#f0b24a">&#9632;</span> root &nbsp;
                    <span style="color:#6ea8ff">&#9632;</span> open &nbsp;
                    <span style="color:#7fd4ff">&#9632;</span> frontier leaf &nbsp;
                    <span style="color:#ff9a4a">&#9632;</span> critical &nbsp;
                    <span style="color:#5a5f75">&#9632;</span> discussed`,
           hint: "drag = pan, wheel = zoom, circle = expand/collapse, card = detail" };
})();
