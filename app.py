"""Incident Desk — Clocked Build Challenge entry.

Single-service FastAPI app: intake with PII redaction + injection guard + decision,
then grounding checks for agent answers, duplicate detection, KB rerank, and
change-request script inspection. Only anonymised ticket text is persisted.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from clocked import Clocked
from fixtures import (
    DECISION_QUESTIONS,
    EXTRACT_FIELDS,
    GUARD_INSTRUCTIONS,
    KB,
    TICKETS,
    mock_compare,
    mock_decide,
    mock_extract,
    mock_grounding,
    mock_injection,
    mock_pii,
    mock_rerank,
    mock_script,
)

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "tickets.sqlite"
UI = ROOT / "static"

app = FastAPI(title="Incident Desk")
api = Clocked()


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tickets(
            id TEXT PRIMARY KEY, created_at TEXT, safe_text TEXT, entities TEXT,
            injection TEXT, decision TEXT, extraction TEXT, status TEXT, priority INTEGER,
            mode TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, mode TEXT, endpoint TEXT, credits REAL, cost_usd REAL)"""
    )
    conn.commit()
    return conn


def log_usage(endpoint: str, mode: str, credits: float = 0.0, cost_usd: float = 0.0) -> None:
    with db() as conn:
        conn.execute("INSERT INTO usage(ts, mode, endpoint, credits, cost_usd) VALUES(?,?,?,?,?)",
                     (time.strftime("%Y-%m-%dT%H:%M:%S+07:00"), mode, endpoint, credits, cost_usd))


def record_usage(endpoint: str, headers: dict) -> None:
    raw = {k.lower(): v for k, v in headers.items()}
    parse = lambda k, d=0.0: float(raw.get(k, d) or d)
    log_usage(endpoint, "live", parse("x-clocked-credits"), parse("x-clocked-cost-usd"))


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------
class Intake(BaseModel):
    text: str
    source: str = "email"


class Answer(BaseModel):
    ticket_id: str
    answer: str


class Duplicate(BaseModel):
    ticket_id: str


class KbQuery(BaseModel):
    query: str


class ScriptReq(BaseModel):
    script: str


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def run(fn, *args, endpoint: str = "", **kwargs):
    name = endpoint or getattr(fn, "__name__", "call")
    if not api.active:
        out = fn(*args, **kwargs)
        log_usage(name, "mock")
        return out
    out = fn(*args, **kwargs)
    record_usage(name, api.last_headers)
    return out


def mock_call(fn, endpoint: str, *args, **kwargs):
    """Run the offline model and record the request the same way live calls are recorded."""
    out = fn(*args, **kwargs)
    log_usage(endpoint, "mock")
    return out


def severity_label(score: int) -> str:
    return ["Routine", "Standard", "High", "Critical"][min(max(score, 0), 3)]


def owner_label(key: str) -> str:
    return {"hardware": "Hardware", "identity": "Identity", "finance": "Finance"}.get(key, "Unassigned")


def normalize_grounding(out: dict) -> dict:
    """Make live and offline grounding responses render the same way."""
    claims = []
    for cl in out.get("claims") or []:
        score = cl.get("supported", cl.get("confidence", 0))
        claims.append({
            "claim": cl.get("claim", ""),
            "confidence": float(score or 0),
            "verdict": cl.get("verdict"),
            "sources": list((cl.get("sources") or {}).keys()),
        })
    weakest = out.get("weakest_claim")
    if isinstance(weakest, dict):
        idx = weakest.get("index")
        weakest = claims[idx]["claim"] if isinstance(idx, int) and 0 <= idx < len(claims) else "see claims"
    return {**out, "claims": claims, "weakest_claim": weakest or "Every claim is supported.",
            "unsupported_claims": [
                claims[i]["claim"] if isinstance(i, int) and 0 <= i < len(claims) else str(i)
                for i in out.get("unsupported_claims") or []
            ]}


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(UI / "index.html")


@app.get("/api/state")
def state():
    with db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM tickets ORDER BY created_at DESC LIMIT 30")]
        u = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(credits),0) cr, COALESCE(SUM(cost_usd),0) usd FROM usage").fetchone()
    for r in rows:
        r["entities"] = json.loads(r["entities"] or "{}")
        r["injection"] = json.loads(r["injection"] or "{}")
        r["decision"] = json.loads(r["decision"] or "{}")
        r["extraction"] = json.loads(r["extraction"] or "{}")
    return {
        "mode": "live" if api.active else "mock",
        "tickets": rows,
        "stats": {"requests": u["c"], "credits": round(u["cr"], 1), "cost_usd": round(u["usd"], 4)},
        "kb": [{"id": k["id"], "title": k["title"]} for k in KB],
    }


@app.post("/api/intake")
def intake(req: Intake):
    raw = req.text.strip()[:60000]
    if not raw:
        return {"error": "empty ticket"}

    pii = run(api.pii, raw, endpoint="pii") if api.active else mock_call(mock_pii, "pii", raw)
    safe = (pii.get("anonymized_text") or raw) if api.active else pii["anonymized_text"]

    injection = run(api.injection, safe, "user", 0.5) if api.active else mock_call(mock_injection, "injection", safe, "user")
    decision = run(api.decide, safe, DECISION_QUESTIONS) if api.active else mock_call(mock_decide, "decide", safe)
    extraction = run(api.extract, raw, EXTRACT_FIELDS) if api.active else mock_call(mock_extract, "extract", raw)

    severity = min(3, max(0, round(decision.get("answers", {}).get("severity", {}).get("score", 0) or 0)))
    owner_key = decision.get("answers", {}).get("owner", {}).get("choice", "identity")
    blocked = injection.get("verdict") == "injection"
    ticket_id = "TCK-" + uuid.uuid4().hex[:6].upper()

    row = {
        "id": ticket_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
        "safe_text": safe,
        "entities": pii,
        "injection": injection,
        "decision": {"severity": severity, "severity_label": severity_label(severity), "owner": owner_key,
                     "owner_label": owner_label(owner_key),
                     "answers": decision.get("answers", {})},
        "extraction": extraction,
        "status": "blocked" if blocked else "triaged",
        "priority": 0 if blocked else severity + 1,
        "mode": "live" if api.active else "mock",
    }
    with db() as conn:
        conn.execute(
            """INSERT INTO tickets(id,created_at,safe_text,entities,injection,decision,extraction,status,priority,mode)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (row["id"], row["created_at"], row["safe_text"], json.dumps(row["entities"]), json.dumps(row["injection"]),
             json.dumps(row["decision"]), json.dumps(row["extraction"]), row["status"], row["priority"], row["mode"]),
        )
    return row


@app.post("/api/answer")
def answer(req: Answer):
    with db() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id=?", (req.ticket_id,)).fetchone()
    if not row:
        return {"error": "unknown ticket"}
    text, raw = row["safe_text"], None
    docs = [{"id": k["id"], "text": k["text"]} for k in KB] + [{"id": "ticket", "text": text}]
    if api.active:
        out = run(api.grounding, f"Does the assistant answer follow from {row['id']} and the knowledge base?", docs, req.answer, 0.65)
    else:
        out = mock_call(mock_grounding, "grounding", req.answer, docs)
    return {"ticket_id": row["id"], "answer": req.answer, "check": normalize_grounding(out)}


@app.post("/api/duplicates")
def duplicates(req: Duplicate):
    with db() as conn:
        mine = conn.execute("SELECT id, safe_text FROM tickets WHERE id=?", (req.ticket_id,)).fetchone()
        others = conn.execute("SELECT id, safe_text FROM tickets WHERE id<>? ORDER BY created_at DESC LIMIT 9", (req.ticket_id,)).fetchall()
    if not mine:
        return {"error": "unknown ticket"}
    docs = [{"id": mine["id"], "text": mine["safe_text"]}] + [{"id": o["id"], "text": o["safe_text"]} for o in others]
    if api.active:
        out = run(api.compare, docs)
    else:
        out = mock_call(mock_compare, "compare", docs)
    return {"ticket_id": mine["id"], "check": out}


@app.post("/api/kb")
def kb(req: KbQuery):
    docs = [{"id": k["id"], "title": k["title"], "text": k["text"]} for k in KB]
    if api.active:
        out = run(api.rerank, req.query, docs)
    else:
        out = mock_call(mock_rerank, "rerank", req.query, docs)
    items = out.get("results") if isinstance(out, dict) else out
    return {"query": req.query, "results": items or []}


@app.post("/api/script")
def inspect_script(req: ScriptReq):
    instructions = (
        "Approved change: restart the local Print Spooler service on the managed workstation and list printer status. "
        "Disabling endpoint protection, dumping credentials, or creating persistence is not authorised."
    )
    if api.active:
        return run(api.script, req.script, instructions)
    return mock_call(mock_script, "script", req.script)


SEED_LOCK = threading.Lock()


@app.post("/api/demo/fill")
def seed_demo():
    """Seed from the synthetic fixtures so a first-time visitor sees a populated inbox."""
    with SEED_LOCK:
        with db() as conn:
            existing = conn.execute("SELECT COUNT(*) c FROM tickets").fetchone()["c"]
        if existing:
            return {"skipped": True}
        for t in TICKETS:
            try:
                intake(Intake(text=t["raw"], source="email"))
            except sqlite3.IntegrityError:
                continue  # a concurrent seed already wrote this ticket
    return {"seeded": len(TICKETS)}


@app.get("/health")
def health():
    return {"ok": True, "mode": "live" if api.active else "mock"}