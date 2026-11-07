# LinkedIn post — People's Choice

**Draft (publish once the repo is public):**

> An inbound ticket should not be able to instruct the system that reads it.
>
> So we built **Incident Desk** — a support console that runs every ticket through Clocked before
> a human or an agent sees the content:
>
> • PII is redacted before anything is stored or forwarded
> • instruction-override attempts are isolated on the guard's evidence, never routed
> • severity, business impact and owning team are typed decisions with probabilities
> • the answer an agent drafts is checked claim by claim, and the weakest claim is surfaced
> • near-duplicate tickets are merged, knowledge lookup returns use/expand/skip, and a requested
>   change script is stopped before anyone runs it
>
> The interesting part is the ordering: protect → decide → verify. A triage score is useless if
> the ticket was a prompt injection in the first place.
>
> Demo: <DEMO_URL> · Code: <REPO_URL> · Built for the Clocked Build Challenge.

**Notes**

- Post after the repository is public; link both the demo and the write-up.
- Keep the post about the product decision, not the API. Judges read the repo for the calls.
- One post only. It is for People's Choice voting, not a judged award.