# Submission sheet — Clocked Build Challenge

Paste-ready fields for <https://clocked.rezolve.ai/challenge>. Fill the two placeholders after the
repository is public.

**Project name:** Incident Desk — a support console that protects, decides, then verifies.

**One-line pitch:** Every inbound ticket is redacted, screened for instruction attacks and scored
for business impact before it reaches a human; every drafted answer is then checked claim by claim
against the ticket and the knowledge base.

**Category entered:** Verify / Compare / Rerank (with Decide, Protect and Inspect in the same flow,
so the entry also demonstrates breadth across all three groups).

**Demo URL:** https://subsidiary-suited-alloy-science.trycloudflare.com

**Repository:** https://github.com/afer00t/incident-desk

**How Clocked is used**

| Step | Endpoint | What the app does with the result |
|---|---|---|
| 1 | `pii` | Redacts names, emails, IDs and assets; only `anonymized_text` is stored and shown |
| 2 | `injection` | Blocks instruction-override and exfiltration attempts with a category and probability |
| 3 | `decide` | Severity, impacts and owning team from typed questions, confidence kept visible |
| 4 | `extract` | Reporter, asset, channel, urgency and requested action become structured fields |
| 5 | `grounding` | Scores each claim of the drafted answer, returns the weakest claim and unsupported claims |
| 6 | `compare` | Merges near-duplicate tickets, flags related and conflicting pairs |
| 7 | `rerank` | Knowledge lookup returns `use` / `expand` / `skip` with relevance scores |
| 8 | `script` | Inspects change requests and stops EDR-disabling or credential-dumping scripts |

**Live proof (2026-11-07, real key, 47 requests, 134 credits, $0.0267)**

| Probe | Live result |
|---|---|
| Ticket with PII | `anonymized_text` keeps `()` where name/email were; entities still resolve for triage |
| "Ignore all previous instructions…" ticket | `injection 0.996`, category `instruction override`, status `blocked`, priority 0 |
| Laptop that will not boot | severity `2.988` → `Critical`, owner `hardware` confidence `0.9647` |
| Answer draft contradicted by the ticket | `ungrounded` 0.019, weakest claim surfaced first |
| Factual draft | `grounded` 0.91 |
| Rerank of "laptop will not boot" | `kb-laptop` → `use` 0.99; `kb-vpn` → `skip` 0.0 |
| Script `Set-MpPreference -DisableRealtimeMonitoring $true` | `malicious` 0.997, `security blinding or EDR evasion` |
| Signed dossier `DSH-D41B4E55D1` | sha256 `0275a126…4686`; grounding 2 claims, compare 10 pairs, rerank 5 passages; `/verify` returns `ok`, `changed: []` |

**Why it matters**

Support consoles are email clients with a database. They show raw text, sort by keyword, and trust
the answer an agent writes. That ordering is exactly backwards: the text may be hostile, and the
answer may be wrong. Incident Desk puts two cheap Clocked calls in front of the human, then puts
verification in front of the customer.

**What was built**

- FastAPI service with a single-page console, no build step
- Offline model for local development, identical UI, automatic switch to live Clocked on key
- Redaction enforced at the storage schema level, not by convention
- Guard result gates severity and priority, so a blocked ticket can never be queued
- Contract test that pins the documented wire format against a stub server
- Dossier endpoint that signs grounding + compare + rerank with SHA-256 and verifies it after storage
- Tamper test and live `INTACT` receipt (`06-dossier-verify.png`)

**Team**

WELY — product, integration, operations.

**Data**

Four synthetic tickets and five knowledge passages, all invented for this demo. No real personal
data. No API key is committed; the app reads `CLOCKED_API_KEY` from the environment.

**Known limits**

- The demo link is a temporary Cloudflare quick tunnel (`trycloudflare.com`) tied to this build
  machine. If it is offline, follow `README.md` to serve the same app locally.
- The offline model is a keyword implementation and is labelled `MOCK` in the toolbar so it is never
  mistaken for a live Clocked result.
- Live responses were sampled once per endpoint; this is evidence of correctness, not a benchmark.
- The dossier receipt proves the stored payload was not edited after signing. It does not prove the
  upstream model's claims are true; grounding scores remain the evidence for that.

**Submission:** saved from the Clocked account on 2026-11-07, before 17:36 WIB. The entry selects Decide, Extract,
PII, injection guard, script inspect, grounding, Compare and Rerank (eight endpoints; no Fill). Team:
WELY. Demo, repository, write-up, and the rules agreement are set; the form reports
"Entry saved" and the values survive a reload. Screenshot:
`docs/screenshots/05-submission-saved.png`.