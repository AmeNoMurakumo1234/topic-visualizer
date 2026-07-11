/* adapter-sqlite.js - the plugin's storage adapter: talks to the local topics server
 * (see ../server/README.md). The views never know the storage; this file is the only
 * place that does. CANONICAL SOURCE: the topic-visualizer plugin repo. */
window.TopicsAdapter = (function () {
  "use strict";
  const HDRS = { "Content-Type": "application/json", "X-Requested-By": "topic-visualizer" };

  return {
    name: "sqlite",
    async load(includeArchive) {
      const r = await fetch("/api/topics" + (includeArchive ? "?include=archive" : ""));
      const items = (await r.json()).topics || [];
      return items.map(t => ({
        slug: t.slug, title: t.title, body: t.body, author: t.created_by,
        created: t.created_at, parentSlug: t.parent_slug || null,
        extraParents: t.extra_parents || [],   // multi-parent DAG edges
        state: t.state,   // seedling | open | discussed | pruned | expired pass through
        critical: t.priority === "critical",
      }));
    },
    async edit(slug, fields, actor) {
      // fields: { title?, body?, parent_slug? ("" = to root), critical? }
      const r = await fetch(`/api/topics/${encodeURIComponent(slug)}/edit`, {
        method: "POST", headers: HDRS,
        body: JSON.stringify({ ...fields, actor }),
      });
      return await r.json();
    },
    attachRemove: true,   // this store can detach an extra avenue
    async attach(slug, parentSlug, note, actor, remove) {
      const r = await fetch(`/api/topics/${encodeURIComponent(slug)}/attach`, {
        method: "POST", headers: HDRS,
        body: JSON.stringify({ parent_slug: parentSlug, note, actor, remove: !!remove }),
      });
      return await r.json();
    },
    async setState(slug, state, actor, note) {
      const r = await fetch(`/api/topics/${encodeURIComponent(slug)}/state`, {
        method: "POST", headers: HDRS,
        body: JSON.stringify({ state, actor, note }),
      });
      return await r.json();
    },
    async create(items) {
      const r = await fetch("/api/topics", { method: "POST", headers: HDRS,
        body: JSON.stringify({ actor: "human", topics: items }) });
      return await r.json();
    },
    async search(q) {
      const r = await fetch(`/api/topics/search?q=${encodeURIComponent(q)}`);
      return (await r.json()).results || [];
    },
    async health() {
      const r = await fetch("/api/topics/health");
      return await r.json();
    },
    async prune(slugs, actor) {
      // client-confirmed, server-verified cascade (see server spec): send the subtree
      // the human saw in the consequence dialog; the server checks it still matches.
      const r = await fetch(`/api/topics/${encodeURIComponent(slugs[0])}/state`, {
        method: "POST", headers: HDRS,
        body: JSON.stringify({ state: "pruned", actor, cascade: slugs,
                               note: "pruned from the topic tree" }),
      });
      return await r.json();   // the TOCTOU refusal must reach the human
    },
  };
})();
