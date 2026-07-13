/* WORKED EXAMPLE (copied verbatim from the birthplace instance, where it runs in
 * production against a live message board). See INTEGRATING.md for the contract
 * this file implements. */
/* adapter-board.js - the MESSAGE BOARD's storage adapter for the Topic Visualizer.
 * BOARD-SPECIFIC (not vendored): topics live as board posts with the OPEN THREAD title
 * prefix and a "parent: <slug>" body convention; states map onto post resolutions
 * (discussed = completed, pruned = discarded). The views never know any of this -
 * that is the adapter law (see the topic-visualizer plugin repo, the canonical source
 * for every other file in this folder). */
window.TopicsAdapter = (function () {
  "use strict";
  // the board's anti-CSRF check requires this exact value (its own app name)
  const HDRS = { "Content-Type": "application/json", "X-Requested-By": "messageboard" };
  // Set these to YOUR board's identity - nothing here is hardcoded to the plugin
  // author's setup. HUMAN = the author name your board uses for the person; PROJECT
  // defaults to "default" but REMEMBERS your last pick: an explicit ?project= wins (and is
  // remembered), else the last project (localStorage), else the default. The shell's dropdown
  // switches by navigating to ?project=, so this round-trip persists it across visits.
  const HUMAN = "you";
  const _urlProject = new URLSearchParams(location.search).get("project");
  const _remembered = (() => { try { return localStorage.getItem("topics-project"); } catch (e) { return null; } })();
  const PROJECT = _urlProject || _remembered || "default";
  try { localStorage.setItem("topics-project", PROJECT); } catch (e) {}

  return {
    name: "board",
    // OPTIONAL: a cheap change-signal for live refresh. The shell polls this on an interval and
    // re-loads only when it changes, so the tree never goes stale. Make it CHEAP - one record, not
    // the whole tree. Here: the board sorts posts updated-desc, so limit=1 gives the newest updated
    // + the total. Return null on error so the shell keeps the current view. Omit to opt out.
    async revision() {
      try {
        const j = await (await fetch(`/api/posts?project=${PROJECT}&type=topic&limit=1`)).json();
        const top = (j.items && j.items[0]) || {};
        return `${j.total || 0}:${top.updated || ""}`;
      } catch (e) { return null; }
    },
    // OPTIONAL: report your app's projects to drive the shell's project dropdown. Here
    // the board's project list comes from its own API; return {projects:[{key,label,
    // current}], current} or omit the method to hide the dropdown.
    async projects() {
      try {
        const r = await fetch("/api/issues");
        const list = ((await r.json()).projects) || [];
        if (PROJECT && list.indexOf(PROJECT) < 0) list.unshift(PROJECT);
        return { projects: list.map(p => ({ key: p, label: p, current: p === PROJECT })), current: PROJECT };
      } catch (e) { return null; }
    },
    async load(includeArchive) {
      // 0524: topics are their own post type; fetch the topic lane explicitly (the default board feed
      // excludes type='topic'). The OPEN THREAD title prefix stays only as a human-readable label.
      const r = await fetch(`/api/posts?project=${PROJECT}&type=topic`);
      const items = ((await r.json()).items || [])
        .filter(p => includeArchive || (p.resolve_kind || "") !== "discarded");
      // rediscoveries live as thread replies ("also-parent: <slug> | <note>") because
      // post bodies are immutable through the board API; only posts WITH replies pay
      // the extra fetch (message_count guards it)
      const threads = await Promise.all(items.map(async p => {
        if (!p.message_count) return [];
        try {
          const full = await (await fetch(`/api/post?slug=${encodeURIComponent(p.slug)}`)).json();
          const out = [];
          for (const th of full.threads || []) {
            for (const msg of th.messages || []) {
              for (const mm of (msg.body || "").matchAll(
                     /^also-parent:\s*([a-z0-9-]+)\s*(?:\|\s*(.*))?$/gmi)) {
                out.push({ slug: mm[1], note: (mm[2] || "").trim() });
              }
            }
          }
          return out;
        } catch (e) { return []; }
      }));
      return items.map((p, i) => {
        // MULTI-PARENT: every "parent:" body line counts - first is the primary
        // (layout spine), the rest + reply-attachments are extra avenues
        const parents = [...(p.body || "").matchAll(/^parent:\s*([a-z0-9-]+)/gmi)].map(m => m[1]);
        const discarded = (p.resolve_kind || "") === "discarded";
        return {
          // strip the storage-only "OPEN THREAD:" marker so the adapter's title matches
          // the MCP backend's (the view's short() then becomes a redundant safety net)
          slug: p.slug, title: (p.title || "").replace(/^OPEN THREAD:?\s*/i, ""),
          body: p.body, author: p.author,
          created: p.created, parentSlug: parents[0] || null,
          extraParents: parents.slice(1).map(s => ({ slug: s, note: "" })).concat(threads[i]),
          state: discarded ? "pruned"                       // archive ghost
               : String(p.status || "open") !== "open" ? "discussed"
               : (/^stage:\s*seedling/mi.test(p.body || "") ? "seedling" : "open"),
          critical: /^priority:\s*critical/mi.test(p.body || ""),
        };
      });
    },
    // no edit(): the board has no post-edit API, so the panel's Edit stays hidden
    // (capability detection in topics-core). Archive IS supported: discarded posts
    // surface as pruned ghosts and Resurrect maps onto /api/reopen below.
    // attach() = an "also-parent" reply (append-only, so no attachRemove).
    async attach(slug, parentSlug, note, actor, remove) {
      if (remove) return { error: "the board cannot detach an avenue (replies are append-only)" };
      const r = await fetch("/api/reply", { method: "POST", headers: HDRS,
        body: JSON.stringify({ slug, author: actor === "human" ? HUMAN : actor,
          body: `also-parent: ${parentSlug}` + (note ? ` | ${note}` : "") }) });
      return await r.json();
    },
    async setState(slug, state, actor, note) {
      const author = actor === "human" ? HUMAN : actor;
      const r = state === "open"
        ? await fetch("/api/reopen", { method: "POST", headers: HDRS,
            body: JSON.stringify({ slug, author }) })
        : await fetch("/api/post/resolve", { method: "POST", headers: HDRS,
            body: JSON.stringify({ slug, author, kind: "completed", note: note || "discussed" }) });
      const j = await r.json().catch(() => ({}));
      return (!r.ok || j.error) ? { error: j.error || `HTTP ${r.status}` } : j;   // surface, don't swallow
    },
    async create(items) {
      let err = null;
      for (const it of items) {
        const lines = [];
        if (it.parent_slug) lines.push(`parent: ${it.parent_slug}`);
        if (it.state === "seedling") lines.push("stage: seedling");
        const r = await fetch("/api/post", { method: "POST", headers: HDRS,
          body: JSON.stringify({ project: PROJECT, author: HUMAN,
            type: "topic",                                     // 0524: first-class topic lane (no `to`)
            title: `OPEN THREAD: ${it.title}`.slice(0, 200),   // most boards cap post titles
            body: (lines.length ? lines.join("\n") + "\n\n" : "") +
                  (it.body || "added via the topic tree quick-add") }) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok || j.error) err = j.error || `create failed (HTTP ${r.status})`;
      }
      return err ? { error: err } : { ok: true };
    },
    async prune(slugs, actor) {
      const author = actor === "human" ? HUMAN : actor;
      for (const slug of slugs) {
        const r = await fetch("/api/post/resolve", { method: "POST", headers: HDRS,
          body: JSON.stringify({ slug, author, kind: "discarded",
                                 note: "pruned from the topic tree" }) });
        const j = await r.json().catch(() => ({}));   // the shell surfaces res.error ("Prune refused")
        if (!r.ok || j.error) return { error: j.error || `prune failed for ${slug} (HTTP ${r.status})` };
      }
      return { ok: true };
    },
  };
})();
