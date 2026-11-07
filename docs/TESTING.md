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

## 6. Not verified

- Live Clocked calls: no API key was available while this was built (signup endpoint returned
  `Too many attempts. Please wait before trying again.`). The stub proves the wire contract; the
  real server has not been exercised from this network.
- Concurrency above 1: the free tier allows one concurrent request, and the app makes sequential
  calls per intake.