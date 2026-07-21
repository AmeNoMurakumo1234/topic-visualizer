/* render-projects.js - view D (0.44): the PROJECTS management page. Not a topics view -
 * the boards themselves are the objects: copy topics between boards (merge with dedup,
 * source untouched), trash a board (restorable ~30d), hard-delete an EMPTY board (the
 * bogus-URL-mint cleanup, owner-ratified 2026-07-20), restore from trash.
 * CANONICAL SOURCE: the topic-visualizer plugin repo. Vendored copies: do not edit in place.
 * Capability-gated: the shell registers this tab only when adapter.projectsAdmin exists.
 * Plain DOM, no pan stage - management pages must never inherit the drag machinery
 * (see the 0.43.2 pointer-capture lesson). Storage-blind via adapter.projectsAdmin. */
window.TopicsRenderers = window.TopicsRenderers || {};
window.TopicsRenderers.projects = (function () {
  "use strict";
  let core, stage, admin;

  const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function stateChips(byState) {
    const order = ["seedling", "open", "discussed", "pruned", "expired"];
    return order.filter(s => byState && byState[s])
      .map(s => `<span class="pj-chip pj-${s}">${byState[s]} ${s}</span>`).join(" ") ||
      '<span class="pj-chip pj-empty">empty</span>';
  }

  async function act(fn, confirmMsg) {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    let res = null;
    try { res = await fn(); } catch (e) { res = { error: String(e) }; }
    if (res && res.error) window.alert("refused: " + res.error);
    render();                                   // always re-read truth from the server
    return res;
  }

  function boardCard(b, all) {
    const others = all.filter(o => o.key !== b.key && !o.error);
    const copySel = others.length
      ? `<select class="pj-copysel" data-k="${esc(b.key)}">
           <option value="">copy topics to...</option>
           ${others.map(o => `<option value="${esc(o.key)}">${esc(o.label)}</option>`).join("")}
         </select>`
      : "";
    const del = b.empty
      ? `<button class="pj-btn pj-danger" data-act="hard" data-k="${esc(b.key)}"
           title="empty board - gone for good">hard delete</button>`
      : `<button class="pj-btn" data-act="trash" data-k="${esc(b.key)}"
           title="moves to trash; restorable ~30 days">trash</button>`;
    return `<div class="pj-card${b.current ? " pj-current" : ""}">
      <div class="pj-head"><b>${esc(b.label)}</b>
        ${b.current ? '<span class="pj-chip pj-cur">viewing</span>' : ""}
        <span class="pj-key">${esc(b.key)}</span></div>
      <div class="pj-meta">${b.error ? `<span class="pj-chip pj-err">unreadable: ${esc(b.error)}</span>`
        : stateChips(b.by_state)} <span class="pj-kb">${b.file_kb} KB</span></div>
      <div class="pj-actions">${copySel}${del}</div>
    </div>`;
  }

  async function render() {
    if (!stage) return;
    let ov = null;
    try { ov = await admin.overview(); } catch (e) { ov = null; }
    if (!stage) return;   // 0.44.2: the tab can unmount during the await - stale render must drop
    if (!ov || !ov.boards) {
      stage.innerHTML = '<div class="pj-wrap"><p class="pj-note">projects overview unavailable ' +
        "(server down, or it predates 0.44 - restart the topics server)</p></div>";
      return;
    }
    const trash = ov.trash.length
      ? `<h3 class="pj-h3">trash <span class="pj-note">(auto-purged ~30d after trashing)</span></h3>
         <div class="pj-cards">${ov.trash.map(t =>
           `<div class="pj-card pj-trashed"><div class="pj-head"><b>${esc(t.name)}</b>
              <span class="pj-kb">${t.file_kb} KB</span></div>
            <div class="pj-actions"><button class="pj-btn" data-act="restore"
              data-k="${esc(t.name)}">restore</button></div></div>`).join("")}</div>`
      : "";
    stage.innerHTML = `<div class="pj-wrap">
      <p class="pj-note">${esc(ov.note)}</p>
      <div class="pj-cards">${ov.boards.map(b => boardCard(b, ov.boards)).join("")}</div>
      ${trash}</div>`;

    stage.querySelectorAll(".pj-btn").forEach(btn => btn.addEventListener("click", () => {
      const k = btn.dataset.k;
      if (btn.dataset.act === "trash")
        act(() => admin.del(k, "trash"),
            `Trash board "${k}"? It moves to the trash and is restorable for ~30 days.`);
      if (btn.dataset.act === "hard")
        act(() => admin.del(k, "hard"),
            `Hard-delete EMPTY board "${k}"? This one is gone for good.`);
      if (btn.dataset.act === "restore")
        act(() => admin.restore(k));
    }));
    stage.querySelectorAll(".pj-copysel").forEach(sel => sel.addEventListener("change", () => {
      const from = sel.dataset.k, to = sel.value;
      if (!to) return;
      sel.value = "";
      act(async () => {
        const r = await admin.copy(from, to);
        if (r && r.ok) window.alert(
          `copied ${r.copied} topic(s) from "${from}" to "${to}" ` +
          `(${r.skipped_identical} identical skipped, ${r.renamed_collisions} renamed); ` +
          "source untouched - trash it yourself once you've verified the copy");
        return r;
      }, `Copy all live topics from "${from}" into "${to}"? Merge with dedup; ` +
         `"${from}" is not modified.`);
    }));
  }

  return {
    legend: "boards, their live counts, and the trash",
    hint: "copy = merge with dedup (source untouched) | trash is restorable ~30d | " +
          "hard delete: empty boards only",
    mount(container, coreRef) { core = coreRef; stage = container;
      admin = (window.TopicsAdapter || {}).projectsAdmin; render(); },
    render,
    unmount() { if (stage) stage.innerHTML = ""; stage = null; },
  };
})();
