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
  // project switcher: a dropdown of the store's projects, capability-gated on
  // adapter.projects() + a #projsel element in the host page (hidden if either is
  // absent). Switching reloads scoped to ?project=<key> - each adapter reads that and
  // scopes every call. The project list is whatever the ADAPTER reports (Claude projects
  // for the local store, board projects for the message board) - nothing hardcoded.
  const projSel = document.getElementById("projsel");
  if (projSel && window.TopicsAdapter.projects && !demo) {
    (async () => {
      let info = null;
      try { info = await window.TopicsAdapter.projects(); } catch (e) { info = null; }
      if (!info || !info.projects || info.projects.length < 1) { projSel.style.display = "none"; return; }
      const escv = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
      projSel.innerHTML = info.projects.map(p =>
        `<option value="${escv(p.key)}"${p.current ? " selected" : ""}>${escv(p.label || p.key)}</option>`).join("");
      projSel.style.display = "";
      projSel.addEventListener("change", () => {
        const u = new URLSearchParams(location.search);
        u.set("project", projSel.value);        // keep demo/still/etc; re-scope to the pick
        location.search = u.toString();
      });
    })();
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

  // backdrop: the generated canvas scene is the DEFAULT; if the plugin's
  // backgrounds/ folder has images, a modal thumbnail gallery lets the user
  // eyeball-pick one (mostly-transparent, so nodes stay legible). Choice persists.
  const starsCanvas = document.getElementById("stars");
  const bgImage = document.getElementById("bgimage");
  const bgOpen = document.getElementById("bgopen");
  const bgModal = document.getElementById("bgmodal");
  const bgGrid = document.getElementById("bggrid");
  function applyBackdrop(choice, urlBase) {
    if (choice && choice !== "__default__") {
      bgImage.style.backgroundImage = `url("${urlBase}${encodeURIComponent(choice)}")`;
      bgImage.style.display = "block";
      starsCanvas.style.display = "none";       // image replaces the generated scene
    } else {
      bgImage.style.backgroundImage = "";
      bgImage.style.display = "none";
      starsCanvas.style.display = "";
      core.paintStars(stage, starsCanvas);
    }
  }
  core.paintStars(stage, starsCanvas);
  addEventListener("resize", () => {
    if (starsCanvas.style.display !== "none") core.paintStars(stage, starsCanvas);
  });
  if (bgOpen && bgModal && window.TopicsAdapter.backgrounds && !demo) {
    (async () => {
      const { list, urlBase } = await window.TopicsAdapter.backgrounds();
      if (!list.length) return;               // no images -> keep the default scene
      let current = localStorage.getItem("topics-bg") || "__default__";
      if (current !== "__default__" && !list.includes(current)) current = "__default__";
      const pretty = f => f.replace(/\.(png|jpe?g|webp|gif|avif)$/i, "").replace(/[-_]/g, " ");
      const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
      // "generated" tile first, then a thumbnail per image (lazy-loaded; the tile
      // is dark so a transparent image composites to its true backdrop look)
      bgGrid.innerHTML =
        `<button class="bgtile gen${current === "__default__" ? " sel" : ""}" data-bg="__default__">
           <span class="bgthumb bggen"></span><span class="bglabel">generated</span></button>`
        + list.map(f =>
          `<button class="bgtile${current === f ? " sel" : ""}" data-bg="${esc(f)}">
             <img class="bgthumb" loading="lazy" src="${urlBase}${encodeURIComponent(f)}" alt="">
             <span class="bglabel">${esc(pretty(f))}</span></button>`).join("");
      const closeModal = () => { bgModal.className = ""; };
      const pick = choice => {
        current = choice;
        localStorage.setItem("topics-bg", choice);
        applyBackdrop(choice, urlBase);
        for (const t of bgGrid.children) t.classList.toggle("sel", t.dataset.bg === choice);
        closeModal();
      };
      bgOpen.style.display = "";
      bgOpen.addEventListener("click", () => { bgModal.className = "open"; });
      bgGrid.addEventListener("click", e => {
        const t = e.target.closest(".bgtile");
        if (t) pick(t.dataset.bg);
      });
      bgModal.querySelector(".bgclose").addEventListener("click", closeModal);
      bgModal.addEventListener("click", e => { if (e.target === bgModal) closeModal(); });
      addEventListener("keydown", e => {
        if (e.key === "Escape" && bgModal.classList.contains("open")) closeModal();
      });
      applyBackdrop(current, urlBase);
    })();
  }

  // validate the stored view (legacy shells stored a/b/c) - never boot into nothing
  const LEGACY = { a: "constellation", b: "lineage", c: "starchart" };
  let saved = localStorage.getItem("topics-view") || "starchart";
  saved = LEGACY[saved] || saved;
  if (!window.TopicsRenderers[saved]) saved = "starchart";
  core.load().then(() => show(saved));
})();
