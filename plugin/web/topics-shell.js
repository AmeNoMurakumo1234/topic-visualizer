/* topics-shell.js - boot + orchestration: one data load, three switchable renderers.
 * CANONICAL SOURCE: the topic-visualizer plugin repo. Vendored copies: do not edit. */
(function () {
  "use strict";
  const params = new URLSearchParams(location.search);
  const demo = parseInt(params.get("demo") || "0", 10) || 0;

  const stage = document.getElementById("stage");
  const rendererHost = document.getElementById("renderer");
  const core = TopicsCore.create(window.TopicsAdapter, {
    panel: document.getElementById("panel"),
    confirmModal: document.getElementById("confirm"),
    confirmBox: document.getElementById("confirmBox"),
    statEl: document.getElementById("stat"),
  }, { demo, actor: "human" });

  let active = null, activeName = "";
  function show(name) {
    const next = window.TopicsRenderers[name];
    if (!next) return;
    if (active) active.unmount();
    active = next; activeName = name;
    localStorage.setItem("topics-view", name);
    for (const b of document.getElementById("viewtabs").children) {
      b.classList.toggle("active", b.dataset.v === name);
    }
    document.getElementById("legend").innerHTML = next.legend || "";
    document.getElementById("hint").textContent = " | " + (next.hint || "");
    active.mount(rendererHost, core);
    active.render();
  }
  core.onChange = () => { if (active) active.render(); };

  document.getElementById("viewtabs").addEventListener("click", e => {
    const b = e.target.closest("button[data-v]");
    if (b) show(b.dataset.v);
  });

  // search bar: filters every view live (Esc clears); debounced
  const searchEl = document.getElementById("search");
  if (searchEl) {
    let deb = null;
    searchEl.addEventListener("input", () => {
      clearTimeout(deb);
      deb = setTimeout(() => core.setSearch(searchEl.value), 250);
    });
    searchEl.addEventListener("keydown", e => {
      if (e.key === "Escape") { searchEl.value = ""; core.setSearch(""); }
    });
  }
  // Esc closes the side panel (unless typing in an input - those keep their own Esc)
  addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    const el = document.activeElement;
    if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
    const confirmEl = document.getElementById("confirm");
    if (confirmEl && confirmEl.classList.contains("open")) {
      confirmEl.className = "";        // the modal owns Esc while it is up
      return;
    }
    if (core.selected) { core.closePanel(); core.onChange(); }
  });
  // quick-add: the human's two-second door (Enter plants an open root topic;
  // select a node first to plant a child under it)
  const quickEl = document.getElementById("quickadd");
  if (quickEl) quickEl.addEventListener("keydown", async e => {
    if (e.key !== "Enter") return;
    const parent = core.selected ? core.selected.slug : null;
    await core.quickAdd(quickEl.value, parent);
    quickEl.value = "";
  });
  // archive explorer toggle: show pruned/expired ghosts (resurrectable). Hidden
  // when the adapter cannot serve an archive (capability detection).
  const archEl = document.getElementById("archive");
  if (archEl) {
    if (window.TopicsAdapter.archiveCapable === false || demo) {
      archEl.closest(".archchip").style.display = "none";
    } else {
      archEl.addEventListener("change", () => core.setArchive(archEl.checked));
    }
  }
  // seam health strip (hidden when the adapter has no health endpoint)
  (async () => {
    const h = await core.health();
    const el = document.getElementById("seamhealth");
    if (el && h) el.textContent =
      `seam 30d: ${h.captured} captured | ${h.served} served | ` +
      `${h.converted} converted | ${h.pruned + h.expired} pruned/expired` +
      (h.beacon_warning ? " | beacons HIGH" : "");
  })();

  core.paintStars(stage, document.getElementById("stars"));
  addEventListener("resize", () =>
    core.paintStars(stage, document.getElementById("stars")));

  // validate the stored view (legacy shells stored a/b/c) - never boot into nothing
  const LEGACY = { a: "constellation", b: "lineage", c: "starchart" };
  let saved = localStorage.getItem("topics-view") || "starchart";
  saved = LEGACY[saved] || saved;
  if (!window.TopicsRenderers[saved]) saved = "starchart";
  core.load().then(() => show(saved));
})();
