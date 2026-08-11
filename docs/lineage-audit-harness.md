# Lineage-view audit harness (geometry invariants + a seeded monkey storm)

Built 2026-08-11 for the 0.55.0 lineage audit; kept because the repo has NO JS test tier
(front-end logic lives in IIFEs and is verified ad hoc - a known, filed gap). Until that
changes, this is the repeatable check for lineage layout work: run it before and after any
change to `render-lineage.js`. It found the filter-blind label family in minutes and then
cleared the geometry across 470 randomized steps on three trees - including a copy of a real
389-topic store - which is a stronger statement than any hand-clicked spot check.

## Setup

1. Dev server from the repo (never audit the installed copy - it serves stale code):

       python plugin/server/server.py --db <scratch>/fixture.db --port 8999

2. Fixture trees. Capture over HTTP (`POST /api/topics`, then `/api/topics/<slug>/state`).
   The shapes that matter, learned the hard way:
   - a DISCUSSED root holding a live child (must stay visible under the filter)
   - a discussed root with only discussed children (whole subtree must hide)
   - an open parent whose children mix: open, discussed-leaf, discussed-with-live-grandchild
   - a node whose EVERY child is filterable (the caret-that-does-nothing shape)
   - a chain 5+ deep with a discussed node mid-chain and live below
   - a >7-child hub AND >35 total nodes (big-tree defaults: FANCAP, shallow-open)
   - long titles (variable measured heights - the layout is measured, not fixed-row)
   - a critical node buried >=2 deep (exercises the reveal-path pass)
   To audit against REAL data: file-copy any store into `<scratch>/projects/<name>.db` and
   open `?project=<name>`. Reads are safe; the copy keeps the real store untouched.

## The invariant checker (paste into the browser console)

Three rules, and the reasoning that keeps them honest:

- **OVERLAP**: two cards in one column intersecting. Always a bug.
- **CROWD**: same-column gap under 10px (GY is 18). Always a bug.
- **TRUE-DEADSPACE**: a vertical band >=120px covered by NO card in ANY column. The naive
  version - gaps between same-column neighbors - fires on legitimate layout: a root-column gap
  spanned by the previous root's deep subtree is the tidy tree working. First version of this
  checker made exactly that mistake and reported 18 phantom problems; charge the instrument
  before charging the code.

```js
window.__auditStrict = (label) => {
  const cards = [...document.querySelectorAll('.tnode')].map(d => ({
    t: d.querySelector('.sum').textContent.trim().slice(0, 24),
    x: parseFloat(d.style.left), y: parseFloat(d.style.top), h: d.offsetHeight }));
  const problems = [];
  const cols = {};
  for (const c of cards) (cols[c.x] = cols[c.x] || []).push(c);
  for (const [x, list] of Object.entries(cols)) {
    list.sort((a, b) => a.y - b.y);
    for (let i = 1; i < list.length; i++) {
      const gap = list[i].y - (list[i-1].y + list[i-1].h);
      if (gap < 0) problems.push(`${label}: OVERLAP col${x} "${list[i-1].t}"/"${list[i].t}" ${(-gap).toFixed(1)}px`);
      else if (gap < 10) problems.push(`${label}: CROWD col${x} gap=${gap.toFixed(1)}`);
    }
  }
  const ivs = cards.map(c => [c.y, c.y + c.h]).sort((a, b) => a[0] - b[0]);
  let coveredTo = ivs.length ? ivs[0][1] : 0;
  for (const [a, b] of ivs.slice(1)) {
    if (a - coveredTo >= 120) problems.push(`${label}: TRUE-DEADSPACE ${(a - coveredTo).toFixed(0)}px at y=${coveredTo.toFixed(0)}`);
    coveredTo = Math.max(coveredTo, b);
  }
  return problems;
};
```

## The storm (seeded, so a failure is REPRODUCIBLE)

Random carets, filter flips, panel reveals/hides, toolbar ops - audit after EVERY step. An
unreproducible monkey test is a rumor: keep the seed, and when a step fails, replay the same
seed and bisect the step count.

```js
(() => {
  let seed = 31415926;                       // change per run; RECORD it with any failure
  const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
  const step = () => {
    const dice = rnd();
    if (dice < 0.42) { const cs = [...document.querySelectorAll('.caret')];
      if (cs.length) { cs[Math.floor(rnd() * cs.length)].click(); return 'caret'; } }
    else if (dice < 0.56) { const box = document.querySelector('.hide-discussed-tgl input');
      box.checked = !box.checked; box.dispatchEvent(new Event('change', { bubbles: true }));
      return 'tgl'; }
    else if (dice < 0.74) { const cards = [...document.querySelectorAll('.tnode')];
      if (cards.length) { cards[Math.floor(rnd() * cards.length)].click();
        const btns = [...document.querySelectorAll('button')].filter(b => /^(Show |Hide this|Expand all|Collapse all)/.test(b.textContent));
        if (btns.length) { btns[Math.floor(rnd() * btns.length)].click(); return 'panel'; }
        return 'sel'; } }
    else { const bs = [...document.querySelectorAll('.tv-expandbar button')];
      const b = bs[Math.floor(rnd() * bs.length)]; b.click(); return b.textContent.slice(0, 8); }
    return 'noop';
  };
  return new Promise(resolve => {
    const found = []; let i = 0;
    setTimeout(function tick() {
      if (i >= 200) { resolve({ steps: i, problemCount: found.length, problems: found.slice(0, 15) }); return; }
      const act = step();
      setTimeout(() => { found.push(...window.__auditStrict(`s${i}:${act}`)); i++; tick(); }, 100);
    }, 900);
  }).then(r => JSON.stringify(r));
})()
```

## Beyond geometry: the honesty checks

Geometry passing is HALF the audit. The 0.55.0 defect family was cards whose LABELS described
a different tree than the layout drew (raw-children counts under an active filter). After any
change, also verify by hand in the hostile fixture, filter ON:

- a discussed root with one live + one discussed child reads "1 child(ren) - 1 filtered"
- a node whose every child is filtered reads "N filtered" and shows NO caret
- "Show discussed (N)": N equals the number of cards that actually appear on click
- flip the filter both ways and re-check - labels must track, not lag

## Run record

| date | code | trees | steps | result |
|---|---|---|---|---|
| 2026-08-11 | 0.55.0 pre-ship | hostile 18-node / big 49-node / real 389-topic copy | 120+150+200 | 0 geometry violations; label family found and fixed |
