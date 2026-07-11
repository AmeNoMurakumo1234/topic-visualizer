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

    stage.addEventListener("mousedown", ev => {
      if (ev.target.closest(".tnode")) return;
      stage.classList.add("dragging");
      const sx = ev.clientX - tx, sy = ev.clientY - ty;
      const mv = e => { tx = e.clientX - sx; ty = e.clientY - sy; apply(); };
      const up = () => { stage.classList.remove("dragging");
        removeEventListener("mousemove", mv); removeEventListener("mouseup", up); };
      addEventListener("mousemove", mv); addEventListener("mouseup", up);
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

  function layout() {
    let cursor = 0;
    const walk = (n, depth) => {
      if (n.open === undefined) n.open = true;
      n.lx = 40 + depth * (W + GX);
      const kids = n.open ? n.children : [];
      if (!kids.length) { n.ly = 40 + cursor; cursor += ROWH + GY; return; }
      kids.forEach(k => walk(k, depth + 1));
      n.ly = kids.reduce((s, k) => s + k.ly, 0) / kids.length;
    };
    core.roots.forEach(r => walk(r, 0));
  }

  function render() {
    if (!stage) return;
    layout();
    cards.innerHTML = ""; wires.innerHTML = "";
    const visible = [];
    const collect = n => { visible.push(n); if (n.open) n.children.forEach(collect); };
    core.roots.forEach(collect);
    let maxX = 0, maxY = 0;
    for (const n of visible) {
      maxX = Math.max(maxX, n.lx + W + 60); maxY = Math.max(maxY, n.ly + ROWH + 60);
      const d = document.createElement("div");
      d.className = "tnode" + (n.parent ? "" : " root") + (core.selected === n ? " selected" : "")
        + (!n.children.length ? " leaf" : "")
        + (n.state === "discussed" ? " discussed" : "")
        + (n.state === "seedling" ? " seedling" : "")
        + (core.searchDim(n) ? " searchdim" : "")
        + (n.critical && n.state !== "discussed" ? " critical" : "");
      d.style.left = n.lx + "px"; d.style.top = n.ly + "px";
      if (n.parent && n.state !== "discussed") {
        d.style.borderLeft = `3px solid hsl(${(222 + (n.hue || 0)) % 360}, 70%, 62%)`;
      }
      const s = core.short(n.title), w = core.weight(n.title);
      d.innerHTML = `<div class="sum">${s.slice(0, 72)}${s.length > 72 ? "..." : ""}</div>
        <div class="chips">${w ? `<span class="chip">${w}</span>` : ""}
          ${n.children.length ? `<span class="chip kids">${n.children.length} child(ren)</span>`
                              : `<span class="chip frontier">frontier</span>`}
          ${n.critical ? `<span class="chip crit">critical</span>` : ""}
          ${n.state === "discussed" ? `<span class="chip done">discussed</span>` : ""}
          ${n.state === "seedling" ? `<span class="chip seed">seedling</span>` : ""}
        </div>
        ${n.children.length ? `<div class="caret">${n.open ? "-" : "+"}</div>` : ""}`;
      d.addEventListener("click", ev => {
        if (ev.target.classList.contains("caret")) { n.open = !n.open; render(); return; }
        core.select(n);
      });
      cards.appendChild(d);
      if (n.parent) {
        const p = core.bySlug[n.parent];
        if (p) {
          const path = document.createElementNS(SVG_NS, "path");
          const x1 = p.lx + W, y1 = p.ly + ROWH / 2 - 6, x2 = n.lx, y2 = n.ly + ROWH / 2 - 6,
                mx = (x1 + x2) / 2;
          path.setAttribute("d", `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
          path.setAttribute("class", "wire");
          path.style.stroke = `hsl(${(222 + (n.hue || 0)) % 360}, 55%, 65%)`;
          wires.appendChild(path);
        }
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
