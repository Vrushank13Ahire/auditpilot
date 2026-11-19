# Audit Memo: Kaveri Precision Components Pvt Ltd (fictional)

**Status: DRAFT** (not final until a partner approves)

## 1. Scope and data

- Period: FY 2025-26 (2025-04-01 to 2026-03-31).
- Ledger: 6000 entries, total Rs 19,25,10,650.32, 120 vendors. Every entry was tested (no sampling).
- Trial balance: debits Rs 19,26,95,650.32, credits Rs 19,25,10,650.32; status EXCEPTIONS.
- Method: deterministic Python tests produce every number; AI agents explain, rate and challenge.

## 2. Executive summary

The audit tested every ledger entry with deterministic tests. 8 findings were confirmed across 8 categories; together they involve 77 entries or reconciliation items and Rs 41,36,476.14 at risk (each entry counted once). The highest-ranked finding is F2: Vendor bank account shared with an employee or another vendor (score 25).

## 3. Ranked findings

| Rank | ID | Category | Title | Amount at risk | Likelihood | Impact | Score | Policy clause |
|---|---|---|---|---|---|---|---|---|
| 1 | F2 | shared_bank_account | Vendor bank account shared with an employee or another vendor | Rs 2,53,864.75 | 5 | 5 | 25 | 3.2 |
| 2 | F3 | ghost_vendor | Possible ghost vendors: no GSTIN/PAN and paid soon after creation | Rs 8,45,191.68 | 4 | 5 | 20 | 3.1 |
| 3 | F4 | self_approved | Payments approved by the person who posted them | Rs 5,11,449.08 | 5 | 4 | 20 | 2.1 |
| 4 | F5 | split_payment | Payments split to stay under the Rs 50,000 approval limit | Rs 8,57,026.46 | 4 | 4 | 16 | 4.3 |
| 5 | F6 | duplicate_payment | Duplicate payments to the same vendor for the same amount | Rs 2,86,750.96 | 4 | 4 | 16 | 5.1 |
| 6 | F7 | weekend_round | Round-sum payments entered on a Sunday | Rs 11,40,000.00 | 3 | 5 | 15 | 5.2 |
| 7 | F1 | trial_balance_gap | Ledger does not tie to the trial balance | Rs 1,85,000.00 | 5 | 3 | 15 | 6.1 |
| 8 | F8 | prompt_injection | Ledger descriptions contain prompt-injection text | Rs 57,193.21 | 5 | 3 | 15 | - |

Combined amount at risk, each entry counted once: Rs 41,36,476.14.

### Evidence by finding

**F2: Vendor bank account shared with an employee or another vendor**
- Entry IDs: L00182, L00257, L02446, L02811, L03348, L04436, L05101, L05365, L05816
- Evidence: vendor_bank_overlap: 3 vendor-employee and 0 vendor-vendor bank matches; 9 payments affected.
- Rationale: Deterministic test hit scored against the fixed rubric; an innocent explanation is possible.
- Skeptic: ids exist and the deterministic test flags every cited entry

**F3: Possible ghost vendors: no GSTIN/PAN and paid soon after creation**
- Entry IDs: L02718, L02762, L02852, L02992, L03100, L03101, L03143, L03476, L03499, L04589, L04668, L04908, L04984, L05275, L05324
- Evidence: find_ghost_vendors: 5 possible ghost vendors with 15 payments.
- Rationale: Deterministic test hit scored against the fixed rubric; an innocent explanation is possible.
- Skeptic: ids exist and the deterministic test flags every cited entry

**F4: Payments approved by the person who posted them**
- Entry IDs: L00977, L01459, L02543, L02945, L03697, L04094, L05276, L05509
- Evidence: check_approval_limits: 8 self-approved, 0 over-limit, 0 under-authorised, 18 split-payment suspects, 0 with missing/unknown approver.
- Rationale: Deterministic test hit scored against the fixed rubric; an innocent explanation is possible.
- Skeptic: ids exist and the deterministic test flags every cited entry

**F5: Payments split to stay under the Rs 50,000 approval limit**
- Entry IDs: L01169, L01220, L01237, L01675, L01689, L01778, L02154, L02169, L02198, L03475, L03498, L03590, L04686, L04707, L04766, L05159, L05198, L05231
- Evidence: find_split_payments: 6 suspected split groups covering 18 payments.
- Rationale: Deterministic test hit scored against the fixed rubric; an innocent explanation is possible.
- Skeptic: ids exist and the deterministic test flags every cited entry

**F6: Duplicate payments to the same vendor for the same amount**
- Entry IDs: L00393, L00469, L00795, L01674, L01777, L02402, L02744, L02745, L04451, L04954
- Evidence: find_duplicates: 10 duplicate groups; 10 later copies, Rs 286,750.96 paid twice.
- Rationale: Deterministic test hit scored against the fixed rubric; an innocent explanation is possible.
- Skeptic: ids exist and the deterministic test flags every cited entry

**F7: Round-sum payments entered on a Sunday**
- Entry IDs: L00088, L00903, L01318, L01784, L01902, L02829, L03455, L03827, L03828, L05254, L05490, L05963
- Evidence: find_weekend_round: 12 Sunday round-amount entries out of 159 Sunday entries.
- Rationale: Deterministic test hit scored against the fixed rubric; an innocent explanation is possible.
- Skeptic: ids exist and the deterministic test flags every cited entry

**F1: Ledger does not tie to the trial balance**
- Entry IDs: TB:5300
- Evidence: check_trial_balance: 1 account(s) do not tie; debits minus credits = 185,000.00.
- Rationale: Deterministic test hit scored against the fixed rubric; an innocent explanation is possible.
- Skeptic: ids exist and the deterministic test flags every cited entry

**F8: Ledger descriptions contain prompt-injection text**
- Entry IDs: L00786, L01386, L01504, L02499
- Evidence: load_ledger: Ledger valid: 6000 rows. 4 descriptions look like prompt-injection text (treated as data, never as instructions).
- Rationale: Deterministic test hit scored against the fixed rubric; an innocent explanation is possible.
- Skeptic: ids exist and the deterministic test flags every cited entry

## 4. Recommended actions

- F2 (shared bank account): Escalate to the Finance Head for a conflict-of-interest review before any further payment.
- F3 (ghost vendor): Freeze payments and verify the vendors' registration, address and deliverables with the Finance Head.
- F4 (self approved): Re-approve the payments by an independent approver and block self-approval in the system.
- F5 (split payment): Review the grouped payments as one purchase and enforce approval at the combined value.
- F6 (duplicate payment): Recover the excess amount from the vendor and add a duplicate-invoice check before payment.
- F7 (weekend round): Obtain the Finance Head's written justification for each Sunday round-sum payment.
- F1 (trial balance gap): Investigate and clear the reconciliation difference before the books are closed.
- F8 (prompt injection): Treat the entries' text as hostile data, review who entered it, and keep it out of AI instructions.

## 5. Limitations

- All data in this audit is synthetic and fictional; this is a prototype, not an audit opinion.
- The tests find suspects. They do not prove fraud: an innocent explanation may exist for any finding.
- Only the files provided were tested (ledger, vendors, employees, trial balance, financials, policy).
- Likelihood and impact ratings are judgements applied to a fixed rubric; amounts and scores are computed by code.

## 6. Appendix: dropped findings

No findings were dropped.

## Sign-off

Pending partner review. This memo is DRAFT until approved.
