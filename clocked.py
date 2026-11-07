"""Thin Clocked API client: Bearer auth, required Idempotency-Key, bounded retry."""
from __future__ import annotations

import os
import time
import uuid

import httpx

BASE = "https://clocked.rezolve.ai/clocked"


class ClockedError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status


class Clocked:
    def __init__(self, key: str | None = None, timeout: float = 90.0):
        self.key = (key or os.environ.get("CLOCKED_API_KEY") or "").strip()
        self.timeout = timeout
        self.last_headers: dict[str, str] = {}

    @property
    def active(self) -> bool:
        return bool(self.key)

    def call(self, path: str, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
            "Accept": "application/json",
        }
        with httpx.Client(timeout=self.timeout) as client:
            idem = str(uuid.uuid4())  # one logical request: same key across retries
            for attempt in range(1, 4):
                resp = client.post(f"{BASE}/{path.lstrip('/')}", json=payload, headers=headers | {"Idempotency-Key": idem})
                self.last_headers = dict(resp.headers)
                if resp.status_code == 429:
                    time.sleep(min(2 ** attempt * 1.5, 8.0))
                    continue
                if resp.status_code >= 500:
                    time.sleep(min(attempt, 2.0))
                    continue
                if resp.status_code >= 400:
                    raise ClockedError(resp.status_code, resp.text)
                return resp.json()
        raise ClockedError(429, "rate limited after retry")

    # ---- endpoints used by the app -------------------------------------
    def pii(self, text: str, entities: dict | None = None, anonymize: bool = True, threshold: float = 0.35):
        payload = {"text": text, "anonymize": anonymize, "threshold": threshold}
        if entities:
            payload["entities"] = entities
        return self.call("pii", payload)

    def injection(self, text: str, source: str = "user", threshold: float = 0.5):
        return self.call("injection", {"text": text, "source": source, "threshold": threshold})

    def decide(self, state: str, questions: dict):
        return self.call("decide", {"state": state, "questions": questions})

    def extract(self, text: str, fields: dict):
        return self.call("extract", {"text": text, "fields": fields})

    def grounding(self, question: str, documents: list[dict], answer: str, threshold: float = 0.65):
        docs = [{"id": d["id"], "text": d["text"][:20000]} for d in documents[:20]]
        return self.call(
            "grounding",
            {"question": question, "documents": docs, "answer": answer, "threshold": threshold},
        )

    def compare(self, documents: list[dict], threshold: float = 0.5):
        docs = [{"id": d["id"], "text": d["text"][:20000]} for d in documents[:20]]
        return self.call("compare", {"documents": docs, "threshold": threshold})

    def rerank(self, query: str, documents: list[dict]):
        docs = [{"id": d["id"], "title": d.get("title", d["id"]), "text": d["text"][:20000]} for d in documents[:60]]
        return self.call("rerank", {"query": query, "documents": docs})

    def script(self, script: str, instructions: str, threshold: float = 0.5):
        return self.call("script", {"script": script, "instructions": instructions, "threshold": threshold})

    def pipeline(self, text: str, steps: list[dict], on_error: str = "skip"):
        return self.call("pipeline", {"text": text, "steps": steps, "on_error": on_error})