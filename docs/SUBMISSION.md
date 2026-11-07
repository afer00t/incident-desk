# Submission sheet — Clocked Build Challenge

Paste-ready fields for <https://clocked.rezolve.ai/challenge>. Fill the two placeholders after the
repository is public.

**Project name:** Incident Desk — a support console that protects, decides, then verifies.

**One-line pitch:** Every inbound ticket is redacted, screened for instruction attacks and scored
for business impact before it reaches a human; every drafted answer is then checked claim by claim
against the ticket and the knowledge base.

**Category entered:** Verify / Compare / Rerank (with Decide, Protect and Inspect in the same flow,
so the entry also demonstrates breadth across all three groups).

**Demo URL:** <DEMO_URL>

**Repository:** <REPO_URL>

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

**Team**

WELY — product, integration, operations.

**Data**

Four synthetic tickets and five knowledge passages, all invented for this demo. No real personal
data. No API key is committed; the app reads `CLOCKED_API_KEY` from the environment.

**Known limits**

- Live calls were not exercised from this network because the signup endpoint rate-limited every
  attempt; the wire contract is covered by the stub test instead.
- The offline model is a keyword implementation and is labelled `MOCK` in the toolbar so it is never
  mistaken for a live Clocked result.