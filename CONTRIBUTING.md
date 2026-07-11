# Contributing

This repo is maintained by the Quantum Concepts agent team (the same family that
maintains the Mind Coherence Suite), with the owner as final arbiter of taste and
scope. The working method that built it is the one we recommend for changing it:

- **Design by reaction, not specification.** For anything visual: build two real,
  running variants with real (or demo) data and let a human react. Reactions to
  artifacts beat blank-page spec questions every time - this whole plugin was designed
  in four reaction rounds in one day.
- **The CHARTER is load-bearing.** Changes that grow the store's importance at the
  expense of the serving ritual will be declined on principle - a garden, not an
  archive. Read [CHARTER.md](CHARTER.md) before proposing features.
- **ASCII-first** in every file (prose punctuation: no em-dashes, curly quotes,
  ellipsis characters). Keep bodies of text tool-safe.
- **The adapter law**: views never know the storage. Anything that couples a renderer
  to SQLite (or any specific backend) will be declined.
- Conventional commits; every fix that came from a real defect lands with the durable
  guard that prevents its recurrence (a check, a test, a stated rule).

Issues and ideas: file them - or better, capture them as topics in your own tree and
bring the card when it's served to you. Dogfood is the house wine.
