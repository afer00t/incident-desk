"""Incident Desk — Clocked Build Challenge entry.

Single-service FastAPI app: intake with PII redaction + injection guard + decision,
then grounding checks for agent answers, duplicate detection, KB rerank, and
change-request script inspection. Only anonymised ticket text is persisted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
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

WIB = timezone(timedelta(hours=7))


def now_wib() -> str:
    return datetime.now(WIB).isoformat(timespec="seconds")


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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS dossiers(
            id TEXT PRIMARY KEY, ticket_id TEXT, created_at TEXT, query TEXT, answer TEXT,
            payload TEXT, receipt TEXT, mode TEXT)"""
    )
    conn.commit()
    return conn


def log_usage(endpoint: str, mode: str, credits: float = 0.0, cost_usd: float = 0.0) -> None:
    with db() as conn:
        conn.execute("INSERT INTO usage(ts, mode, endpoint, credits, cost_usd) VALUES(?,?,?,?,?)",
                     (now_wib(), mode, endpoint, credits, cost_usd))


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


class Dossier(BaseModel):
    ticket_id: str
    answer: str
    query: str = ""


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
            "sources": list((cl.get("sources") or {}).keys()) if isinstance(cl.get("sources"), dict) else [],
        })
    weakest = out.get("weakest_claim")
    if isinstance(weakest, dict):
        idx = weakest.get("index")
        weakest = claims[idx]["claim"] if isinstance(idx, int) and 0 <= idx < len(claims) else "see claims"
    unsupported = []
    for i in out.get("unsupported_claims") or []:
        if isinstance(i, int) and 0 <= i < len(claims):
            unsupported.append(claims[i]["claim"])
        elif isinstance(i, dict):
            unsupported.append(i.get("claim") or str(i)[:120])
        else:
            unsupported.append(str(i)[:120])
    return {**out, "claims": claims, "weakest_claim": weakest or "Every claim is supported.",
            "unsupported_claims": unsupported}


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha(obj) -> str:
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()


def normalize_compare(out: dict) -> dict:
    """Flatten live pairs ({a,b:{id}}) and mock pairs into one shape."""
    pairs = []
    for p in out.get("pairs") or []:
        b = p.get("b")
        bid = b.get("id") if isinstance(b, dict) else b
        pairs.append({
            "a": p.get("a"),
            "b": bid,
            "relation": p.get("relation") or "unrelated",
            "related": round(float(p.get("related", 0) or 0), 4),
        })
    return {
        "verdict": out.get("verdict") or (pairs[0]["relation"] if pairs else "unrelated"),
        "pairs": pairs,
        "duplicates": [p for p in pairs if p["relation"] == "duplicates"],
        "overlaps": [p for p in pairs if p["relation"] == "related"],
        "conflicts": [p for p in pairs if p["relation"] == "conflict"],
    }


def normalize_rerank(out: dict) -> dict:
    items = out.get("results") if isinstance(out, dict) else out
    results = []
    for r in items or []:
        results.append({
            "id": r.get("id"),
            "action": r.get("action"),
            "relevance_score": round(float(r.get("relevance_score", r.get("score", 0)) or 0), 4),
        })
    return {"results": results}


def call_meta(label: str, started: float) -> dict:
    raw = {k.lower(): v for k, v in api.last_headers.items()}
    return {
        "endpoint": label,
        "ms": round((time.perf_counter() - started) * 1000, 1),
        "credits": round(float(raw.get("x-clocked-credits", 0) or 0), 3),
        "cost_usd": round(float(raw.get("x-clocked-cost-usd", 0) or 0), 6),
        "request_id": raw.get("x-clocked-request-id") or raw.get("x-request-id"),
    }


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
        d = conn.execute("SELECT id,ticket_id,created_at,receipt,mode FROM dossiers ORDER BY created_at DESC LIMIT 1").fetchone()
    latest = json.loads(d["receipt"]) if d else None
    if latest:
        latest.update({"ticket_id": d["ticket_id"], "mode": d["mode"]})
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
        "latest_dossier": latest,
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
    row = {
        "created_at": now_wib(),
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
    for _ in range(8):
        row["id"] = "TCK-" + uuid.uuid4().hex[:6].upper()
        try:
            with db() as conn:
                conn.execute(
                    """INSERT INTO tickets(id,created_at,safe_text,entities,injection,decision,extraction,status,priority,mode)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (row["id"], row["created_at"], row["safe_text"], json.dumps(row["entities"]), json.dumps(row["injection"]),
                     json.dumps(row["decision"]), json.dumps(row["extraction"]), row["status"], row["priority"], row["mode"]),
                )
            return row
        except sqlite3.IntegrityError:
            continue  # 6-hex id collided; draw a new one
    return {"error": "could not allocate a ticket id"}


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


@app.post("/api/dossier")
def dossier(req: Dossier):
    """Verify one ticket end-to-end: claims, duplicates and ranked passages, then sign the payload."""
    with db() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id=?", (req.ticket_id,)).fetchone()
    if not row:
        return {"error": "unknown ticket"}
    answer = req.answer.strip()[:20000]
    if not answer:
        return {"error": "empty answer"}
    query = (req.query.strip() or row["safe_text"] or "")[:500]

    docs = [{"id": k["id"], "text": k["text"]} for k in KB] + [{"id": row["id"], "text": row["safe_text"] or ""}]
    api.last_headers = {}
    started = time.perf_counter()
    if api.active:
        g_raw = run(api.grounding, f"Does the assistant answer follow from {row['id']} and the knowledge base?",
                    docs, answer, 0.65, endpoint="grounding")
    else:
        g_raw = mock_call(mock_grounding, "grounding", answer, docs)
    grounding = normalize_grounding(g_raw)
    g_meta = call_meta("grounding", started)

    with db() as conn:
        others = conn.execute(
            "SELECT id, safe_text FROM tickets WHERE id<>? ORDER BY created_at DESC LIMIT 9", (row["id"],)
        ).fetchall()
    c_docs = [{"id": row["id"], "text": row["safe_text"] or ""}] + [
        {"id": o["id"], "text": o["safe_text"] or ""} for o in others
    ]
    started = time.perf_counter()
    api.last_headers = {}
    if api.active and len(c_docs) > 1:
        c_raw = run(api.compare, c_docs)
    else:
        c_raw = mock_call(mock_compare, "compare", c_docs) if len(c_docs) > 1 else {
            "model": "local", "verdict": "unrelated", "pairs": []
        }
    compare = normalize_compare(c_raw)
    c_meta = call_meta("compare", started)

    r_docs = [{"id": k["id"], "title": k["title"], "text": k["text"]} for k in KB]
    started = time.perf_counter()
    api.last_headers = {}
    if api.active:
        r_raw = run(api.rerank, query, r_docs)
    else:
        r_raw = mock_call(mock_rerank, "rerank", query, r_docs)
    rerank = normalize_rerank(r_raw)
    r_meta = call_meta("rerank", started)

    mode = "live" if api.active else "mock"
    payload = {
        "ticket_id": row["id"], "answer": answer, "query": query,
        "grounding": grounding, "compare": compare, "rerank": rerank,
        "meta": {"grounding": g_meta, "compare": c_meta, "rerank": r_meta},
    }
    did = "DSH-" + uuid.uuid4().hex[:10].upper()
    created = now_wib()
    sections = {k: sha(payload[k]) for k in ("grounding", "compare", "rerank", "meta")}
    receipt = {
        "id": did, "created_at": created, "mode": mode,
        "payload_sha256": sha(payload), "sections": sections,
    }
    with db() as conn:
        conn.execute(
            """INSERT INTO dossiers(id,ticket_id,created_at,query,answer,payload,receipt,mode)
               VALUES(?,?,?,?,?,?,?,?)""",
            (did, row["id"], created, query, answer, json.dumps(payload), json.dumps(receipt), mode),
        )
    return {"id": did, "mode": mode, **payload, "receipt": receipt}


@app.get("/api/dossiers/{did}")
def get_dossier(did: str):
    with db() as conn:
        row = conn.execute("SELECT payload, receipt, mode FROM dossiers WHERE id=?", (did,)).fetchone()
    if not row:
        return {"error": "unknown dossier"}
    return {"id": did, "mode": row["mode"], **json.loads(row["payload"]), "receipt": json.loads(row["receipt"])}


@app.get("/api/dossiers/{did}/verify")
def verify_dossier(did: str):
    with db() as conn:
        row = conn.execute("SELECT payload, receipt, mode, created_at FROM dossiers WHERE id=?", (did,)).fetchone()
    if not row:
        return {"error": "unknown dossier"}
    payload = json.loads(row["payload"])
    receipt = json.loads(row["receipt"])
    computed = sha(payload)
    sections = {}
    for key, want in (receipt.get("sections") or {}).items():
        got = sha(payload.get(key))
        sections[key] = {"ok": got == want, "stored": want, "computed": got}
    return {
        "ok": computed == receipt.get("payload_sha256"),
        "id": did, "mode": row["mode"], "created_at": row["created_at"],
        "stored_sha256": receipt.get("payload_sha256"), "computed_sha256": computed,
        "sections": sections,
        "changed": [k for k, v in sections.items() if not v["ok"]],
    }


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