/* adapter-sqlite.js - the plugin's storage adapter: talks to the local topics server
 * (see ../server/README.md). The views never know the storage; this file is the only
 * place that does. CANONICAL SOURCE: the topic-visualizer plugin repo. */
window.TopicsAdapter = (function () {
  "use strict";
  const HDRS = { "Content-Type": "application/json", "X-Requested-By": "topic-visualizer" };
  // the project this page is scoped to. Resolution REMEMBERS your last pick: an explicit
  // ?project= wins (and is remembered); else the last project you were on (localStorage); else
  // "" (the server auto-detects from its own cwd). Only a real, non-empty project is remembered.
  // Threaded onto every call so the dropdown can switch stores; the dropdown switches by
  // navigating to ?project=, so this one round-trip is all the persistence needed.
  const _urlProject = new URLSearchParams(location.search).get("project");
  const _remembered = (() => { try { return localStorage.getItem("topics-project"); } catch (e) { return null; } })();
  const PROJECT = _urlProject || _remembered || "";
  if (PROJECT) { try { localStorage.setItem("topics-project", PROJECT); } catch (e) {} }
  const q = u => PROJECT ? u + (u.indexOf("?") >= 0 ? "&" : "?") + "project=" + encodeURIComponent(PROJECT) : u;

  return {
    name: "sqlite",
    // the projects the local machine offers (Claude projects + existing stores); drives
    // the shell's project dropdown. Omitted-gracefully if the server predates /api/projects.
    async projects() {
      try {
        const r = await fetch(q("/api/projects"));
        if (!r.ok) return null;
        return await r.json();   // { projects: [{key,label,current}], current }
      } catch (e) { return null; }
    },
    async load(includeArchive) {
      const r = await fetch(q("/api/topics" + (includeArchive ? "?include=archive" : "")));
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
      const r = await fetch(q(`/api/topics/${encodeURIComponent(slug)}/edit`), {
        method: "POST", headers: HDRS,
        body: JSON.stringify({ ...fields, actor }),
      });
      return await r.json();
    },
    attachRemove: true,   // this store can detach an extra avenue
    async attach(slug, parentSlug, note, actor, remove) {
      const r = await fetch(q(`/api/topics/${encodeURIComponent(slug)}/attach`), {
        method: "POST", headers: HDRS,
        body: JSON.stringify({ parent_slug: parentSlug, note, actor, remove: !!remove }),
      });
      return await r.json();
    },
    async setState(slug, state, actor, note) {
      const r = await fetch(q(`/api/topics/${encodeURIComponent(slug)}/state`), {
        method: "POST", headers: HDRS,
        body: JSON.stringify({ state, actor, note }),
      });
      return await r.json();
    },
    async create(items) {
      const r = await fetch(q("/api/topics"), { method: "POST", headers: HDRS,
        body: JSON.stringify({ actor: "human", topics: items }) });
      return await r.json();
    },
    async search(query) {
      const r = await fetch(q(`/api/topics/search?q=${encodeURIComponent(query)}`));
      return (await r.json()).results || [];
    },
    async health() {
      const r = await fetch(q("/api/topics/health"));
      return await r.json();
    },
    // background scenes: filenames in the plugin's backgrounds/ folder, served at
    // /backgrounds/<name>. Empty list -> the shell keeps the generated canvas.
    async backgrounds() {
      try {
        const r = await fetch("/api/backgrounds");
        return { list: (await r.json()).backgrounds || [], urlBase: "/backgrounds/" };
      } catch (e) { return { list: [], urlBase: "/backgrounds/" }; }
    },
    async prune(slugs, actor) {
      // client-confirmed, server-verified cascade (see server spec): send the subtree
      // the human saw in the consequence dialog; the server checks it still matches.
      const r = await fetch(q(`/api/topics/${encodeURIComponent(slugs[0])}/state`), {
        method: "POST", headers: HDRS,
        body: JSON.stringify({ state: "pruned", actor, cascade: slugs,
                               note: "pruned from the topic tree" }),
      });
      return await r.json();   // the TOCTOU refusal must reach the human
    },
  };
})();
