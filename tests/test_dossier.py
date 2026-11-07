"""Dossier test: signed payload, verify endpoint, and tamper detection.

Runs FastAPI in offline mode against a throwaway database so it never
spends Clocked credits.
"""
from __future__ import annotations

import sqlite3
import sys
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient

import app as mod

mod.api.key = ""
mod.api.last_headers = {}

with tempfile.TemporaryDirectory() as td:
    mod.DB = Path(td) / "test.sqlite"
    client = TestClient(mod.app)

    seed = client.post("/api/demo/fill").json()
    assert seed.get("seeded", 0) > 0 or seed.get("skipped"), seed

    tickets = client.get("/api/state").json()["tickets"]
    assert tickets, "demo seed produced no tickets"
    ticket_id = tickets[0]["id"]
    answer = "The fuselage will not boot because the timer chip is empty."

    res = client.post("/api/dossier", json={
        "ticket_id": ticket_id,
        "answer": answer,
        "query": "fuselage boot failure",
    })
    assert res.status_code == 200, res.text
    dossier = res.json()
    assert dossier["mode"] == "mock"
    assert dossier["ticket_id"] == ticket_id
    assert dossier["grounding"]["claims"], "grounding returned no claims"
    assert dossier["compare"]["verdict"]
    assert dossier["receipt"]["payload_sha256"]
    assert dossier["receipt"]["sections"]["grounding"]
    assert datetime.fromisoformat(dossier["receipt"]["created_at"]).utcoffset() == timedelta(hours=7)

    verified = client.get(f"/api/dossiers/{dossier['id']}/verify").json()
    assert verified["ok"] is True, verified
    assert verified["changed"] == [], verified
    assert verified["computed_sha256"] == dossier["receipt"]["payload_sha256"]

    loaded = client.get(f"/api/dossiers/{dossier['id']}").json()
    assert loaded["receipt"]["payload_sha256"] == dossier["receipt"]["payload_sha256"]
    assert loaded["answer"] == answer

    con = sqlite3.connect(mod.DB)
    stored = con.execute("SELECT payload FROM dossiers WHERE id=?", (dossier["id"],)).fetchone()[0]
    obj = json.loads(stored)
    obj["answer"] = obj["answer"] + " "
    con.execute("UPDATE dossiers SET payload=? WHERE id=?", (json.dumps(obj), dossier["id"]))
    con.commit()
    con.close()

    tampered = client.get(f"/api/dossiers/{dossier['id']}/verify").json()
    assert tampered["ok"] is False, tampered
    assert "grounding" not in tampered["changed"], tampered

assert mod.normalize_compare({"pairs": [
    {"a": "a", "b": {"id": "b"}, "relation": "duplicates", "related": 0.9}
]})["pairs"][0]["b"] == "b"
assert mod.sha({"a": 1, "b": [1, 2]}) == mod.sha({"b": [1, 2], "a": 1})
print("DOSSIER OK · signed, verified, tamper detected, canonical hash stable")