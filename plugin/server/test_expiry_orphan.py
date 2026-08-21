#!/usr/bin/env python3
"""0.55.4: the seedling expiry must not ORPHAN a live subtree.

FIELD INCIDENT (quantum-concepts store, found by Tare 2026-08-21 during a groom):
twelve LIVE topics were unreachable from any live root, because the sweep had expired
two nodes that still held live children.

  story-world-craft-e595fd      expired 2026-08-18, holding 10 live children (4 open).
                                Groom-minted as a SEEDLING, later promoted to role='hub'
                                by a reparent and carrying an owner ruling - but its STATE
                                was never explicitly moved off 'seedling', so it stayed
                                eligible forever. It was the tree's only home for
                                story/canon/craft seeds.
  should-pre-registration-...   expired 2026-08-21 MID-GROOM, holding 2 live children.

WHY expire_seedlings could do this and expire_merged could not: the sweep twenty lines
below already carries the guard, with a comment naming this exact hazard ("a POST-merge
capture can be parented under the tombstone ... re-home such children to root FIRST").
expire_seedlings never learned it.

THE DEEPER CAUSE, which is why the guard keys on CHILDREN and not merely on role:
touched_at records the node's OWN touches and does not move when a child is parented
under it. So a node can be actively used as structure for weeks while its clock reads
untouched. The expiry asks "has anyone touched this?" when the question that matters is
"is anyone STANDING on this?"

WHY NOT re-home the children to root the way expire_merged does: a merge tombstone is
deliberately dead, so rescuing its children to root is the only option left. A seedling
holding live children is not dead - it has BECOME structure, and dumping ten craft topics
at root would destroy the grouping a groom built. The right answer is that such a node is
not eligible for expiry at all.

    python server/test_expiry_orphan.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class ExpiryOrphanUnit(unittest.TestCase):
    """Direct-import: expiry eligibility against a temp store."""

    def _fresh(self, tmp):
        sys.path.insert(0, str(HERE))
        import server
        server.DB_PATH = str(Path(tmp) / "t.db")
        server._conn = server.open_db(server.DB_PATH)
        return server

    @staticmethod
    def _age(server, slug, days):
        """Backdate a topic's clocks so the sweep considers it."""
        server._conn.execute(
            "UPDATE topic SET touched_at=datetime('now', ?), "
            "engaged_at=datetime('now', ?) WHERE slug=?",
            ("-%d days" % days, "-%d days" % days, slug))
        server._conn.commit()

    @staticmethod
    def _state(server, slug):
        return server._conn.execute(
            "SELECT state FROM topic WHERE slug=?", (slug,)).fetchone()["state"]

    def test_a_seedling_holding_live_children_is_not_expired(self):
        """THE REGRESSION: the story-world-craft shape, minimally."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            server = self._fresh(tmp)
            parent = server.add_topics(
                [{"title": "story and world craft", "state": "seedling"}], "t")[0]["slug"]
            child = server.add_topics(
                [{"title": "is the Devourer a survivor", "parent_slug": parent,
                  "state": "open"}], "t")[0]["slug"]
            # The parent is old and untouched; the CHILD is what keeps it alive.
            self._age(server, parent, server.SEEDLING_EXPIRY_DAYS + 5)

            server.expire_seedlings()

            self.assertEqual(self._state(server, parent), "seedling",
                             "a seedling holding a LIVE child must survive the sweep - "
                             "expiring it orphans the child under a dead parent")
            self.assertEqual(self._state(server, child), "open",
                             "the child is untouched either way")

    def test_the_child_stays_reachable_from_a_live_root(self):
        """The consequence the incident was actually made of: reachability.

        Asserting the parent's state alone would also pass for a fix that expired the
        parent but re-homed the child to root. That is a DIFFERENT cure (expire_merged's)
        and it would silently destroy the grouping. This leg pins the OUTCOME, not the
        mechanism.
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            server = self._fresh(tmp)
            parent = server.add_topics(
                [{"title": "a groom-minted hub", "state": "seedling"}], "t")[0]["slug"]
            child = server.add_topics(
                [{"title": "a live question under it", "parent_slug": parent,
                  "state": "open"}], "t")[0]["slug"]
            self._age(server, parent, server.SEEDLING_EXPIRY_DAYS + 5)

            server.expire_seedlings()

            row = server._conn.execute(
                "SELECT p.state AS pstate, p.parent_id AS pparent "
                "FROM topic c JOIN topic p ON p.id = c.parent_id WHERE c.slug=?",
                (child,)).fetchone()
            self.assertIsNotNone(row, "the child must still HAVE a parent row")
            self.assertIn(row["pstate"], ("open", "seedling", "discussed"),
                          "the child's parent must be LIVE, or the child is unreachable "
                          "from every live root while still counting as live")
            self.assertIsNone(row["pparent"],
                              "and that parent is still the root it was - not re-homed")

    def test_a_childless_seedling_still_expires(self):
        """The control. Without it the guard could be 'never expire anything' and pass.

        This is the noise valve doing its job: 30 of the 32 nodes the field sweep took
        were exactly this shape, and taking them was CORRECT.
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            server = self._fresh(tmp)
            lonely = server.add_topics(
                [{"title": "an abandoned tentative capture", "state": "seedling"}],
                "t")[0]["slug"]
            self._age(server, lonely, server.SEEDLING_EXPIRY_DAYS + 5)

            n = server.expire_seedlings()

            self.assertEqual(self._state(server, lonely), "expired",
                             "a seedling nobody built on is still noise and still expires")
            self.assertEqual(n, 1, "and it is still COUNTED, so the groom report stays honest")

    def test_a_seedling_whose_only_children_are_dead_still_expires(self):
        """The boundary: 'has children' is not the test - 'has LIVE children' is.

        A seedling whose subtree was pruned away is genuinely abandoned, and holding it
        open forever on the strength of tombstones would make the valve un-closeable.
        """
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            server = self._fresh(tmp)
            parent = server.add_topics(
                [{"title": "a hub whose questions were all answered", "state": "seedling"}],
                "t")[0]["slug"]
            dead = server.add_topics(
                [{"title": "a pruned child", "parent_slug": parent, "state": "open"}],
                "t")[0]["slug"]
            server.set_state(dead, "pruned", "t", "answered")
            self._age(server, parent, server.SEEDLING_EXPIRY_DAYS + 5)

            server.expire_seedlings()

            self.assertEqual(self._state(server, parent), "expired",
                             "only LIVE children hold a seedling open")


if __name__ == "__main__":
    unittest.main(verbosity=2)
