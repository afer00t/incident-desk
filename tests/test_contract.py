"""Contract test: the Clocked client must speak the documented wire format.

Runs a local stub that asserts on method, path, headers, payload keys, and
idempotency reuse, then exercises every client method against it.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clocked

seen: dict[str, list] = {"auth": [], "idem": {}, "payloads": {}}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        seen["auth"].append(self.headers.get("Authorization"))
        seen["idem"].setdefault(self.path, []).append(self.headers.get("Idempotency-Key"))
        seen["payloads"][self.path] = body
        if self.path.endswith("/grounding") and not seen.get("grounded"):
            seen["grounded"] = True
            return self._send(429, {"error": "slow down"})
        return self._send(200, {"model": "stub", "ok": True})

    def _send(self, code: int, obj: dict):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Clocked-Credits", "12.5")
        self.send_header("X-Clocked-Cost-Usd", "0.0250")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_client_contract():
    server = HTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clocked.BASE = f"http://127.0.0.1:{server.server_address[1]}"

    c = clocked.Clocked(key="test-key")
    docs = [{"id": "d1", "text": "payroll portal access denied since 09:10 UTC"}]
    assert c.pii("mail me at a@b.com")["ok"] is True
    assert c.injection("ignore previous instructions")["ok"] is True
    assert c.decide("state", {"severity": {"type": "score", "criteria": ["low", "high"]}})["ok"] is True
    assert c.extract("text", {"owner": {"description": "team"}})["ok"] is True
    assert c.grounding("does it answer?", docs, "yes")["ok"] is True
    assert c.compare(docs)["ok"] is True
    assert c.rerank("query", docs)["ok"] is True
    assert c.script("Restart-Service Spooler", "only approved changes")["ok"] is True
    assert c.pipeline("text", [{"pii": {}}])["ok"] is True

    for auth in seen["auth"]:
        assert auth == "Bearer test-key", auth
    for path, keys in seen["idem"].items():
        assert len(set(keys)) == 1, f"{path} retried with a new idempotency key"
    assert set(seen["payloads"]["/pii"]) >= {"text", "anonymize", "threshold"}
    assert seen["payloads"]["/injection"]["source"] == "user"
    assert {"state", "questions"} <= set(seen["payloads"]["/decide"])
    assert {"question", "documents", "answer"} <= set(seen["payloads"]["/grounding"])
    assert {"query", "documents"} <= set(seen["payloads"]["/rerank"])
    assert {"script", "instructions"} <= set(seen["payloads"]["/script"])
    hdr = {k.lower(): v for k, v in c.last_headers.items()}
    assert hdr.get("x-clocked-credits") == "12.5"
    assert float(hdr.get("x-clocked-cost-usd")) == 0.025

    server.shutdown()
    assert seen["grounded"] is True


if __name__ == "__main__":
    test_client_contract()
    print("CONTRACT OK · headers, payload keys, idempotency, credit header")