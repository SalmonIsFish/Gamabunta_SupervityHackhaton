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

Two families of insight are generated:
- automation-opportunity insights (_derive_patterns/_derive_anomalies/
  _derive_recommendations below) — meta-statistics about policy usage,
  mined from this backend's own audit log.
- operational insights (_derive_operational_insights) — computed by reading
  the live procurement dataset directly from Supabase (the same project the
  Auto Operators seed and query), covering the Operations-specific patterns
  the brief calls for: recurring delay patterns, POs at risk, demand
  anomalies beyond safety stock, single-source exposure, and contracts
  expiring soon. This half degrades to zero insights (not an error) if
  Supabase isn't configured.
"""

import asyncio
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.audit import AuditLog
from ..models.insight import Insight, InsightSeverity, InsightType
from ..models.policy import Policy, PolicyStatus
from ..models.work_item import WorkItem
from . import supabase_client

log = logging.getLogger(__name__)

WINDOW_DAYS = 30
MIN_SAMPLE = 3  # minimum evaluations before a rate/absence is trustworthy
SPIKE_FACTOR = 2.0  # recent count must be at least this many times the baseline
MIN_SPIKE_COUNT = 3  # minimum absolute recent count before flagging a spike

GENERATED_BY = "insight_engine"

# Operational-insights pass (reads Supabase directly)
OPERATIONAL_DOMAIN = "procurement"
AT_RISK_WINDOW_DAYS = 7  # PO need_by_date within this many days counts as "at risk"
CONTRACT_EXPIRY_WINDOW_DAYS = 90
CONTRACT_EXPIRY_URGENT_DAYS = 30
DEMAND_SPIKE_FACTOR = 1.3  # actual demand must exceed forecast by at least this ratio

_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%b %d %Y",
)


def _parse_flexible_date(value: Optional[str]) -> Optional[datetime]:
    """
    Best-effort parse of the dataset's inconsistent date formats.

    The seeded dataset deliberately mixes ISO timestamps, "DD/MM/YYYY", and
    "Mon DD YYYY" strings in the same column (confirmed against the raw CSVs).
    An unparseable value is skipped, not guessed at — the agent shouldn't
    invent a value on malformed data any more than a missing one.
    """
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    log.debug("Could not parse date value: %r", value)
    return None


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


def _derive_delay_patterns(order_confirmations: list[dict]) -> list[Insight]:
    """'Supplier X has N delayed confirmations, most often for <reason>.'"""
    delays_by_supplier: dict[str, list[dict]] = defaultdict(list)
    for row in order_confirmations:
        if row.get("status") == "delayed" and row.get("supplier_id") is not None:
            delays_by_supplier[row["supplier_id"]].append(row)

    insights: list[Insight] = []
    for supplier_id, rows in delays_by_supplier.items():
        if len(rows) < MIN_SAMPLE:
            continue
        reasons = Counter(r.get("delay_reason") for r in rows if r.get("delay_reason"))
        top_reason, top_count = reasons.most_common(1)[0] if reasons else (None, 0)
        insights.append(
            Insight(
                title=f"Supplier {supplier_id} has {len(rows)} delayed confirmations",
                description=(
                    f"Supplier {supplier_id} has {len(rows)} delayed order confirmations"
                    + (f", most often citing '{top_reason}' ({top_count}x)" if top_reason else "")
                    + "."
                ),
                insight_type=InsightType.PATTERN.value,
                severity=InsightSeverity.WARNING.value,
                confidence=min(1.0, len(rows) / (MIN_SAMPLE * 3)),
                suggested_action=f"Review supplier {supplier_id}'s reliability and lead-time buffer",
                extra_data={
                    "domain": OPERATIONAL_DOMAIN,
                    "supplier_id": supplier_id,
                    "delayed_count": len(rows),
                    "top_delay_reason": top_reason,
                },
                generated_by=GENERATED_BY,
            )
        )
    return insights


def _derive_pos_at_risk(po_headers: list[dict]) -> list[Insight]:
    """Open (still-'issued') POs whose need_by_date has passed or is imminent."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=AT_RISK_WINDOW_DAYS)

    at_risk: list[tuple[dict, datetime]] = []
    for row in po_headers:
        need_by = _parse_flexible_date(row.get("need_by_date"))
        if need_by and need_by <= horizon:
            at_risk.append((row, need_by))

    if len(at_risk) < MIN_SAMPLE:
        return []

    overdue = [r for r, d in at_risk if d < now]
    severity = InsightSeverity.CRITICAL.value if overdue else InsightSeverity.WARNING.value

    return [
        Insight(
            title=f"{len(at_risk)} purchase orders trending at risk",
            description=(
                f"{len(at_risk)} open purchase order(s) have a need-by date within "
                f"{AT_RISK_WINDOW_DAYS} days, of which {len(overdue)} are already overdue."
            ),
            insight_type=InsightType.ANOMALY.value,
            severity=severity,
            confidence=min(1.0, len(at_risk) / (MIN_SAMPLE * 3)),
            suggested_action="Review at-risk POs and expedite or re-promise as needed",
            extra_data={
                "domain": OPERATIONAL_DOMAIN,
                "at_risk_count": len(at_risk),
                "overdue_count": len(overdue),
                "po_numbers": [r.get("po_number") for r, _ in at_risk[:20]],
            },
            generated_by=GENERATED_BY,
        )
    ]


def _derive_demand_anomalies(demand_signals: list[dict], inventory_positions: list[dict]) -> list[Insight]:
    """
    Demand spikes that land on an item already short on *available* stock —
    on-hand minus committed, not raw on-hand (the phantom-inventory trap).
    """
    inventory_by_item = {row.get("item_number"): row for row in inventory_positions}

    insights: list[Insight] = []
    for row in demand_signals:
        item_number = row.get("item_number")
        forecast = row.get("forecast_qty")
        actual = row.get("actual_demand")
        inv = inventory_by_item.get(item_number)
        if not item_number or forecast is None or actual is None or not inv:
            continue
        if forecast <= 0 or actual < forecast * DEMAND_SPIKE_FACTOR:
            continue

        available = (inv.get("on_hand_qty") or 0) - (inv.get("committed_qty") or 0)
        safety_stock = inv.get("safety_stock") or 0
        if available > safety_stock:
            continue

        insights.append(
            Insight(
                title=f"Demand spike on {item_number} beyond available safety stock",
                description=(
                    f"{item_number} saw actual demand of {actual} vs a forecast of {forecast} "
                    f"({row.get('signal_date', 'recent')}), while available stock "
                    f"({available} = on-hand minus committed) is at or below the safety "
                    f"stock level of {safety_stock}."
                ),
                insight_type=InsightType.ANOMALY.value,
                severity=InsightSeverity.CRITICAL.value,
                confidence=min(1.0, actual / max(forecast, 1) / (DEMAND_SPIKE_FACTOR * 2)),
                suggested_action=(
                    f"Check {item_number} for a compounding supplier delay; consider reallocation "
                    "from another warehouse node"
                ),
                extra_data={
                    "domain": OPERATIONAL_DOMAIN,
                    "item_number": item_number,
                    "forecast_qty": forecast,
                    "actual_demand": actual,
                    "available_qty": available,
                    "safety_stock": safety_stock,
                },
                generated_by=GENERATED_BY,
            )
        )
    return insights


def _derive_single_source_exposure(sole_source_suppliers: list[dict]) -> list[Insight]:
    """Active suppliers flagged x_sole_source=true — no fallback if they fail."""
    active = [s for s in sole_source_suppliers if s.get("status") == "active"]
    if not active:
        return []

    names = [s.get("name") or str(s.get("id")) for s in active[:10]]
    return [
        Insight(
            title=f"{len(active)} active sole-source supplier(s) with no fallback",
            description=(
                f"{len(active)} active supplier(s) are flagged sole-source: {', '.join(names)}"
                f"{', ...' if len(active) > 10 else ''}. A failure at any of these has no "
                "alternative supplier on file."
            ),
            insight_type=InsightType.RECOMMENDATION.value,
            severity=InsightSeverity.WARNING.value,
            confidence=1.0,
            suggested_action="Qualify at least one alternative supplier for each sole-source item",
            extra_data={
                "domain": OPERATIONAL_DOMAIN,
                "sole_source_supplier_ids": [s.get("id") for s in active],
            },
            generated_by=GENERATED_BY,
        )
    ]


def _derive_contract_expiry(contracts: list[dict]) -> list[Insight]:
    """Published contracts whose end_date falls inside the risk window."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=CONTRACT_EXPIRY_WINDOW_DAYS)

    expiring: list[tuple[dict, datetime]] = []
    for row in contracts:
        end_date = _parse_flexible_date(row.get("end_date"))
        if end_date and now <= end_date <= horizon:
            expiring.append((row, end_date))

    if not expiring:
        return []

    soon_cutoff = now + timedelta(days=CONTRACT_EXPIRY_URGENT_DAYS)
    urgent = [r for r, d in expiring if d <= soon_cutoff]
    severity = InsightSeverity.CRITICAL.value if urgent else InsightSeverity.WARNING.value

    return [
        Insight(
            title=f"{len(expiring)} contract(s) expiring within {CONTRACT_EXPIRY_WINDOW_DAYS} days",
            description=(
                f"{len(expiring)} active contract(s) expire within {CONTRACT_EXPIRY_WINDOW_DAYS} days, "
                f"{len(urgent)} of them within {CONTRACT_EXPIRY_URGENT_DAYS} days."
            ),
            insight_type=InsightType.RECOMMENDATION.value,
            severity=severity,
            confidence=1.0,
            suggested_action="Start renewal or re-sourcing conversations for contracts expiring soon",
            extra_data={
                "domain": OPERATIONAL_DOMAIN,
                "expiring_count": len(expiring),
                "urgent_count": len(urgent),
                "contract_numbers": [r.get("contract_number") for r, _ in expiring[:20]],
            },
            generated_by=GENERATED_BY,
        )
    ]


async def _derive_operational_insights(domain: Optional[str]) -> list[Insight]:
    """
    Sweep the live Supabase procurement tables directly — not audit-log
    derived — for the Operations-specific insight categories the brief calls
    for. Only runs when the caller didn't ask for a domain outside
    procurement, and degrades to no insights if Supabase isn't configured.
    """
    if domain not in (None, OPERATIONAL_DOMAIN) or not supabase_client.is_configured():
        return []

    (
        order_confirmations,
        po_headers,
        demand_signals,
        inventory_positions,
        sole_source_suppliers,
        published_contracts,
    ) = await asyncio.gather(
        supabase_client.select("order_confirmations"),
        supabase_client.select("purchase_order_headers", {"select": "*", "status": "eq.issued"}),
        supabase_client.select("demand_signals"),
        # Table name is case-sensitive in this Supabase project: "Inventory_positions",
        # not "inventory_positions" — confirmed against the Round 1 Auto workflow's own
        # code comment and by hitting the REST API directly (lowercase 404s).
        supabase_client.select("Inventory_positions"),
        supabase_client.select("suppliers", {"select": "*", "x_sole_source": "eq.true"}),
        supabase_client.select("contracts", {"select": "*", "status": "eq.published"}),
    )

    return [
        *_derive_delay_patterns(order_confirmations),
        *_derive_pos_at_risk(po_headers),
        *_derive_demand_anomalies(demand_signals, inventory_positions),
        *_derive_single_source_exposure(sole_source_suppliers),
        *_derive_contract_expiry(published_contracts),
    ]


async def generate_insights(db: Session, domain: Optional[str] = None) -> list[Insight]:
    """
    Derive fresh Insight rows from recent audit-log activity, plus a live
    sweep of the Supabase procurement dataset (see _derive_operational_insights).

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
        *await _derive_operational_insights(domain),
    ]

    if insights:
        db.add_all(insights)
        db.commit()
        for insight in insights:
            db.refresh(insight)

    return insights
