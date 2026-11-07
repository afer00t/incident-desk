# Incident Desk

Operational ticket console that puts **Clocked** between an untrusted inbound ticket and the
people or agents who act on it.

Three questions decide whether a ticket is safe and urgent, what it is about, and who owns it.
The answer a support agent drafts is then checked claim by claim against the ticket and the
knowledge base, so an unsupported sentence never reaches a customer.

```
inbound ──► PII (redact) ──► Guard (injection) ──► Decide (severity / impacts / owner)
                                │                       │
                                └── blocked ──► isolated, nothing routed
                                                │
                         Extract (fields) ──► ticket record (redacted only)
                                                │
        Answer ──► Grounding ──► per-claim confidence + weakest claim
        Knowledge query ──► Rerank ──► use / expand / skip
        Open tickets ──► Compare ──► duplicates, overlaps, conflicts
        Change request ──► Script ──► malicious / suspicious / benign
```

## Screenshots

| | |
|---|---|
| ![Blocked ticket](docs/screenshots/01-guard-blocked.png) | ![Grounding](docs/screenshots/02-grounding.png) |
| Guard isolates an instruction-override ticket | Per-claim grounding on a drafted answer |
| ![Duplicates](docs/screenshots/03-duplicates.png) | ![Live](docs/screenshots/04-live-verified.png) |
| Compare flags the near-duplicate payroll reports | Live console: live mode, real credit accounting |
| ![Dossier](docs/screenshots/06-dossier-verify.png) | ![Submission](docs/screenshots/05-submission-saved.png) |
| Dossier re-verified after storage | Clocked entry saved with eight endpoints selected |

## What it demonstrates

| Clocked call | Where it changes the product |
|---|---|
| `pii` | The ticket is redacted **before** it is stored; the inbox only ever shows and persists `[NAME]`, `[EMAIL]`, `[ASSET]` |
| `injection` | A ticket that tries to override instructions is isolated; severity is reset and no agent receives it |
| `decide` | Severity, business impact and owning team come from typed decisions with probabilities, not from a keyword score |
| `extract` | Asset, reporter, channel, urgency and requested action are pulled into structured fields |
| `grounding` | The drafted answer is scored per claim; unsupported claims are listed with the weakest one surfaced |
| `compare` | Near-duplicate payroll reports are merged into one incident instead of triaged twice |
| `rerank` | Knowledge-base lookup returns `use` / `expand` / `skip` actions with relevance scores |
| `script` | A change request containing EDR disabling is stopped before anyone runs it |
| `dossier` | Grounding, compare and rerank run together; the full payload is SHA-256 signed and can be reverified after storage |

All eight endpoints drive the UI. `fill` and `pipeline` are available in the client for the same
model family (record synthesis, and an eight-step one-request flow) but are not on the main path.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# offline demo — no key required, deterministic fixtures, indistinguishable UI
cp .env.example .env && python -m uvicorn app:app --port 8777

# live Clocked mode
set -a && . ./.env && set +a
python -m uvicorn app:app --port 8777
```

Open <http://127.0.0.1:8777>. `Load demo` seeds four synthetic tickets.

`CLOCKED_API_KEY` is read only from the environment or from `CLOCKED_API_KEY` in `.env`
(mode `0600`). Without a key the app runs in `MOCK` and every endpoint uses the local fixture
model; with a key it switches to `LIVE` and the header reports `credits` and `cost_usd` from
`X-Clocked-Credits` / `X-Clocked-Cost-Usd`.

## Layout

```
app.py                  FastAPI routes, storage, intake orchestration
clocked.py              Clocked client: Bearer + Idempotency-Key + retry, no key in code
fixtures.py             synthetic tickets, KB passages, mock model for offline demo
static/index.html       single-page console (no build step, no CDN)
tests/test_contract.py  stub server asserts headers, payload keys, idempotency reuse
tests/test_dossier.py   signed dossier, verify endpoint, tamper detection
data/tickets.sqlite     created at runtime, holds redacted text only
```

## Design notes

**One redaction, one source of truth.** `safe_text` is the only ticket text persisted and the only
text sent to `decide`, `extract`, `guard`, `grounding`, `compare` and `rerank`. Raw inbound text is
used once, by the PII call, and is not written to disk. This is the product's core claim, and it
is enforced by the storage schema rather than by convention.

**Guard before decision.** A blocked ticket never receives a severity score. The UI shows the
evidence category and probability from `injection` so an operator can see *why* it was isolated.

**Decisions stay decisions.** `threshold` returns booleans, but the app keeps the probabilities and
shows confidence next to every label, because a rigid boolean hides the cases that need a human.

**Failures are visible.** Anything that cannot reach Clocked returns the upstream error instead of
a fake success; the mode badge is the first thing on the toolbar.

**The dossier is signed, not asserted.** `/api/dossier` hashes the exact grounding, compare, rerank
and call metadata with canonical JSON, stores the receipt, and exposes `/verify` so a later reader
can prove the payload was not edited after the fact. The UI shows `INTACT` or names the changed
section. This is integrity for the displayed evidence, not a claim that the upstream model is
truthful.

## Cost

One credit equals 25 ms of model time, minimum one credit per request. A typical intake is
`pii` + `injection` + `decide` + `extract`; an answer check adds `grounding`, a duplicate sweep adds
`compare`, and a signed dossier adds `grounding` + `compare` + `rerank` in one pass. The header
exposes the actual charge per call, so the running total in the toolbar is the real bill, not an
estimate.

## Tests

```bash
python tests/test_contract.py      # wire contract against a local stub
python tests/test_dossier.py       # signed payload, verify, tamper detection
python -m uvicorn app:app --port 8777
```

The contract test asserts the required `Authorization`, a single `Idempotency-Key` reused across
retries, the documented payload keys for `pii`, `injection`, `decide`, `grounding`, `rerank` and
`script`, and that the credit/cost headers are surfaced. Four end-to-end runs of the intake also
pass 5/5 with identical output. The dossier test runs against a throwaway database, signs a live-shaped
payload, proves the receipt, mutates the stored answer and proves the tamper is detected without
spending credits.

## Security

- API key never enters the source tree, the UI, or a log line.
- Idempotency keys are generated per logical request and reused verbatim on retry.
- Only redacted text is persisted; raw tickets are discarded after the PII call.
- Guarded tickets are stored with a `blocked` status and zero priority so they cannot be picked up
  by an automation queue.

## Team

WELY — build, operations, Clocked integration.