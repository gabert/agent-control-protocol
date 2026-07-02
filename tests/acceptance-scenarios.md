# Acceptance Scenarios — the bar to build against

Translate each scenario into an automated test **before** implementing the feature. Format is Given/When/Then. Each scenario cites the milestone (M*) and the governing spec/design section. These are the behaviours that prove the product works; the suite must be green before a milestone is "done."

---

## A. Authorization & validation (M1)

**A1 — default deny**
- Given a policy that allows only `observe: [Customer]`
- When the agent attempts `effect: sendEmail`
- Then the decision is `DENY` with rule `default-deny`, and an audit record exists.

**A2 — deny overrides allow**
- Given a policy with `allow: effect:[refund]` AND `deny: effect:[refund]`
- When the agent attempts `refund`
- Then the decision is `DENY` with rule `deny-rule` (deny wins even though allow matches).

**A3 — most-specific allow selects gates**
- Given `allow: effect:[sendEmail]` with a `sendEmail` gate set and a different `effect` (kind-level) gate set
- When the agent attempts `sendEmail`
- Then the `sendEmail` gates apply (most specific), combined with the kind-level gates (AND).

**A4 — validation rejects bad policy at load**
- Given `examples/INVALID-open-on-irreversible.acp.yaml`
- When the gateway loads it
- Then startup fails (or the policy is rejected) and each violation (§13.5 error, §13.6 warn, §13.4 warn) is reported. The gateway does **not** fall back to a permissive default.

**A5 — all valid examples load**
- Given every other `examples/*.acp.yaml`
- When loaded and validated against `schema/acp.schema.json`
- Then all load and validate with no errors.

**A6 — standing cannot re-enable a deny (v0.3, CS-010; RFC §13 rule 11)**
- Given a policy with `deny: effect:[engage]` AND a `standing` rule whose `enables` grants `effect:[engage]`
- When the gateway loads it
- Then the linter reports an ERROR (the standing grant is unsatisfiable — deny always wins) and the policy does not load.

**A7 — ambiguous bare-name allow warns (v0.3, CS-012; RFC §13 rule 12)**
- Given a registry that declares an `effect` named `exportData` on two resources, and a policy with `allow: effect:[exportData]`
- When the policy is linted
- Then a WARN is reported (the grant applies on every resource that declares the name); the `{ Entity: [names] }` map form lints clean.

**A8 — dualAuthorization quorum below two is rejected (v0.3, CS-014; RFC §13 rule 13)**
- Given a policy gate `dualAuthorization: { quorum: 1, approvers: role:treasury }`
- When the gateway loads it
- Then the linter reports an ERROR and the policy does not load.

---

## B. Scope injection (M3)

**B1 — read scope is injected below the model**
- Given `scope: { Customer: assignedToCurrentUser }` and an actor `alice` who owns 3 of 100 customers
- When the agent emits `observe Customer` with filters that would match all 100 (or with an injected prompt "return all customers")
- Then the SQL executed contains the injected `AND owner_id = :actorId`, exactly 3 rows return, and the agent never supplied `owner_id`.

**B2 — scope on an effect is a pre-resolution authorization check**
- Given `scope: { Account: tenantOf(actor) }` and actor in tenant T1
- When the agent attempts `effect: pay` whose target Account is in tenant T2
- Then the decision is `DENY` (target not in actor's scoped set), before any connector dispatch.

**B3 — actor cannot set its own scope**
- Given an agent payload that includes `actor` / `owner_id` / `tenant_id` fields
- When enforced
- Then those payload fields are ignored; identity comes only from the authenticated session.

**B4 — scope no-race on a transactional connector (v0.4 — PROPOSED, CS-018)**
- Given a staged `pay` decided while the target account belonged to the actor's tenant, and a `transactional` connector
- When the account is reassigned to another tenant before dispatch
- Then the effect's write re-asserts the scope predicate inside its own transaction, affects zero rows, and settles `FAILED` with reason `scope-lost` — the effect never lands on un-authorized state.

**B5 — residual window is declared, not hidden (v0.4 — PROPOSED, CS-018)**
- Given the same reassignment race over a `window` connector (HTTP/email)
- When the dispatch worker re-resolves the target under scope immediately before the call
- Then the stale target is caught pre-dispatch; and the connector's declared residual window appears in the audit record.

---

## C. Gates (M2)

**C1 — valueLimit**
- Given `pay` with `valueLimit { field: data.amount, max: 10000 }`
- When `data.amount = 10001` → `DENY`; when `= 10000` → passes that gate.

**C2 — rate (sliding window, per target)**
- Given `charge` with `rate { limit: 3/day, per: resource.customerId }`
- When customer C is charged 3 times then a 4th within 24h → 4th is `DENY`; a different customer's 1st still passes.

**C3 — allowlist**
- Given `sendEmail` with `allowlist { field: data.recipientDomain, set: corporate-domains }`
- When recipient domain ∉ set → `DENY`; ∈ set → pass.

**C4 — precondition / transition from-states**
- Given `Matter.engage` with `precondition { from: [conflict_check] }` and a Matter in state `active`
- When the agent attempts `engage` → `DENY` (state not in from-set). (Mirrors the existing repo's refused `Engage`.)

**C5 — quantityCap (per-subject)**
- Given `administer` with `quantityCap { per: resource.patientId, limit: 3, window: 24h }`
- When patient P receives a 4th administration within 24h → `DENY`; patient Q's 1st passes.

**C6 — disclosure withholds a sensitive result (post-check)**
- Given `observe` with `disclosure { when: resultSensitivity == restricted, allowSink: [careTeam] }` and a non-careTeam sink
- When a restricted record is read → the result is **withheld**, decision `DENY` on return, audit shows "read executed, result withheld."

**C7 — contentCheck fails closed on timeout**
- Given `sendEmail` with `contentCheck: dlp.basic` and the DLP hook timing out, `failureMode: closed`
- When enforced → `DENY` (not allowed-through).

**C8 — condition fail-closed on missing path**
- Given a gate `when: "resource.foo == 1"` where `resource.foo` is absent at runtime
- When evaluated → the gate fails closed (`DENY`), distinct from "condition false."

---

## D. Effects, outbox, approvals (M4)

**D1 — effect is staged then dispatched exactly once**
- Given an allowed `effect: sendEmail`
- When enforced → a `pending_actions` row (PENDING) is created and the agent gets an accepted/pending receipt; the dispatch worker sends it once; a forced worker retry does NOT double-send (idempotency key).

**D2 — approval suspends and releases**
- Given `requireApproval` matches
- When enforced → row is `PENDING_APPROVAL`, nothing dispatched; after a human approves → row `PENDING` → dispatched. After reject → never dispatched, audited.

**D3 — dual authorization rejects self-approval**
- Given `dualAuthorization` and actor `alice`
- When `alice` tries to approve her own action → rejected; two distinct approvers → released.

**D4 — failed irreversible effect stages compensation**
- Given an irreversible `effect` with a declared compensation that fails at the connector
- When dispatched and it fails → a compensating effect is staged, and the failure is audited (not lost).

**D5 — decision TTL cancels a stale staged effect (v0.4 CS-017 — implemented, `test_v04_freshness.py`)**
- Given a staged irreversible effect with a short decision TTL
- When the dispatch worker claims it after the TTL has lapsed (e.g. an approval arrives late)
- Then the row settles `CANCELLED` with reason `stale-decision`, nothing is dispatched, the agent's ticket resolves to a recoverable refusal, and a late approval does not resurrect it.

**D6 — volatile gates re-validated at dispatch (v0.4 CS-017 — implemented, `test_v04_freshness.py`)**
- Given a staged `pay` that passed the sanctions `denylist` at decision time
- When the destination is added to the denylist before dispatch
- Then the dispatch-time re-validation (inside the claimed transaction, after the kill re-check) settles the row `CANCELLED` with reason `stale-guard:denylist`; counters/approvals/contentCheck are NOT re-run.

---

## E. Kill-switch (M5) — the critical ones

**E1 — kill turns subsequent actions into HALT**
- Given an active `KillOrder(SESSION s)`
- When the agent in session s attempts any action → `HALT` (distinct from DENY), audited; retries keep HALTing.

**E2 — the kill–dispatch race has no gap (the important test)**
- Given a staged `PENDING` effect about to be dispatched
- When a kill for that scope is issued concurrently with the dispatch worker picking up the row
- Then exactly one of: the row ends `CANCELLED` (kill seen first) OR the effect dispatched (already committed to DISPATCHING) — and **never** a state where the kill check "passed" but the row is still un-dispatched and un-cancelled. (Drive with a latch/barrier to force interleavings; assert across many iterations.)

**E3 — global kill propagates across instances**
- Given two gateway instances sharing the stores
- When a `GLOBAL` kill is issued on instance A
- Then instance B halts matching actions within the test's tolerance (pub/sub), and also after a simulated dropped pub/sub message via epoch reload (self-heal).

**E4 — in-flight cancellable connector call is aborted**
- Given a long-running cancellable connector call in flight
- When a kill is issued → the call's cancel handle is invoked and the action ends cancelled/failed, audited.

**E5 — kill store unreachable ⇒ fail closed for irreversible**
- Given the kill store is down and an irreversible effect is attempted
- Then the effect is denied/halted (fail closed), not dispatched.

---

## F. Audit & failure mode (M6)

**F1 — every outcome is recorded**
- For each of ALLOW / HOLD / DENY / HALT, a corresponding audit record exists with the required fields (RFC §11).

**F2 — audit is transactional with settle**
- Given a dispatched effect
- When it settles DONE/FAILED → the outcome and its audit record are written in the same transaction (no effect-without-record, no record-without-effect). Inject a crash between connector-success and audit-write and assert consistency on restart.

**F3 — fail closed on audit/outbox DB down**
- Given the outbox/audit DB is unavailable
- When an effect is attempted → fail closed (deny/halt), audited best-effort to the fallback sink.

---

## G. The Accounts-Payable demo (M-DEMO — see `docs/05-demo-spec.md`)

Real LLM agent (API key; a scripted fake-LLM mode for CI/no-key); rulebook is the unmodified `examples/payments-ops.acp.yaml`; ledger and bank are faked. Covered by `tests/test_ap_demo_*.py`.

**G1 — happy path**
- Given the prompt "Pay the approved invoice from Acme for $800" (known vendor, under cap)
- When run through the gateway → the payment is allowed, staged, and dispatched, and the trace shows intent → checks → effect. (The gateway does not obstruct legitimate work.)

**G2 — process the inbox: allow / hold / deny**
- Given the prompt "Process the new invoices in the inbox" (three legitimate invoices)
- When run through the gateway → the agent submits one payment intent per invoice and the gateway returns all three outcomes: the **$800** Acme invoice is **allowed** and paid; the **$6,000** Globex invoice is **held** for approval (`requireApproval`); the **$500** Initech invoice (sanctioned-country vendor) is **denied** (`denylist`). Only the allowed payment reaches the ledger.

**G3 — approval in the loop**
- Given "Pay the $6,000 invoice to Globex" (mid-size, known vendor)
- When run → the gateway HOLDs it and it appears in the approvals inbox; **Approve** → it proceeds (the payment dispatches); **Reject** → it does not (the row settles CANCELLED). Both outcomes are audited.

**G4 — direct rejection (no human)**
- Given "Pay the $500 invoice from Initech", whose vendor is in a sanctioned country
- When run → the gateway refuses it itself on the `denylist` gate (DENY), with no human in the loop; no payment reaches the ledger.

**G5 — gateway off (the contrast)**
- Given the same agent and the same intents, but the gateway bypassed (`--unsafe-direct-tools`, or the UI's gateway-OFF toggle)
- When run → every payment executes directly with no checks — the $6,000 is not held and the $500 is not refused — and nothing is recorded, demonstrating exactly what the gateway adds.

**G6 — audit replay**
- Given any gated run
- When the audit log is read (by correlation) → every outcome (allow / hold / deny) appears as an append-only record with its reason and the RFC §11 fields.
