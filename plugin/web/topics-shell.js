/* topics-shell.js - boot + orchestration: one data load, three switchable renderers.
 * CANONICAL SOURCE: the topic-visualizer plugin repo. Vendored copies: do not edit. */
(function () {
  "use strict";
  const params = new URLSearchParams(location.search);
  const demo = parseInt(params.get("demo") || "0", 10) || 0;

  // Cross-app back-link (the "Link" integration mode - INTEGRATING.md mode B). When a host
  // app opens us with ?return=<url>&return_label=<name>, render a "back to <name>" link so the
  // user can get home. App-agnostic + STATELESS: the host is described entirely by the query
  // params and we hold zero config about it, so any number of apps can link the same visualizer
  // without collision. Only http/https hrefs are honored (never javascript:/data:), and it is a
  // click-through the user chooses, never an auto-redirect - so it is not an open-redirect vector.
  (function mountReturnLink() {
    const raw = params.get("return");
    if (!raw) return;
    let href;
    try {
      const u = new URL(raw, location.href);
      if (u.protocol !== "http:" && u.protocol !== "https:") return;
      href = u.href;
    } catch (e) { return; }
    let label = (params.get("return_label") || "").trim();
    if (!label) { try { label = new URL(href).host; } catch (e) { label = "back"; } }
    const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                              .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    const a = document.createElement("a");
    a.className = "returnlink";
    a.href = href;
    a.rel = "noopener";
    a.title = "back to " + label;
    a.innerHTML = '<span aria-hidden="true">&#8592;</span> ' + esc(label);
    (document.querySelector("header") || document.body).insertAdjacentElement("afterbegin", a);
  })();

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
    // 0.44.2 (audit MEDIUM): the Projects tab is demo-gated at injection, but the
    // boot-time stored-view restore was not - a session whose last view was Projects
    // booted ?demo= straight into the REAL management page (live trash/delete against
    // real stores inside a session the README promises never touches a database).
    // Gate the VIEW, not just the tab, so no path reaches it in demo.
    if (demo && name === "projects") name = "starchart";
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

  // 0.44: the Projects management tab, injected ONLY when the adapter can manage stores
  // (capability-gated, so the board page - whose adapter has no sqlite stores - never
  // shows it and vendored host pages need no HTML change).
  if (window.TopicsAdapter.projectsAdmin && window.TopicsRenderers.projects && !demo) {
    const pb = document.createElement("button");
    pb.dataset.v = "projects";
    pb.textContent = "Projects";
    pb.title = "manage the project boards: copy topics between boards, trash/restore, " +
               "hard-delete empty bogus boards";
    document.getElementById("viewtabs").appendChild(pb);
  }

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

  // --- live refresh --------------------------------------------------------------------------
  // A visual that is 2 hours stale lies. So we poll a CHEAP change-signal (adapter.revision() - one
  // record, NOT the tree) and only re-load when topics actually change; core.load() re-renders in
  // place, preserving the camera. A burst is COALESCED (refresh once the signal settles, not per
  // mutation). A manual button forces it now; a toggle pauses the poll (persisted). Adapters that
  // predate revision() simply opt out - no button, old behavior.
  function setupLiveRefresh() {
    const adapter = window.TopicsAdapter;
    if (demo || typeof adapter.revision !== "function") return;
    const POLL_MS = 12000;
    let renderedRev = null, pendingRev = null, timer = null, busy = false;

    // inject the controls into the header (works across host pages; no host HTML edit needed)
    const host = document.querySelector("header") || document.body;
    const box = document.createElement("div");
    box.className = "hgroup hrefresh";
    box.style.cssText = "display:flex;align-items:center;gap:8px;margin-left:8px";
    box.innerHTML =
      '<button id="refreshnow" title="Reload the topic tree now" style="cursor:pointer;' +
      'background:none;border:1px solid currentColor;border-radius:4px;color:inherit;font:inherit;' +
      'padding:2px 8px;opacity:.7">↻</button>' +
      '<label title="Auto-refresh when topics change" style="display:flex;align-items:center;gap:4px;' +
      'cursor:pointer;opacity:.7;font-size:12px"><input type="checkbox" id="autorefresh"> live</label>' +
      '<span id="refreshstatus" style="font-size:11px;opacity:.55;min-width:52px"></span>';
    host.appendChild(box);
    const btn = box.querySelector("#refreshnow");
    const chk = box.querySelector("#autorefresh");
    const status = box.querySelector("#refreshstatus");

    let flashTimer = null;
    function idle() { return chk.checked ? "live" : "paused"; }
    function flash(msg, sticky) {
      status.textContent = msg;
      clearTimeout(flashTimer);
      if (!sticky) flashTimer = setTimeout(() => { status.textContent = idle(); }, 2500);
    }
    async function refreshNow() {
      if (busy) return;
      busy = true;
      try {
        const rev = await adapter.revision();
        await core.load();
        if (rev != null) renderedRev = pendingRev = rev;
        flash("updated");
      } catch (e) { /* keep the current view; the next tick retries */ }
      finally { busy = false; }
    }
    async function poll() {
      if (busy) return;
      let rev;
      try { rev = await adapter.revision(); } catch (e) { return; }
      if (rev == null) return;                       // could not check - keep the current view
      if (renderedRev === null) { renderedRev = pendingRev = rev; return; }   // baseline
      if (rev === renderedRev) { pendingRev = rev; return; }   // nothing new since last render
      if (rev !== pendingRev) { pendingRev = rev; return; }    // still moving - wait for it to settle
      await refreshNow();                            // settled AND differs from rendered -> refresh once
    }
    function start() { stop(); timer = setInterval(poll, POLL_MS); }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }

    // seed the baseline from the just-loaded state so the first poll never spuriously refreshes
    adapter.revision().then(r => { renderedRev = pendingRev = r; }).catch(() => {});

    const on = localStorage.getItem("topics-autorefresh") !== "off";
    chk.checked = on;
    status.textContent = idle();
    if (on) start();
    chk.addEventListener("change", () => {
      localStorage.setItem("topics-autorefresh", chk.checked ? "on" : "off");
      if (chk.checked) { status.textContent = "live"; start(); } else { stop(); status.textContent = "paused"; }
    });
    btn.addEventListener("click", () => { flash("…", true); refreshNow(); });
  }

  // --- degraded-state banner --------------------------------------------------------------------
  // The product must ANNOUNCE when it is running at half value (semantic ranking off, or the server
  // not persisting) instead of silently degrading - the core onboarding fix. adapter.doctor() returns
  // {degraded:[...]}; a non-empty list raises a visible red strip. Adapters without doctor() (or a
  // healthy store) show nothing.
  async function checkDoctor() {
    const adapter = window.TopicsAdapter;
    if (demo || typeof adapter.doctor !== "function") return;
    let d;
    try { d = await adapter.doctor(); } catch (e) { return; }
    if (!d || !Array.isArray(d.degraded) || !d.degraded.length) return;
    const bar = document.createElement("div");
    bar.style.cssText = "padding:7px 14px;background:#7a1f1f;color:#ffecec;font-size:12px;" +
      "line-height:1.45;display:flex;gap:10px;align-items:flex-start;border-bottom:1px solid #a33";
    const msg = document.createElement("div");
    msg.style.flex = "1";
    msg.innerHTML = "<b>⚠ Running degraded — not at full value.</b> " +
      d.degraded.map(x => String(x)).join("<br>");
    const x = document.createElement("button");
    x.textContent = "×"; x.title = "dismiss (re-checks on reload)";
    x.style.cssText = "background:none;border:none;color:inherit;font-size:16px;cursor:pointer;opacity:.8";
    x.addEventListener("click", () => bar.remove());
    bar.append(msg, x);
    (document.querySelector("header") || document.body).insertAdjacentElement("afterend", bar);
  }

  // --- "Undo last groom" --------------------------------------------------------------------
  // One deterministic rollback to the checkpoint taken before the last groom. Capability-gated on
  // adapter.restore() (sqlite backend only; the board adapter omits it, so no button appears).
  // The rollback is a RECONCILE: reparents/merges reverse, but anything captured since is KEPT.
  function setupGroomUndo() {
    const adapter = window.TopicsAdapter;
    if (demo || typeof adapter.restore !== "function") return;
    const host = document.querySelector("header") || document.body;
    const box = document.createElement("div");
    box.className = "hgroup hundo";
    box.style.cssText = "display:flex;align-items:center;margin-left:8px";
    box.innerHTML = '<button id="undogroom" title="Roll the tree back to the checkpoint taken '
      + 'before the last groom (anything captured since is kept)" style="cursor:pointer;'
      + 'background:none;border:1px solid currentColor;border-radius:4px;color:inherit;font:inherit;'
      + 'padding:2px 8px;opacity:.7">⟲ Undo last groom</button>';
    host.appendChild(box);
    const modal = document.getElementById("confirm"), cbox = document.getElementById("confirmBox");
    const esc = core.esc || (s => String(s));
    const close = () => { modal.className = ""; };
    box.querySelector("#undogroom").addEventListener("click", async () => {
      const data = await adapter.checkpoints();
      // skip safety checkpoints (auto=1, taken before a restore) so "Undo last groom" targets the
      // last real GROOM, not the pre-restore snapshot (structural flag, not a stringly label match)
      const cps = ((data && data.checkpoints) || []).filter(c => !c.auto);
      if (!cps.length) {
        cbox.innerHTML = "<h3>Nothing to undo</h3><p>No groom checkpoint has been recorded for "
          + "this project yet — one is created at the start of a groom.</p><button class='no'>OK</button>";
        modal.className = "open"; cbox.querySelector(".no").onclick = close; return;
      }
      const latest = cps[0];
      const when = (latest.created_at || "").replace("T", " ").slice(0, 16);
      cbox.innerHTML = "<h3>Undo last groom?</h3>"
        + `<p>Roll the tree back to the checkpoint from <b>${esc(when)}</b>`
        + (latest.label ? ` (&ldquo;${esc(latest.label)}&rdquo;)` : "")
        + ` — a snapshot of ${latest.topics} topic(s).</p>`
        + "<p style='opacity:.8'>Reparents and merges since then are reversed. "
        + "<b>Anything captured during the groom is kept</b> — nothing is deleted.</p>"
        + "<button class='go'>Undo the groom</button><button class='no'>Cancel</button>";
      modal.className = "open";
      cbox.querySelector(".no").onclick = close;
      cbox.querySelector(".go").onclick = async () => {
        const res = await adapter.restore(latest.id, "human");   // the checkpoint we SHOWED, not "newest"
        close();
        await core.load();
        cbox.innerHTML = (res && res.ok)
          ? "<h3>Groom undone</h3><p>" + `${res.reverted} topic(s) restored to the checkpoint`
            + (res.preserved_since ? `; <b>${res.preserved_since} captured since were kept</b>` : "")
            + (res.recovered ? `; ${res.recovered} recovered` : "")
            + (res.removed_hubs ? `; ${res.removed_hubs} empty hub(s) swept` : "")
            + ".</p><button class='no'>OK</button>"
          : "<h3>Undo failed</h3><p>" + esc((res && res.error) || "could not reach the store")
            + "</p><button class='no'>OK</button>";
        modal.className = "open"; cbox.querySelector(".no").onclick = close;
      };
    });
  }

  // validate the stored view (legacy shells stored a/b/c) - never boot into nothing
  const LEGACY = { a: "constellation", b: "lineage", c: "starchart" };
  let saved = localStorage.getItem("topics-view") || "starchart";
  saved = LEGACY[saved] || saved;
  if (!window.TopicsRenderers[saved]) saved = "starchart";
  core.load().then(() => { show(saved); setupLiveRefresh(); setupGroomUndo(); checkDoctor(); });
})();
