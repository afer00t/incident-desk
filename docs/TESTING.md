# Verification log

All numbers below come from commands run in this workspace on 2026-11-07 (WIB) against
`http://127.0.0.1:8777`, offline model (`MOCK`). Raw output: `../evidence/repeatability.json`.

## 1. Syntax

```
$ python3 -m py_compile app.py clocked.py fixtures.py tests/test_contract.py
COMPILE_OK
```

## 2. Wire contract (stub server)

```
$ python3 tests/test_contract.py
CONTRACT OK · headers, payload keys, idempotency, credit header
```

The stub asserts:

- every request carries `Authorization: Bearer <key>`;
- one `Idempotency-Key` per logical request, reused unchanged when a 429 retries the call;
- payload keys for `pii` (`text`, `anonymize`, `threshold`), `injection` (`text`, `source`, `threshold`
  with `source` in `user|content`), `decide` (`state`, `questions`), `grounding`
  (`question`, `documents`, `answer`), `rerank` (`query`, `documents`), `script`
  (`script`, `instructions`);
- the credit/cost headers from the response are exposed to the app.

## 3. Intake repeatability

Three inputs, five runs each, same payload, same server:

| Input | Runs | HTTP | Distinct outputs |
|---|---|---|---|
| Laptop + demo deadline | 5 | 200 ×5 | 1 |
| “Ignore previous instructions” | 5 | 200 ×5 | 1 |
| Payroll ACCESS_DENIED | 5 | 200 ×5 | 1 |

First run of each case:

```
laptop    → [NAME] ([EMAIL]) … [ASSET] … High · Hardware · guard benign
attack    → Guard: injection (blocked, priority 0) · nothing routed
payroll   → Critical · Identity · ACCESS_DENIED + 09:10 UTC extracted
```

Twenty consecutive intakes with unique text (burst test) returned `200:20`, no 500s, after the
ticket id moved from a timestamp to `uuid4`.

## 4. Endpoint behaviour

| Call | Observed |
|---|---|
| `grounding` on an unsupported draft | `contradicted`, grounded `0.0`, claim listed as unsupported |
| `grounding` on “Payroll portal shows ACCESS_DENIED since 09:10 UTC” | `supported`, grounded `1.0` |
| `compare` over four tickets | one `duplicates` pair at `0.531`, rest `unrelated` |
| `rerank` “payroll portal access denied” | `kb-payroll` → `use` `0.99`, next → `expand` `0.375` |
| `script` with `Set-MpPreference -DisableRealtimeMonitoring` | `malicious` `0.99`, category `security blinding or EDR evasion` |
| `script` with `Restart-Service Spooler` | `benign` |

## 5. Layout

- 1280 px: no element crosses the viewport (`scrollWidth == innerWidth`), no zero-height widgets.
- 390 px: single-column layout (`aside` and `main` both 390 px), `scrollWidth == 390`, zero
  overflowing elements.

## 6. Live verification

Run on 2026-11-07 at 16:23 WIB against `https://clocked.rezolve.ai/clocked` with a real free-tier key
(20,000 credits, concurrency 4). Server state after the run: `requests 14`, `credits 41`,
`cost_usd 0.0082`.

| Call | Live result |
|---|---|
| `pii` | `anonymized_text` = `Hi, this is () from finance…`, entities person + email |
| `injection` | `verdict injection`, `injection 0.9961`, category `instruction override` |
| `decide` | severity `score 2.988` → `Critical`, owner `hardware` `0.9647` |
| `extract` | reporter `Priya Nair`, email, `asset ASSET-4471`, issue `will not boot` |
| `grounding` (contradictory draft) | `verdict ungrounded`, `grounded 0.019`, weakest claim returned |
| `grounding` (factual draft) | `verdict grounded`, `grounded 0.91` |
| `compare` | `pairs` with relation and probabilities (treat as unrelated at `0.9963`) |
| `rerank` | `kb-laptop` → `use` `0.99`, `kb-vpn` → `skip` `0.0` |
| `script` | `verdict malicious`, `malicious 0.997`, `security blinding or EDR evasion` |

Screen shot of the live console: `docs/screenshots/04-live-verified.png`.

The first live intake failed with a `run()` signature error; fixed, then 14 requests succeeded.
`anonymize` is not a boolean on the wire — it is the string `redact` (the API returns 422 otherwise).