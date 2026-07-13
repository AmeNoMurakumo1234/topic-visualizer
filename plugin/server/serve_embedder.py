#!/usr/bin/env python3
"""A minimal, CPU-only OpenAI-style /v1/embeddings server, so topic-visualizer's semantic stack
(search / dedup / serve ranking) works out of the box - no bring-your-own endpoint, no model hunt.

This is the "bundled embedder" the onboarding overhaul promises. Stdlib HTTP around
sentence-transformers `all-MiniLM-L6-v2` - small (~80MB), fast on CPU, and a STANDARD model, so it
needs NO trust_remote_code and therefore SIDESTEPS the HF_HUB_OFFLINE / LocalEntryNotFound trap that
bites custom-code models on first run. The model auto-downloads once and is cached by huggingface.

    python serve_embedder.py                 # -> http://127.0.0.1:8082  (the plugin's default EMBED_URL)
    python serve_embedder.py --port 8083 --model <hf-model>

Point the plugin at it with TOPICS_EMBED_URL=http://127.0.0.1:<port> - the default :8082 already
matches, so if you run this on the default port the plugin finds it with zero config.

Graceful: if sentence-transformers is not installed, this prints exactly what to `pip install` and
exits - the plugin keeps working in KEYWORD mode until an embedder is up, and `topic_doctor` shows the
state loudly. Optional dependency by design; the core plugin stays stdlib-only.

Swapping the model: set --model / TOPICS_EMBED_MODEL. If you pick a model that requires
`trust_remote_code`, do NOT set HF_HUB_OFFLINE=1 on its first run - such models fetch live hub METADATA
and will hard-fail with LocalEntryNotFound offline (the exact trap all-MiniLM avoids).
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_NAME = os.environ.get("TOPICS_EMBED_MODEL", DEFAULT_MODEL)


def _load_model(name):
    """Load the model on CPU, or exit with an actionable message. CPU by design - the embedder must
    never contend with a GPU the host is using, and this model is fast enough on CPU."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.stderr.write(
            "topic-visualizer embedder: `sentence-transformers` is not installed.\n"
            "  pip install sentence-transformers\n"
            "(CPU-only is fine - it pulls torch. Alternatives: set TOPICS_EMBED_URL to your own\n"
            " OpenAI-style /v1/embeddings endpoint, or skip semantic ranking - the plugin runs\n"
            " keyword-only without an embedder. Run `topic_doctor` any time to see the state.)\n")
        sys.exit(2)
    return SentenceTransformer(name, device="cpu")


class Handler(BaseHTTPRequestHandler):
    model = None

    def log_message(self, *a):  # quiet
        pass

    def _json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            return self._json(200, {"status": "ok", "model": MODEL_NAME})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/embeddings":
            return self._json(404, {"error": "not found"})
        try:
            n = max(0, int(self.headers.get("Content-Length") or 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            inp = body.get("input")
            if isinstance(inp, str):
                inp = [inp]
            if not isinstance(inp, list) or not all(isinstance(x, str) for x in inp):
                return self._json(400, {"error": "'input' must be a string or a list of strings"})
            vecs = self.model.encode(inp, normalize_embeddings=False)
            data = [{"object": "embedding", "index": i, "embedding": [float(x) for x in v]}
                    for i, v in enumerate(vecs)]
            return self._json(200, {"object": "list", "data": data, "model": MODEL_NAME})
        except Exception as e:
            return self._json(500, {"error": str(e)})


def main():
    ap = argparse.ArgumentParser(description="Bundled CPU /v1/embeddings server for topic-visualizer")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("TOPICS_EMBED_PORT", "8082")))
    ap.add_argument("--model", default=MODEL_NAME)
    args = ap.parse_args()
    globals()["MODEL_NAME"] = args.model
    Handler.model = _load_model(args.model)      # loads (and downloads once) before we accept traffic
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(json.dumps({"topic_visualizer_embedder": f"http://{args.host}:{args.port}",
                      "model": args.model, "endpoint": "/v1/embeddings"}))
    srv.serve_forever()


if __name__ == "__main__":
    main()
