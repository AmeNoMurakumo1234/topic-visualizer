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
  // defaults to "default" but the shell's project dropdown drives it at runtime.
  const HUMAN = "you";
  const PROJECT = new URLSearchParams(location.search).get("project") || "default";

  return {
    name: "board",
    async load(includeArchive) {
      const r = await fetch(`/api/posts?project=${PROJECT}`);
      const items = ((await r.json()).items || [])
        .filter(p => /^OPEN THREAD/i.test(p.title || ""))
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
          slug: p.slug, title: p.title, body: p.body, author: p.author,
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
      if (state === "open") {
        await fetch("/api/reopen", { method: "POST", headers: HDRS,
          body: JSON.stringify({ slug, author: actor === "human" ? HUMAN : actor }) });
      } else {
        await fetch("/api/post/resolve", { method: "POST", headers: HDRS,
          body: JSON.stringify({ slug, author: actor === "human" ? HUMAN : actor,
                                 kind: "completed", note: note || "discussed" }) });
      }
    },
    async create(items) {
      for (const it of items) {
        const lines = [];
        if (it.parent_slug) lines.push(`parent: ${it.parent_slug}`);
        if (it.state === "seedling") lines.push("stage: seedling");
        await fetch("/api/post", { method: "POST", headers: HDRS,
          body: JSON.stringify({ project: PROJECT, author: HUMAN,
            type: "proposal", to: HUMAN,
            title: `OPEN THREAD: ${it.title}`,
            body: (lines.length ? lines.join("\n") + "\n\n" : "") +
                  (it.body || "added via the topic tree quick-add") }) });
      }
    },
    async prune(slugs, actor) {
      for (const slug of slugs) {
        await fetch("/api/post/resolve", { method: "POST", headers: HDRS,
          body: JSON.stringify({ slug, author: actor === "human" ? HUMAN : actor,
                                 kind: "discarded",
                                 note: "pruned from the topic tree" }) });
      }
    },
  };
})();
