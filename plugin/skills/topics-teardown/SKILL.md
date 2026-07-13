---
name: topics-teardown
description: Run BEFORE uninstalling topic-visualizer to release the machine gracefully - the mirror of topics-setup. Stops the server/embedder we started, removes the login autostart, and offers to remove the local topic store, so nothing is left behind - no Scheduled Task failing at every login, no ghost process holding a port or the DB lock. Trigger when the user says "uninstall topics", "remove the plugin", "how do I get rid of this", "clean up topic-visualizer", or is about to delete the plugin.
---

# topics-teardown: leave the machine as clean as you found it

Onboarding installs real persistence - a login autostart, a running server, an embedder - so the
visualizer survives restarts. The cost: simply DELETING the plugin folder is NOT clean. It orphans a
Scheduled Task that then fails silently at every login, and leaves a ghost process holding the port and
the DB (WAL) lock. Run this FIRST, then uninstall.

**Do this BEFORE deleting the plugin dir** - the teardown matches processes by our exact script paths,
which only exist while the plugin is still installed.

## Step 1 - Stop the processes + remove the autostart

Run the bundled teardown (add `--dry-run` first to preview; drop it to apply):

    python "<PLUGIN>/server/install_service.py" --uninstall --embedder

It STOPS only python processes running OUR server / serve_embedder (a shared or bring-your-own embedder
on the same port is deliberately left alone - never killed by port), then removes the `TopicVisualizer*`
Scheduled Task(s). Read back to the user what it stopped and removed.

## Step 2 - The data store (ASK - it is theirs)

The topic tree lives at `~/.topic-visualizer/` (per-project sqlite). That is the user's data, so ask:

> "Remove your saved topics too, or keep them in case you reinstall?" [remove / keep]

On **remove**, delete `~/.topic-visualizer/` and say so. On **keep**, leave it and hand them the path so
they can remove it themselves later. Never delete their topics without asking.

## Step 3 - Loose ends (mention, do not force)

- If setup persisted `TOPICS_EMBED_URL` / `TOPICS_PROJECT` / `TOPICS_EMBED_MODEL` in their environment,
  list them so they can unset them - stale but harmless.
- The embedding model cache (`~/.cache/huggingface`, ~80MB) is a SHARED huggingface cache other tools
  use - leave it unless the user explicitly wants the space back.

## Step 4 - Confirm clean, then uninstall

Verify: no `TopicVisualizer*` Scheduled Task remains (`schtasks /Query /TN TopicVisualizerServer` should
say not found), nothing answers on the server/embedder ports, and - if they chose remove - the data dir
is gone. Then tell the user it is safe to uninstall the plugin.

## The principle

We onboard gracefully; we release gracefully. A user who leaves should find their machine exactly as
they lent it to us - no ghost task, no held port, no surprise cost. That is how you keep their trust on
the way out - which is how you earn it back if they return.
