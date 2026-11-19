"""Ingest all sample emails through the real pipeline so the dashboard has data.

    python -m opspilot.demo_load [--if-empty]

Timestamps are rebased so the newest e-mail arrived minutes ago (otherwise every SLA in the
fixed-date sample set would already be breached). Re-running is safe: duplicates are ignored.
"""

import argparse
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from opspilot.api.container import Container, build_container
from opspilot.db.models import Task
from opspilot.emailio import raw_from_seed_json
from opspilot.settings import get_settings

log = logging.getLogger(__name__)
SEED = Path("data/seed")
SPAN_HOURS = 10.0


def load_demo(
    container: Container, base: Path = SEED, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    paths = sorted((base / "emails").glob("EM-*.json"))
    raws = [raw_from_seed_json(p, base / "attachments") for p in paths]
    first, last = min(r.received_at for r in raws), max(r.received_at for r in raws)
    span = (last - first).total_seconds() or 1.0
    # compress the 3-day sample into the last ~10 hours so SLA clocks look like a live working day
    squeeze = min(1.0, SPAN_HOURS * 3600 / span)

    def rebase(t: datetime) -> datetime:
        return now - timedelta(minutes=5) - timedelta(seconds=(last - t).total_seconds() * squeeze)

    counts = {"processed": 0, "duplicate": 0, "interrupted": 0}
    for raw in raws:
        res = container.pipeline.start(
            raw.model_copy(update={"received_at": rebase(raw.received_at)})
        )
        counts["duplicate" if res.state.duplicate else "processed"] += 1
        counts["interrupted"] += res.status.value == "interrupted"
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-empty", action="store_true", help="skip when tasks already exist")
    args = ap.parse_args()
    container = build_container(get_settings())
    try:
        with container.factory() as s:
            existing = s.scalar(select(func.count()).select_from(Task)) or 0
        if args.if_empty and existing:
            log.info("demo data already present (%d tasks); skipping", existing)
            return
        log.info("demo data loaded: %s", json.dumps(load_demo(container)))
    finally:
        container.close()


if __name__ == "__main__":
    main()
