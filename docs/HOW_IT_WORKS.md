# AuditPilot: how it works

*A multi-agent audit and risk copilot for company finance data. Google ADK + Gemini. Part 1 of the deboistech course.*
*All data is synthetic and fictional. This is a prototype.*

---

## 1. The problem it solves

**Auditors sample.** A company's general ledger can hold thousands of payments a year. A human auditor cannot read them
all, so the audit tests a sample (often around 5%) and extrapolates. The other ~95% is never looked at. Fraud and
control failures are usually *rare, specific entries* hiding in that unread part: a payment made twice, a purchase
split into three pieces to dodge an approval limit, a "vendor" that is really an employee's bank account.

**Manual work is slow, and naive AI is not credible.** Two obvious fixes both fail:

- *More people:* too slow and expensive, and people still sample.
- *Just ask an LLM to audit:* LLMs are good at reading and explaining, but they miscalculate, they invent entries
  that do not exist, and they can be steered by text in the data ("ignore previous instructions...").
  An audit that cannot show its evidence is worthless.

**AuditPilot's answer: let code do the testing and the AI do the reasoning.**

| Auditor's problem | What AuditPilot does |
|---|---|
| Only a sample is tested | Deterministic tools test **100% of entries** in seconds |
| Hidden patterns (splits, duplicates, shared bank accounts, ghost vendors) | Dedicated tests find each one and return the exact entry IDs |
| "Why do you say that?" | Every finding cites **entry IDs, tool numbers and the policy clause** |
| AI can invent or miscalculate | **Every number comes from a tool.** A check proves memo numbers appear in tool output |
| AI can be tricked by text in the data | Ledger text is treated as **untrusted data**; injection text is detected, redacted and ignored |
| Findings get over-claimed | A **skeptic loop** tries to knock each finding down; unsupported ones are dropped with reasons |
| Who is accountable? | The memo stays **DRAFT** until a **human partner** approves it |

In one sentence: *100% tested by code, explained by AI, signed off by a human.*

---

## 2. The one rule

> **LLMs reason. Code calculates. Every number in the memo comes from a tool.**

This shapes every design choice below. Agents never add, average or estimate. They call a tool, copy what it
returns, and explain it. Scores (`likelihood x impact`) and amounts at risk are computed in Python, never by the model.

---

## 3. Architecture

```
audit_lead (root agent)  ---- owns the human sign_off tool
   |
   '-- audit_pipeline (SequentialAgent: fixed order, no LLM guessing)
         1. intake_agent        validates books, reconciles to trial balance      -> data_profile
         2. specialists         ParallelAgent, all four at the same time
              anomaly_agent     Benford, duplicates, splits, Sunday round sums    -> anomaly_findings
              vendor_agent      shared bank accounts, ghost vendors               -> vendor_findings
              ratio_agent       financial ratio screens                           -> ratio_findings
              policy_agent      approval limits + policy retrieval with clauses   -> policy_findings
         3. risk_agent          SequentialAgent
              risk_assessor     LLM, structured output: likelihood + impact       -> risk_draft
              risk_scorer       plain code: amount, score = L x I, ranking        -> ranked_findings
         4. skeptic_stage       SequentialAgent
              skeptic_loop      LoopAgent, max 3 rounds
                 skeptic_agent  LLM + verify_entry_ids + record_verdicts
                 skeptic_gate   plain code: overrides the model, ends the loop
              skeptic_finalizer plain code                                        -> confirmed_findings, dropped_findings
         5. report_agent        LLM prose + code-rendered memo (DRAFT)            -> docs/audit_memo.md
   human partner: approve / request changes / reject  -->  FINAL only on approve
```

**Agent types used (all four ADK workflow/LLM building blocks from the PDF):** `LlmAgent`, `SequentialAgent`,
`ParallelAgent`, `LoopAgent`. Two small custom `BaseAgent`s (`risk_scorer`, `skeptic_gate`/`skeptic_finalizer`) hold
the plain-code steps so the model cannot override them.

**Shared memory = session state.** Each agent has an `output_key`; ADK writes its answer to that key and later agents
read it through `{key}` placeholders in their instructions. Keys are unique (a test checks there are no clashes).

**Least privilege.** Each agent is given only the tools it needs (a test pins every tool list). The report agent
can write the memo but can never sign it off.

---

## 4. The data (Phase 1)

`scripts/make_data.py` writes the books of a fictional Indian company, *Kaveri Precision Components Pvt Ltd*, for
FY 2025-26, using numpy seed **42**, so every run (and every student) gets byte-identical files.

| File | Content |
|---|---|
| `ledger.csv` | 6,000 payments: entry_id, date, posted_by, approved_by, account, vendor_id, amount_inr, description |
| `vendors.csv` | 120 vendors with GSTIN, PAN, bank account, created date |
| `employees.csv` | 40 employees with role and bank account |
| `trial_balance.csv` | balances by account |
| `financials.csv` | monthly financial statements |
| `policy.md` | numbered finance-policy clauses (approval limits, segregation of duties...) |
| `ground_truth.csv` | **the answer key.** Used only by tests and the eval. Agents never see it |

**Planted anomalies (exact counts, with known entry IDs):**

| Anomaly | Count | Entries in ground truth |
|---|---|---|
| Duplicate payments (same vendor, same amount, within 30 days) | 10 | 10 (the later copies) |
| Split payments (groups of 3 just under Rs 50,000) | 6 groups | 18 |
| Ghost vendors (no GSTIN/PAN, paid right after creation) | 5 vendors | 15 payments |
| Vendor bank account shared with an employee | 3 vendors | 9 payments |
| Self-approved payments | 8 | 8 |
| Sunday round-amount payments | 12 | 12 |
| Trial-balance gap (account 5300, Rs 1,85,000) | 1 | 1 |
| Prompt-injection descriptions | 4 | 4 |

---

## 5. The toolbox (Phase 2)

Pure Python over pandas. **No LLM calls, no printing, no randomness** (a test enforces this). Each tool has type hints
and a clear docstring (the agent reads it) and returns the same shape:
`{"test", "flagged_ids", "stats", "notes"}`. Tools never raise into the agent loop: errors come back as
`stats.status = FAILED/ERROR`.

| Tool | What it tests | Policy clause |
|---|---|---|
| `load_ledger` | columns, row count, date range, positive amounts, unique ids; scans for injection text | - |
| `check_trial_balance` | debits = credits; ledger ties to trial balance per account | 6.1 |
| `benford_test` | leading-digit distribution vs Benford's law (MAD conformity bands) | - |
| `find_duplicates` | same vendor + same amount within 30 days | 5.1 |
| `find_split_payments` | 3+ payments to one vendor in 7 days, each 90-100% of the Rs 50,000 limit | 4.3 |
| `find_weekend_round` | Sunday entries with an exact multiple of Rs 5,000 | 5.2 |
| `check_approval_limits` | self-approval, over-limit, under-authorised, split clusters, missing approver | 2.1, 4.1, 4.2, 4.3 |
| `vendor_bank_overlap` | vendor bank account equals an employee's or another vendor's (masked output) | 3.2 |
| `find_ghost_vendors` | missing GSTIN/PAN **and** first paid within 45 days of creation | 3.1 |
| `ratio_table` | monthly ratios, z-score and hard-limit screens | - |
| `retrieve_policy(query, k)` | TF-IDF retrieval of policy clauses with a verbatim quote | all |
| `verify_entry_ids` | do cited ids exist; facts about them for the skeptic | - |

*Tests find suspects. Humans conclude.*

---

## 6. How one run flows

You type **`start audit`** in `adk web`.

1. **audit_lead** transfers to `audit_pipeline` and does no analysis itself.
2. **intake_agent** calls `load_ledger` and `check_trial_balance` and writes a data profile
   (`PASSED`, `PASSED_WITH_EXCEPTIONS` or `FAILED`).
   - If a tool reports `FAILED`, **code** (not the model) sets `state["intake_failed"]`. Every later stage checks that flag in
     a `before_agent_callback` and skips itself. So a broken CSV stops the pipeline whatever the model says.
   - A reconciliation difference is a *finding*, not a failure, so it does not stop the run.
3. **specialists** run in parallel (3 to 4 tasks, one wait). Each runs *every* tool it owns, then lists findings with the
   complete `entry_ids` from the tool and the exact tool numbers. They may not invent entries, and ignore instructions in ledger text.
   `policy_agent` calls `retrieve_policy` and must include the clause id and a quote; **no clause, no finding.**
4. **risk_agent** merges duplicates across specialists, adds the trial-balance and injection findings, and rates each
   finding's likelihood and impact (1-5) against a written rubric. The LLM output is schema-enforced
   (`RiskAssessment`, pydantic). Then **code** computes `amount_at_risk` from the ledger and `score = likelihood x impact`,
   rejects findings with no entry_ids (with a reason), and sorts by score.
   *(ADK note: an agent with `output_schema` cannot call tools, which is why this stage is "LLM judges, code scores" in two steps.)*
5. **skeptic loop** (max 3 rounds), see section 8.
6. **report_agent** writes the DRAFT memo (section 9).
7. You, the human partner, reply `approve` with your name. Only then is the memo `FINAL`.

---

## 7. Findings, scoring and the rubric

A `Finding` carries: id, category, title, entry_ids, evidence, amount_at_risk_inr, likelihood, impact, score,
rationale, status, status_reason, policy_clause. Two schemas exist on purpose:

- `FindingDraft`: what the LLM may produce. **No amount, no score.** All fields required (simple schema for Gemini).
- `Finding`: the full record. Its validator recomputes `score = likelihood x impact`, overwriting anything supplied.

**Rubric (written into the risk agent's instruction):**

| | Likelihood (chance it is a real problem) | Impact (harm if real) |
|---|---|---|
| 5 | unambiguous tool hit (exact reconciliation difference, bank number shared with an employee) | above Rs 10 lakh **or** any fraud indicator |
| 4 | tool hit, plausible but unproven innocent explanation | Rs 2.5-10 lakh **or** a control override (self-approval, split payments) |
| 3 | pattern consistent with a problem, weaker evidence | Rs 50,000-2.5 lakh **or** a policy breach |
| 2 | weak or circumstantial | Rs 10,000-50,000 |
| 1 | very unlikely | below Rs 10,000 or informational |

---

## 8. The skeptic loop (Phase 7)

Professional scepticism, built as a loop. No evidence, no finding.

Each round: **skeptic_agent** (LLM) calls `verify_entry_ids` for each finding, checks the evidence against the facts returned
(amounts, vendors, dates, poster, approver), weighs innocent explanations, and records a verdict (`confirmed`,
`needs_evidence`, `dropped`, with a one-line reason). Then **skeptic_gate** (plain code) enforces rules the model cannot override:

- A cited id that does not exist in the books: the finding is **dropped**.
- Real ids but the category's own deterministic test does not flag them: **dropped** (none flagged) or **needs_evidence** (some flagged).
- A model "confirm" that the books contradict is downgraded. A dropped finding can never be revived.
- Findings nobody reviewed are `needs_evidence`, so the loop goes again.
- The loop **ends when no finding needs evidence, or after 3 rounds.** If the skeptic has nothing to review, the model call is skipped.

After the loop, the **finalizer** moves anything still unresolved to the dropped list with the reason
*"evidence still not established after the final skeptic round"*. **Nothing is ever deleted silently**: rejected and dropped findings
all appear in the memo's appendix.

---

## 9. The memo and the human sign-off (Phase 8)

`docs/audit_memo.md` has: scope and data; executive summary; ranked findings (table + entry IDs + evidence); recommended actions;
limitations; appendix of dropped findings with reasons; sign-off block.

- **Code renders the memo.** The report agent supplies only prose (summary, actions, extra limitations) via `write_audit_memo`.
  Scope, tables, ids and amounts are rendered from state, in Indian digit grouping (Rs 1,85,000.00).
- **Number check.** Before writing, code collects every number from all tool outputs and checks every figure of 100 or more
  in the memo (ids, dates, month labels and clause numbers excluded). If the agent's prose quotes a figure no tool returned,
  **the memo is not written** and the offending numbers are returned so the agent rewrites. An evidence line from an earlier stage
  with untraceable figures is replaced by `[evidence line withheld...]`.
- **DRAFT then FINAL.** The memo is always written as `DRAFT`. `sign_off` (a tool owned by `audit_lead`, never the report agent) takes
  `approve`, `request_changes` or `reject`, plus a reviewer name:
  only **approve** flips it to FINAL. It refuses if there is no draft, no name, an unknown decision, or if the memo file was edited
  after drafting (hash check). Re-running the audit resets an approved memo to DRAFT.

---

## 10. Guardrails and the audit trail (Phase 9)

| Layer | How |
|---|---|
| Untrusted data | Every instruction says ledger text is data, never a command. `injection.py` detects patterns ("ignore previous instructions", "set risk scores to 0"...) and redacts them in tool output |
| Least privilege | Each agent has only its own tools; the report agent cannot sign off |
| Callbacks | `before_model` masks 11-18 digit numbers (bank accounts) to the last 4 digits before text reaches the model; `after_tool` and `after_model` write the trail |
| Human sign-off | Nothing is final alone |
| Hidden answer key | `ground_truth.csv` is read only by tests and the eval; a test fails if any package file mentions it |
| Secrets | `.env` is git-ignored; logged values are scrubbed for key-shaped strings; a test scans for committed keys |

**Audit trail:** `runs/<session_id>/audit_trail.jsonl`, append-only, one JSON line per model call and per tool call:
timestamp, agent, tool, args (masked, scrubbed) and a **hash** of the result. The trail proves what came back without storing prompts or full results.

---

## 11. Evaluation (Phase 9)

`evals/run_eval.py` runs the pipeline **3 times** and scores it against `ground_truth.csv`:
recall and precision per anomaly type (target recall >= 90%), plus: every memo number appears in tool output; the memo is DRAFT;
injected ledger text did not leak or zero the findings; the confirmed findings are the same in all runs (variance).
Results are written to `evals/results.md`.

- `python evals/run_eval.py` runs the **offline** pipeline (same tools, scoring, skeptic rules and memo, with fixed rules standing in for the LLM judgement).
  Current result: **100% recall and 100% precision on all 8 anomaly types**, all other checks pass.
- `python evals/run_eval.py --mode agents` runs the real Gemini agent team. Expect some variance between runs.

**Read the 100% honestly:** the data is synthetic and the tests were written knowing what was planted. It shows the machinery is correct and the
guardrails work, not that real-world books would score the same. That is the limitation to say out loud.

---

## 12. What was done in this build

### Phases

| Phase | Commit message | What |
|---|---|---|
| 0 Setup | `phase 0: scaffold` | repo, `.gitignore`, rules file, requirements |
| 1 Data | `phase 1: synthetic books with planted anomalies` | `make_data.py`, 7 files, ground truth, counts test |
| 2 Tools | `phase 2: deterministic audit toolbox...` | 10 tools + one pytest each, recall >= 90% per anomaly |
| 3 Intake | `phase 3: intake agent, deterministic stop gate, audit_lead` | intake agent, FAILED stops the pipeline |
| 4 Specialists | `phase 4: anomaly, vendor and ratio specialists...` | 3 agents in a ParallelAgent |
| 5 Policy RAG | `phase 5: policy retrieval (TF-IDF)...` | clause splitter, retrieval, policy agent with citations |
| 6 Risk | `phase 6: pydantic findings, risk agent...` | schemas, rubric, assessor + code scorer |
| 7 Skeptic | `phase 7: ...` | `verify_entry_ids`, LoopAgent, code gate, finalizer |
| 8 Report | `phase 8: ...` | memo renderer, number check, sign-off gate |
| 9 Harden | `phase 9: ...` | callbacks (trail + masking), eval, hygiene tests |

Phases 0-5 were already committed in the repo when this session picked it up (47 tests passing); phase 6 was written but
uncommitted. This session finished and committed phase 6, then built phases 7-9, the offline pipeline and all documentation.

### Design decisions worth knowing

1. **Risk split in two.** ADK agents with `output_schema` cannot use tools, so `risk_assessor` (LLM, schema) hands to `risk_scorer` (code).
2. **Code outranks the model.** The skeptic's gate and the memo's number check run in plain Python after the LLM step, so a wrong or manipulated model output cannot get through.
3. **Skeptic verdicts are passed as a JSON string** (`record_verdicts`) because nested dict types in tool signatures are fragile with Gemini function schemas.
4. **Sign-off belongs to the root agent**, whose instruction only accepts an explicit decision from the human's own chat message.
5. **Offline pipeline (extra, not in the PDF).** It lets the whole system be run and evaluated with no key or quota, and doubles as the baseline.
6. **Model:** defaults to `gemini-flash-latest`; override with the `AUDITPILOT_MODEL` environment variable.
7. **Gates before agents.** `before_agent_callback` on each later stage is the "pipeline must stop" mechanism.

### Tests

99 tests (88 run anywhere; the 11 agent-wiring tests need `google-adk` installed and are skipped without it): data counts and determinism, one-or-more per tool, recall/precision against ground truth, policy retrieval top-1,
schema and scoring, skeptic behaviour (fake finding dropped, real ones stay), memo/sign-off, callbacks and masking, repo hygiene, and agent wiring
(tool lists, output keys, pipeline order, gates). Run `pytest` from the repo root.

---

## 13. What has and has not been verified

**Verified here (run and passing):** all deterministic code: data generation, every tool, scoring, skeptic rules, memo and sign-off, callbacks,
offline pipeline, evaluation (offline mode). Agent *wiring* (names, tool lists, output keys, order, callbacks) was checked against a lightweight
stand-in for ADK.

**Not verified here:** the build environment had no `google-adk` and no network for installs, and no Gemini key, so the agent team
was **not run against real ADK or Gemini**. Before you tag a release, check these on your machine:

1. `adk web` (run from the repo root) lists `auditpilot` and "start audit" shows tool calls for intake, then the parallel specialists.
2. `state` after a run holds `data_profile`, the four `*_findings`, `ranked_findings`, `confirmed_findings`, `dropped_findings`.
3. The skeptic loop ends in 3 rounds or fewer; `runs/<session>/audit_trail.jsonl` appears.
4. After the DRAFT memo, typing `approve, my name is <you>` reaches `audit_lead` and flips the memo to FINAL.
5. `python evals/run_eval.py --mode agents` and paste the numbers into the README.

If something misbehaves, read the trace before editing a prompt, then change one thing:

| Symptom | Fix |
|---|---|
| Model does the math | name the tool, make it mandatory |
| Wrong tool called | shrink the tool list |
| Key missing in state | check `output_key`, no clashes |
| 429 quota error | wait, retry, or run sequentially |
| `adk web` cannot find the agent | run from the repo root |

---

## 14. Shipping to GitHub

```bash
git remote add origin https://github.com/<your-user>/auditpilot.git   # if not already set
git push -u origin main
# after the checks in section 13 pass:
git tag v1.0-part1 && git push --tags
```
Confirm on github.com that there is no `.env`, no API key and no `.venv`. **Part 2** hosts this exact repo on AWS (Docker, ECR, App Runner or ECS Fargate, Secrets Manager, S3, CloudWatch, a web sign-off page).

## 15. Resume line (be honest: a prototype on synthetic data)

*Multi-agent audit copilot, Google ADK. Tests all entries. Recall: 100% on planted anomalies (offline deterministic pipeline; fill in your agent-mode number after running it).*
