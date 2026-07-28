#!/usr/bin/env python3
"""Capture-time auto-file (0.46).

WHY THIS EXISTS. Measured on the real QC store 2026-07-27: 238 captures in 14 days (17/day, peaks of
38) with roughly half landing at ROOT, so the tree grew ~8-9 un-nested leaf topics a day and a groom
to zero was back over 40 within a week. The owner's read was "something is un-grooming the tree"; the
reparent log said otherwise - ZERO topics had been filed and then returned to root. It is arithmetic,
not a bug, and no manual cadence beats it when one human is the bottleneck. So the hub match that
_root_orphan_hints already ran at GROOM time now also runs at CAPTURE.

The risk being managed: the topics skill is explicit that similarity PROPOSES and judgment DECIDES,
and an autonomous similarity-only regroup is worse than no grooming. Auto-file is therefore bounded -
a higher bar than a hint, never over an explicit parent, never for a hub, off by one env var, and
every placement STAMPED so it stays visible as a guess and the threshold can be re-tuned on counted
evidence rather than taste.

    python server/test_autofile.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db, self._conn, self._embed = server.DB_PATH, server._conn, server._embed
        self._on, self._thr = server.AUTOFILE_ON, server.AUTOFILE_THRESHOLD
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)
        server.AUTOFILE_ON = True
        # PIN the threshold for the tests instead of inheriting the shipped default. The default is
        # calibrated against a live embedder and WILL be re-tuned from the verify queue's hit rate;
        # a suite that moves with it would silently stop testing the boundary it claims to test.
        server.AUTOFILE_THRESHOLD = 0.60

    def tearDown(self):
        try:
            server._conn.close()
        except Exception:
            pass
        server.DB_PATH, server._conn, server._embed = self._db, self._conn, self._embed
        server.AUTOFILE_ON, server.AUTOFILE_THRESHOLD = self._on, self._thr
        self.tmp.cleanup()

    # A FAKE embedder, so the tests assert the PLACEMENT LOGIC and never the model's taste.
    # Vectors are hand-set per text fragment; cosine then falls out deterministically.
    def _fake_embed(self, mapping, default=(0.0, 0.0, 1.0)):
        def fake(texts):
            out = []
            for t in texts:
                vec = default
                for frag, v in mapping.items():
                    if frag.lower() in t.lower():
                        vec = v
                        break
                out.append(list(vec))
            return out
        server._embed = fake

    def _hub(self, title):
        """A hub is a live topic with >= 2 live children - mint it with two."""
        h = server.add_topics([{"title": title, "state": "open", "role": "hub"}], "test")[0]["slug"]
        for i in range(2):
            server.add_topics([{"title": f"{title} child {i}", "parent_slug": h, "state": "open"}],
                              "test")
        return h

    def _parent_of(self, slug):
        r = server._conn.execute(
            "SELECT p.slug AS p FROM topic t LEFT JOIN topic p ON p.id=t.parent_id "
            "WHERE t.slug=?", (slug,)).fetchone()
        return r["p"] if r else None

    def _events(self, slug):
        return [r["event"] for r in server._conn.execute(
            "SELECT e.event FROM topic_event e JOIN topic t ON t.id=e.topic_id WHERE t.slug=? "
            "ORDER BY e.id", (slug,))]


class AutoFile(Base):
    def test_01_a_strong_match_is_filed_not_left_at_root(self):
        """The whole point: a capture that clearly belongs somewhere stops landing at root."""
        hub = self._hub("Guards and gates")
        self._fake_embed({"guards and gates": (1.0, 0.0, 0.0), "guard": (0.98, 0.2, 0.0)})
        r = server.add_topics([{"title": "guard cannot fail", "autofile": True}], "Vera")[0]
        self.assertEqual(self._parent_of(r["slug"]), hub, "a strong match must be FILED, not rooted")
        self.assertEqual(r.get("auto_filed"), hub)
        self.assertTrue(r["suggested_parent"]["filed"])
        self.assertGreaterEqual(r["suggested_parent"]["score"], server.AUTOFILE_THRESHOLD)

    def test_02_a_weak_match_is_suggested_but_NOT_filed(self):
        """The calibration case. On the real store the only 0.457 hint was WRONG, so a middling score
        must surface as a proposal and leave the topic at root rather than mis-file it silently."""
        self._hub("Guards and gates")
        self._fake_embed({"guards and gates": (1.0, 0.0, 0.0), "middling": (0.5, 0.87, 0.0)})
        r = server.add_topics([{"title": "middling relevance capture", "autofile": True}], "Vera")[0]
        self.assertIsNone(self._parent_of(r["slug"]), "a weak match must stay at ROOT")
        self.assertFalse(r["suggested_parent"]["filed"])
        self.assertLess(r["suggested_parent"]["score"], server.AUTOFILE_THRESHOLD)
        self.assertNotIn("auto_filed", self._events(r["slug"]), "no placement means no stamp")
        self.assertNotIn("auto_filed", r)

    def test_02b_a_caller_that_did_NOT_opt_in_is_never_filed(self):
        """The opt-in contract itself, and the gap mutation control found: every other test passes
        autofile=True, so 'want_file = True' survived every one of them. add_topics is also how hubs
        get minted, how imports land and how fixtures are built - those callers said where the topic
        goes and must be obeyed. Only the capture door opts in."""
        hub = self._hub("Guards and gates")
        self._fake_embed({"guards and gates": (1.0, 0.0, 0.0), "guard": (1.0, 0.0, 0.0)})
        r = server.add_topics([{"title": "guard cannot fail"}], "Vera")[0]      # no autofile flag
        self.assertIsNone(self._parent_of(r["slug"]),
                          "a structural caller must land exactly where it said - at root")
        self.assertNotIn("auto_filed", self._events(r["slug"]))
        self.assertEqual(r["suggested_parent"]["slug"], hub,
                         "the PROPOSAL still comes back - proposing costs nothing, only placing does")
        self.assertFalse(r["suggested_parent"]["filed"])

    def test_03_an_explicit_parent_always_wins(self):
        """Caller judgment is never overridden, even by a perfect score elsewhere."""
        strong = self._hub("Guards and gates")
        chosen = self._hub("Somewhere else entirely")
        self._fake_embed({"guards and gates": (1.0, 0.0, 0.0), "guard": (1.0, 0.0, 0.0)})
        r = server.add_topics([{"title": "guard thing", "parent_slug": chosen, "autofile": True}], "Vera")[0]
        self.assertEqual(self._parent_of(r["slug"]), chosen)
        self.assertNotEqual(self._parent_of(r["slug"]), strong)
        self.assertNotIn("suggested_parent", r, "no suggestion is computed when the caller chose")

    def test_04_a_hub_being_minted_is_never_auto_filed(self):
        """A groom mints hubs; a hub IS the structure and must not be buried under a sibling."""
        self._hub("Guards and gates")
        self._fake_embed({"guards": (1.0, 0.0, 0.0)})
        r = server.add_topics([{"title": "Guards, deeper cut", "role": "hub", "state": "open", "autofile": True}],
                              "Vera")[0]
        self.assertIsNone(self._parent_of(r["slug"]), "a minted hub stays where the groom put it")

    def test_05_embedder_down_means_no_suggestion_and_no_placement(self):
        """Fail toward an honest root landing. A keyword guess would mis-file INVISIBLY, which is
        strictly worse than a visible pile - the same reasoning root_orphan_hints already uses."""
        self._hub("Guards and gates")
        server._embed = lambda texts: None
        r = server.add_topics([{"title": "guard cannot fail", "autofile": True}], "Vera")[0]
        self.assertIsNone(self._parent_of(r["slug"]))
        self.assertNotIn("suggested_parent", r)

    def test_05b_the_suggester_itself_reports_embedder_down(self):
        """Tested at _suggest_hub directly, because add_topics wraps it in a catch-all that a capture
        needs but that also MASKS the difference between 'declined honestly' and 'threw'. Mutation
        control caught that: deleting the None-check survived the end-to-end test, since the exception
        it caused was swallowed into the same no-placement outcome."""
        self._hub("Guards and gates")
        server._embed = lambda texts: None
        hub, why = server._suggest_hub("guard cannot fail", "")
        self.assertIsNone(hub)
        self.assertIn("embedder", why.lower(),
                      "the reason must name the embedder, not read as 'no match'")

    def test_06_no_hubs_yet_means_no_placement(self):
        """A young tree has nothing to file under; capture must still work."""
        self._fake_embed({"anything": (1.0, 0.0, 0.0)})
        r = server.add_topics([{"title": "anything at all", "autofile": True}], "Vera")[0]
        self.assertIsNone(self._parent_of(r["slug"]))
        self.assertTrue(r["slug"])

    def test_07_the_kill_switch_makes_it_suggest_only(self):
        hub = self._hub("Guards and gates")
        self._fake_embed({"guards and gates": (1.0, 0.0, 0.0), "guard": (1.0, 0.0, 0.0)})
        server.AUTOFILE_ON = False
        r = server.add_topics([{"title": "guard cannot fail", "autofile": True}], "Vera")[0]
        self.assertIsNone(self._parent_of(r["slug"]), "off means SUGGEST, never place")
        self.assertFalse(r["suggested_parent"]["filed"])
        self.assertEqual(r["suggested_parent"]["slug"], hub, "the proposal still reaches the caller")

    def test_08_a_suggester_crash_never_kills_the_capture(self):
        """Capture is the one path that must not fail: a lost idea is unrecoverable, an unfiled one
        is merely untidy."""
        self._hub("Guards and gates")

        def boom(texts):
            raise RuntimeError("embedder exploded")
        server._embed = boom
        r = server.add_topics([{"title": "still must be stored", "autofile": True}], "Vera")[0]
        self.assertTrue(r.get("slug"), "the topic is STORED even when the suggester dies")
        self.assertIsNone(self._parent_of(r["slug"]))

    def test_08b_a_PARTIAL_embedder_response_degrades_to_unavailable(self):
        """The reachable version of test_08, found by writing it. _embed catches HTTP faults, so it
        never raises on a dead service - but a service answering with FEWER vectors than inputs used
        to slip past: zip() truncated, the tail never cached, and the final comprehension raised
        KeyError out of _embed into callers that handle None and never expected a throw. A short count
        is unavailability, so it now returns None like every other failure."""
        server._embed_cache.clear()
        real_urlopen = server.urllib.request.urlopen

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                # two inputs requested, ONE embedding returned
                return server.json.dumps({"data": [{"embedding": [1.0, 0.0, 0.0]}]}).encode()

        server.urllib.request.urlopen = lambda *a, **k: _Resp()
        try:
            server.EMBED_URL = server.EMBED_URL or "http://127.0.0.1:9"
            server._embed_up = None
            server._embed_failed_at = 0
            got = server._embed(["alpha text", "beta text"])
            self.assertIsNone(got, "a short-count response must read as unavailable, not raise")
        finally:
            server.urllib.request.urlopen = real_urlopen
            server._embed_cache.clear()

    def test_09_every_placement_is_stamped_and_shows_up_as_unverified(self):
        """A machine guess must never read as a settled human decision."""
        hub = self._hub("Guards and gates")
        self._fake_embed({"guards and gates": (1.0, 0.0, 0.0), "guard": (1.0, 0.0, 0.0)})
        r = server.add_topics([{"title": "guard cannot fail", "autofile": True}], "Vera")[0]
        self.assertIn("auto_filed", self._events(r["slug"]))
        q = server._auto_filed_unverified()
        self.assertEqual([x["slug"] for x in q], [r["slug"]])
        self.assertEqual(q[0]["parent"], hub)
        self.assertIn("UNVERIFIED", q[0]["note"])

    def test_10_a_human_reparent_clears_it_from_the_verify_queue(self):
        """The queue must DRAIN, or it becomes the same undifferentiated pile one level up."""
        self._hub("Guards and gates")
        other = self._hub("Somewhere else entirely")
        self._fake_embed({"guards and gates": (1.0, 0.0, 0.0), "guard": (1.0, 0.0, 0.0)})
        r = server.add_topics([{"title": "guard cannot fail", "autofile": True}], "Vera")[0]
        self.assertEqual(len(server._auto_filed_unverified()), 1)
        server.edit_topic(r["slug"], "Murakumo", None, None, other, None)   # the human moves it
        self.assertEqual(server._auto_filed_unverified(), [],
                         "once a person has ruled on the placement it is no longer a machine guess")


if __name__ == "__main__":
    unittest.main(verbosity=2)
