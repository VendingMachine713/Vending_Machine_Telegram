from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from .db import PlatformDB
from .governance import RecommendationDecision, RecommendationGovernanceError, transition_recommendation
from .learning import LearningError, RecordedOutcome, record_outcome
from .paths import project_root


_RECOMMENDATION_TYPE = "canonical_relationship_reengagement_review"
_OPERATOR_TARGETS = {"ACCEPTED", "DISMISSED", "COMPLETED"}


class CanonicalReviewFeedbackError(RuntimeError):
    """Raised when canonical review governance or feedback input is invalid."""


def _recommendation(db: PlatformDB, recommendation_key: str) -> dict[str, Any]:
    with db.connect() as con:
        row = con.execute(
            "SELECT * FROM intelligence_recommendations WHERE recommendation_key=?",
            (recommendation_key,),
        ).fetchone()
    if row is None:
        raise CanonicalReviewFeedbackError(f"recommendation not found: {recommendation_key}")
    item = dict(row)
    if str(item.get("recommendation_type") or "") != _RECOMMENDATION_TYPE:
        raise CanonicalReviewFeedbackError("recommendation is not a canonical relationship review")
    return item


def transition_canonical_review(
    recommendation_key: str,
    target_status: str,
    *,
    actor: str = "operator",
    note: str | None = None,
    root: Path | None = None,
) -> RecommendationDecision:
    """Apply one explicit operator transition to a canonical review recommendation.

    Automatic expiry remains owned by the canonical lifecycle module. This helper
    intentionally exposes only operator review states and never executes Telegram
    actions.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    _recommendation(db, recommendation_key)
    target = target_status.upper().strip()
    if target not in _OPERATOR_TARGETS:
        raise CanonicalReviewFeedbackError(
            f"unsupported canonical operator transition: {target_status}"
        )
    try:
        return transition_recommendation(
            recommendation_key,
            target,
            actor=actor,
            note=note,
            root=root,
        )
    except RecommendationGovernanceError as exc:
        raise CanonicalReviewFeedbackError(str(exc)) from exc


def record_canonical_review_outcome(
    recommendation_key: str,
    outcome_type: str,
    *,
    value_score: float = 0,
    confidence: float = 1,
    actor: str = "operator",
    note: str | None = None,
    evidence: dict[str, Any] | None = None,
    root: Path | None = None,
) -> RecordedOutcome:
    """Record one verified outcome for a completed canonical review.

    This delegates to the existing learning store after enforcing canonical review
    identity. It records feedback only and never changes rules automatically.
    """
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    row = _recommendation(db, recommendation_key)
    if str(row.get("status") or "").upper() != "COMPLETED":
        raise CanonicalReviewFeedbackError(
            "canonical review outcomes may only be recorded after COMPLETED"
        )
    outcome_evidence = dict(evidence or {})
    try:
        recommendation_evidence = json.loads(row.get("evidence_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        recommendation_evidence = {}
    if not isinstance(recommendation_evidence, dict):
        recommendation_evidence = {}
    outcome_evidence.update(
        {
            "canonical_review": True,
            "canonical_inference_event_id": recommendation_evidence.get(
                "canonical_inference_event_id"
            ),
            "support_signature": recommendation_evidence.get("support_signature"),
        }
    )
    try:
        return record_outcome(
            recommendation_key,
            outcome_type,
            value_score=value_score,
            confidence=confidence,
            actor=actor,
            note=note,
            evidence=outcome_evidence,
            root=root,
        )
    except LearningError as exc:
        raise CanonicalReviewFeedbackError(str(exc)) from exc


def canonical_review_feedback_summary(
    *,
    root: Path | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Return passive operator feedback coverage for canonical review recommendations."""
    root = root or project_root()
    db = PlatformDB(root=root)
    db.init()
    rows = [
        row
        for row in db.recommendations(limit=max(1, int(limit)))
        if str(row.get("recommendation_type") or "") == _RECOMMENDATION_TYPE
    ]
    ids = [int(row["id"]) for row in rows]
    outcomes_by_recommendation: dict[int, dict[str, Any]] = {}
    if ids:
        placeholders = ",".join("?" for _ in ids)
        with db.connect() as con:
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='intelligence_outcomes'"
            ).fetchone()
            if exists is not None:
                outcome_rows = con.execute(
                    f"SELECT * FROM intelligence_outcomes WHERE recommendation_id IN ({placeholders})",
                    ids,
                ).fetchall()
                outcomes_by_recommendation = {
                    int(item["recommendation_id"]): dict(item) for item in outcome_rows
                }

    status_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}
    completed_without_outcome = 0
    for row in rows:
        status = str(row.get("status") or "UNKNOWN").upper()
        status_counts[status] = status_counts.get(status, 0) + 1
        outcome = outcomes_by_recommendation.get(int(row["id"]))
        if outcome is not None:
            outcome_type = str(outcome.get("outcome_type") or "UNKNOWN").upper()
            outcome_counts[outcome_type] = outcome_counts.get(outcome_type, 0) + 1
        elif status == "COMPLETED":
            completed_without_outcome += 1

    return {
        "recommendations": len(rows),
        "status_counts": status_counts,
        "recorded_outcomes": len(outcomes_by_recommendation),
        "outcome_counts": outcome_counts,
        "completed_without_outcome": completed_without_outcome,
        "operator_transition_required": True,
        "automatic_completion": False,
        "automatic_outcome_recording": False,
        "automatic_rule_change": False,
        "automatic_execution": False,
        "external_action_authority": False,
    }


def canonical_review_decision_dict(decision: RecommendationDecision) -> dict[str, Any]:
    """Small serialisable helper for admin/operator surfaces."""
    result = asdict(decision)
    result.update(
        {
            "automatic_execution": False,
            "external_action_authority": False,
        }
    )
    return result
