"""_embed sends one HTTP request per call, and search embeds the WHOLE store, archive included.

Field case, quantum-concepts 2026-10-10 (Tare, run 56): a 1226-row store took 8.51s to embed in
one request against an 8s timeout, so every topic_search on it fell back to KEYWORD while
topic_doctor reported semantic ranking on - and the failure latched the embedder "down" for 60s,
so capture-time dedup in that minute went keyword too. The failed batch cached nothing, so the
next search paid the same cold cost and failed the same way: it could never warm itself.
Control: a 7-row store answered `mode: semantic` on the same server in the same minute.

The stub below fails any request carrying more than 300 inputs, which is about half of what the
real embedder managed inside the timeout (600 in 4.2s). That is the BEHAVIOUR under test: a long
list must reach the embedder as several bounded requests, not one unbounded one.
"""
import json
import unittest

import server


class _Resp:
    def __init__(self, n):
        self._n = n

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"data": [{"embedding": [1.0, 0.0, float(i)]}
                                    for i in range(self._n)]}).encode()


class EmbedChunking(unittest.TestCase):
    CLIFF = 300

    def setUp(self):
        self._urlopen = server.urllib.request.urlopen
        self._url = server.EMBED_URL
        server.EMBED_URL = server.EMBED_URL or "http://127.0.0.1:9"
        server._embed_cache.clear()
        server._embed_up = None
        server._embed_failed_at = 0
        self.sizes = []
        self.fail_on_call = None

        def fake(req, timeout=None):
            n = len(json.loads(req.data)["input"])
            self.sizes.append(n)
            if n > self.CLIFF or len(self.sizes) == self.fail_on_call:
                raise TimeoutError("timed out")
            return _Resp(n)

        server.urllib.request.urlopen = fake

    def tearDown(self):
        server.urllib.request.urlopen = self._urlopen
        server.EMBED_URL = self._url
        server._embed_cache.clear()
        server._embed_up = None
        server._embed_failed_at = 0

    def test_a_store_larger_than_one_request_still_embeds(self):
        texts = [f"topic number {i}" for i in range(1000)]
        got = server._embed(texts)
        self.assertIsNotNone(got, f"fell back to keyword; request sizes were {self.sizes}")
        self.assertEqual(len(got), 1000)
        self.assertTrue(all(n <= self.CLIFF for n in self.sizes), self.sizes)

    def test_a_late_failure_keeps_the_chunks_that_landed(self):
        """Progress must survive a failure, or a store that times out once times out forever."""
        texts = [f"topic number {i}" for i in range(1000)]
        self.fail_on_call = 2
        self.assertIsNone(server._embed(texts), "a failed chunk is still unavailability")
        cached = sum(1 for t in texts if t in server._embed_cache)
        self.assertGreater(cached, 0, "the first chunk landed and should have been kept")
        self.assertLess(cached, 1000)


if __name__ == "__main__":
    unittest.main()
