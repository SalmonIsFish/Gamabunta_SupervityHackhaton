# app/services/insight_engine.py
"""
Insight Generation Engine — statistical, no-LLM first pass.

Aggregates recent audit-log activity (policy evaluations + workbench
resolutions) into Insight rows: patterns, anomalies, and recommendations.
See docs/command-center-guide.md, "AI Insights — The Visibility Layer".

This is intentionally simple — counts and rate comparisons, not ML or an LLM
call. It's triggered manually (POST /ai/insights/generate) rather than
scheduled, matching the hackathon scaffold's current scope. Each call appends
fresh rows; it does not deduplicate against insights from a previous run.
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.audit import AuditLog
from ..models.insight import Insight, InsightSeverity, InsightType
from ..models.policy import Policy, PolicyStatus
from ..models.work_item import WorkItem

log = logging.getLogger(__name__)

WINDOW_DAYS = 30
MIN_SAMPLE = 3  # minimum evaluations before a rate/absence is trustworthy
SPIKE_FACTOR = 2.0  # recent count must be at least this many times the baseline
MIN_SPIKE_COUNT = 3  # minimum absolute recent count before flagging a spike

GENERATED_BY = "insight_engine"


def _policy_evaluate_logs(db: Session, window_start: datetime, domain: Optional[str]) -> list[AuditLog]:
    """Fetch policy.evaluate audit rows in the window, optionally scoped to one domain."""
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.action == "policy.evaluate")
        .filter(AuditLog.timestamp >= window_start)
        .order_by(AuditLog.timestamp.asc())
        .all()
    )
    if domain:
        logs = [entry for entry in logs if (entry.extra_data or {}).get("domain") == domain]
    return logs


def _derive_patterns(db: Session, evaluations_by_domain: Counter, match_counts: Counter) -> list[Insight]:
    """e.g. 'Policy X matched 80% of 12 evaluations.'"""
    if not match_counts:
        return []

    policies_by_id = {p.id: p for p in db.query(Policy).filter(Policy.id.in_(match_counts.keys())).all()}
    insights: list[Insight] = []

    for policy_id, match_count in match_counts.items():
        policy = policies_by_id.get(policy_id)
        if not policy:
            continue
        total = evaluations_by_domain.get(policy.domain, 0)
        if total < MIN_SAMPLE:
            continue

        rate = match_count / total
        insights.append(
            Insight(
                title=f"Policy '{policy.name}' matched {rate:.0%} of evaluations",
                description=(
                    f"Policy '{policy.name}' (domain '{policy.domain}') matched {match_count} of {total} "
                    f"evaluations in the last {WINDOW_DAYS} days."
                ),
                insight_type=InsightType.PATTERN.value,
                severity=InsightSeverity.INFO.value,
                confidence=min(1.0, total / (MIN_SAMPLE * 5)),
                extra_data={
                    "policy_id": policy.id,
                    "domain": policy.domain,
                    "match_count": match_count,
                    "total_evaluations": total,
                    "match_rate": rate,
                },
                related_policy_id=policy.id,
                generated_by=GENERATED_BY,
            )
        )
    return insights


def _derive_anomalies(db: Session, logs: list[AuditLog], window_start: datetime, now: datetime) -> list[Insight]:
    """e.g. 'Policy X's trigger rate spiked vs its recent baseline' / 'conflicts spiked in domain Y.'"""
    if not logs:
        return []

    midpoint = window_start + (now - window_start) / 2
    baseline_logs = [entry for entry in logs if entry.timestamp < midpoint]
    recent_logs = [entry for entry in logs if entry.timestamp >= midpoint]

    insights: list[Insight] = []

    # Per-policy match-rate spikes
    baseline_matches = Counter(
        pid for entry in baseline_logs for pid in (entry.extra_data or {}).get("matched_policy_ids") or []
    )
    recent_matches = Counter(
        pid for entry in recent_logs for pid in (entry.extra_data or {}).get("matched_policy_ids") or []
    )
    spiking_policy_ids = [
        pid
        for pid, recent_count in recent_matches.items()
        if recent_count >= MIN_SPIKE_COUNT
        and baseline_matches.get(pid, 0) >= 1
        and recent_count >= baseline_matches[pid] * SPIKE_FACTOR
    ]
    if spiking_policy_ids:
        policies_by_id = {p.id: p for p in db.query(Policy).filter(Policy.id.in_(spiking_policy_ids)).all()}
        for pid in spiking_policy_ids:
            policy = policies_by_id.get(pid)
            if not policy:
                continue
            baseline_count = baseline_matches[pid]
            recent_count = recent_matches[pid]
            insights.append(
                Insight(
                    title=f"Policy '{policy.name}' trigger rate spiked",
                    description=(
                        f"Policy '{policy.name}' matched {recent_count} times in the most recent half of "
                        f"the {WINDOW_DAYS}-day window, up from {baseline_count} in the earlier half."
                    ),
                    insight_type=InsightType.ANOMALY.value,
                    severity=InsightSeverity.WARNING.value,
                    confidence=min(1.0, recent_count / (MIN_SPIKE_COUNT * 3)),
                    extra_data={"policy_id": pid, "baseline_count": baseline_count, "recent_count": recent_count},
                    related_policy_id=pid,
                    generated_by=GENERATED_BY,
                )
            )

    # Per-domain policy-conflict rate spikes
    baseline_conflicts = Counter(
        (entry.extra_data or {}).get("domain")
        for entry in baseline_logs
        if (entry.extra_data or {}).get("verdict") == "blocked_pending_review"
    )
    recent_conflicts = Counter(
        (entry.extra_data or {}).get("domain")
        for entry in recent_logs
        if (entry.extra_data or {}).get("verdict") == "blocked_pending_review"
    )
    for dom, recent_count in recent_conflicts.items():
        baseline_count = baseline_conflicts.get(dom, 0)
        if recent_count >= MIN_SPIKE_COUNT and baseline_count >= 1 and recent_count >= baseline_count * SPIKE_FACTOR:
            insights.append(
                Insight(
                    title=f"Policy conflicts spiked in domain '{dom}'",
                    description=(
                        f"{recent_count} policy conflicts were routed to the Workbench in the most recent "
                        f"half of the {WINDOW_DAYS}-day window for domain '{dom}', up from {baseline_count} before."
                    ),
                    insight_type=InsightType.ANOMALY.value,
                    severity=InsightSeverity.WARNING.value,
                    confidence=min(1.0, recent_count / (MIN_SPIKE_COUNT * 3)),
                    extra_data={"domain": dom, "baseline_count": baseline_count, "recent_count": recent_count},
                    generated_by=GENERATED_BY,
                )
            )

    return insights


def _derive_recommendations(
    db: Session,
    domain: Optional[str],
    evaluations_by_domain: Counter,
    match_counts: Counter,
    window_start: datetime,
    logs: list[AuditLog],
) -> list[Insight]:
    """e.g. 'Policy X has 0 matches — consider archiving' / 'N items of type Y took longest to resolve.'"""
    insights: list[Insight] = []

    # Zero-trigger active policies
    query = db.query(Policy).filter(Policy.status == PolicyStatus.ACTIVE.value)
    if domain:
        query = query.filter(Policy.domain == domain)
    for policy in query.all():
        total = evaluations_by_domain.get(policy.domain, 0)
        if total < MIN_SAMPLE:
            continue
        if match_counts.get(policy.id, 0) == 0:
            insights.append(
                Insight(
                    title=f"Policy '{policy.name}' has 0 matches in {WINDOW_DAYS} days",
                    description=(
                        f"Policy '{policy.name}' (domain '{policy.domain}') did not match any of {total} "
                        f"evaluations in the last {WINDOW_DAYS} days."
                    ),
                    insight_type=InsightType.RECOMMENDATION.value,
                    severity=InsightSeverity.INFO.value,
                    confidence=min(1.0, total / (MIN_SAMPLE * 5)),
                    suggested_action="Review this policy's condition or archive it",
                    extra_data={"policy_id": policy.id, "domain": policy.domain, "total_evaluations": total},
                    related_policy_id=policy.id,
                    generated_by=GENERATED_BY,
                )
            )

    # Slowest-resolving exception type
    workbench_ids_for_domain = None
    if domain:
        workbench_ids_for_domain = {
            wid for entry in logs if (wid := (entry.extra_data or {}).get("workbench_item_id"))
        }

    resolved_query = db.query(WorkItem).filter(WorkItem.resolved_at.isnot(None)).filter(
        WorkItem.resolved_at >= window_start
    )
    if workbench_ids_for_domain is not None:
        resolved_query = resolved_query.filter(WorkItem.id.in_(workbench_ids_for_domain))
    resolved_items = resolved_query.all()

    if len(resolved_items) >= 2:
        durations_by_type: dict[str, list[float]] = defaultdict(list)
        for item in resolved_items:
            durations_by_type[item.exception_type].append((item.resolved_at - item.created_at).total_seconds())

        avg_by_type = {t: sum(seconds) / len(seconds) for t, seconds in durations_by_type.items()}
        slowest_type = max(avg_by_type, key=avg_by_type.get)
        avg_hours = avg_by_type[slowest_type] / 3600
        count = len(durations_by_type[slowest_type])

        insights.append(
            Insight(
                title=f"'{slowest_type}' exceptions take the longest to resolve",
                description=(
                    f"{count} workbench item(s) of type '{slowest_type}' took an average of {avg_hours:.1f} "
                    f"hour(s) to resolve in the last {WINDOW_DAYS} days — the slowest of all exception types "
                    f"resolved in that window."
                ),
                insight_type=InsightType.RECOMMENDATION.value,
                severity=InsightSeverity.INFO.value,
                confidence=min(1.0, count / (MIN_SAMPLE * 2)),
                suggested_action=f"Review the '{slowest_type}' resolution workflow",
                extra_data={"exception_type": slowest_type, "avg_resolution_hours": avg_hours, "sample_count": count},
                generated_by=GENERATED_BY,
            )
        )

    return insights


def generate_insights(db: Session, domain: Optional[str] = None) -> list[Insight]:
    """
    Derive fresh Insight rows from recent audit-log activity.

    Optionally scoped to a single domain; otherwise looks across all domains
    that have been evaluated in the last WINDOW_DAYS days.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=WINDOW_DAYS)

    logs = _policy_evaluate_logs(db, window_start, domain)
    evaluations_by_domain = Counter((entry.extra_data or {}).get("domain") for entry in logs if entry.extra_data)
    match_counts = Counter(
        pid for entry in logs for pid in (entry.extra_data or {}).get("matched_policy_ids") or []
    )

    insights = [
        *_derive_patterns(db, evaluations_by_domain, match_counts),
        *_derive_anomalies(db, logs, window_start, now),
        *_derive_recommendations(db, domain, evaluations_by_domain, match_counts, window_start, logs),
    ]

    if insights:
        db.add_all(insights)
        db.commit()
        for insight in insights:
            db.refresh(insight)

    return insights
