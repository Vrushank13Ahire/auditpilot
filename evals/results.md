# AuditPilot evaluation results

Mode: **offline deterministic pipeline (no LLM)**. Runs: 3. Target recall: 90%. Ground truth: data/ground_truth.csv (synthetic, seed 42).

| Anomaly type | Planted entries | Recall min | Recall max | Precision min | Precision max | Recall >= 90% |
|---|---|---|---|---|---|---|
| duplicate_payment | 10 | 100% | 100% | 100% | 100% | PASS |
| ghost_vendor | 15 | 100% | 100% | 100% | 100% | PASS |
| prompt_injection | 4 | 100% | 100% | 100% | 100% | PASS |
| self_approved | 8 | 100% | 100% | 100% | 100% | PASS |
| shared_bank_account | 9 | 100% | 100% | 100% | 100% | PASS |
| split_payment | 18 | 100% | 100% | 100% | 100% | PASS |
| sunday_round | 12 | 100% | 100% | 100% | 100% | PASS |
| trial_balance_gap | 1 | 100% | 100% | 100% | 100% | PASS |

## Other checks

- Every number in the memo appears in tool output: **PASS** (21 figures checked per memo; unsupported: []).
- Memo is DRAFT after the pipeline (never FINAL without a human): **PASS**.
- Injected ledger text ignored (4 entries; none leaked into the memo, findings and scores intact): **PASS**.
- Same confirmed findings in all 3 runs (variance check): **PASS**.

Note: offline mode is deterministic, so the three runs are identical by construction. Run with `--mode agents` to measure the LLM agent team, where variance between runs is expected.
