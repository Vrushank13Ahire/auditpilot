"""Pydantic schemas for findings. The model proposes likelihood and impact; code computes score and amount."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Category = Literal[
    "duplicate_payment", "split_payment", "ghost_vendor", "shared_bank_account", "self_approved",
    "approval_limit_breach", "missing_approver", "weekend_round", "trial_balance_gap", "prompt_injection",
    "ratio_anomaly", "benford",
]
Status = Literal["proposed", "confirmed", "needs_evidence", "dropped"]


class FindingDraft(BaseModel):
    """What the risk agent (LLM) is allowed to produce. No amounts and no score: code adds those.

    Every field is required (no defaults) so the structured-output schema stays simple for Gemini.
    """

    id: str = Field(description="Short unique id such as F1, F2.")
    category: Category
    title: str = Field(description="One-line title of the issue.")
    entry_ids: list[str] = Field(description="Evidence: every ledger entry_id (or TB:/FIN: id) behind the finding.")
    evidence: list[str] = Field(description="Tool results that support it: tool name plus the exact numbers returned.")
    likelihood: int = Field(ge=1, le=5, description="1-5 per the rubric.")
    impact: int = Field(ge=1, le=5, description="1-5 per the rubric.")
    rationale: str = Field(description="Why these likelihood and impact values; mention innocent explanations.")
    policy_clause: str = Field(description="Policy clause id such as 4.2, or an empty string if none applies.")


class RiskAssessment(BaseModel):
    findings: list[FindingDraft]


class Finding(BaseModel):
    """The full finding. score = likelihood x impact and amount_at_risk_inr are set by code, never by the model."""

    id: str
    category: Category
    title: str
    entry_ids: list[str] = Field(min_length=1)
    evidence: list[str]
    amount_at_risk_inr: float = 0.0
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    score: int = 0
    rationale: str
    status: Status = "proposed"
    status_reason: str = ""
    policy_clause: str = ""

    @model_validator(mode="after")
    def _compute_score(self) -> "Finding":
        self.score = self.likelihood * self.impact
        return self
