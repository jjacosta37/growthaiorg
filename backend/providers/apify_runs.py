"""Helpers shared by the Apify-backed providers."""

import logging
from typing import Any

log = logging.getLogger(__name__)


def settled_run(client: Any, run: Any) -> Any:
    """Re-read a finished actor run so its cost is final.

    The run object `ActorClient.call()` returns can predate the run's last pay-per-event charges:
    a live keyword lookup returned `usage_total_usd` of $0.00005 for a run that cost $0.044. The
    spend we record has to be the settled figure, so read the run again once it has finished.
    Falls back to the original object if the re-read fails.
    """
    try:
        return client.run(run.id).get() or run
    except Exception:
        log.warning("couldn't re-read apify run %s; its recorded cost may be understated", run.id, exc_info=True)
        return run
