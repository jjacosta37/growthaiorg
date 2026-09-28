"""Bookkeeping for one external (non-LLM) provider call.

An external call is the part of a run that spends money and takes the longest, and until now
it was also the least visible: the ExternalUsage row was written inline by each pipeline and
no RunEvent ever mentioned it, so the provider's run id, duration and cost reached the
database and nothing else. `record_external` writes the row and reports it in one place, so
every provider call reads the same way in the trail whatever pipeline made it.
"""

from decimal import Decimal

from .models import ExternalUsage


def record_external(run, reporter, *, provider: str, purpose: str, message: str,
                    resource_id: str = "", external_run_id: str = "", status: str = "",
                    items: int = 0, cost_usd: Decimal = Decimal(0), duration_ms: int = 0,
                    error: str = "", **data) -> ExternalUsage:
    """Record one provider call: the ExternalUsage row plus a structured RunEvent.

    Reported as a warning when `error` is set, because that is exactly the degraded-but-
    carried-on case — a provider call that fails outright is the caller's to raise on.
    """
    usage = ExternalUsage.objects.create(
        project=run.project, agent_run=run, provider=provider, purpose=purpose,
        resource_id=resource_id, external_run_id=external_run_id, status=status,
        items=items, cost_usd=cost_usd, duration_ms=duration_ms, error=error,
    )
    detail = {
        "provider": provider,
        "purpose": purpose,
        "resource_id": resource_id,
        "external_run_id": external_run_id,
        "status": status,
        "items": items,
        "duration_ms": duration_ms,
        "cost_usd": float(cost_usd),  # Decimal is not JSON-serialisable
        **data,
    }
    if error:
        reporter.warning(f"{message}: {error}", **detail, error=error)
    else:
        reporter.event(message, **detail)
    return usage
