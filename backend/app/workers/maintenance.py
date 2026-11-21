"""Background worker: daily data retention (see app/services/retention.py).

Usage (from backend/):
    python -m app.workers.maintenance           # run once an hour until stopped
    python -m app.workers.maintenance --once    # one pass (for testing or Windows Task Scheduler)

Safe to run more than once at the same time: each pass only deletes rows past their period.
"""

import argparse
import logging
import time

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_engine
from app.services import retention

logger = logging.getLogger("voiceflow.worker")


def run_once() -> retention.RetentionStats:
    with Session(get_engine()) as db:
        stats = retention.run(db)
        db.commit()
    logger.info("retention pass", extra={"data": vars(stats)})
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="VoiceFlow maintenance worker (retention)")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    parser.add_argument("--interval", type=int, default=3600, help="seconds between passes")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    if args.once:
        print(vars(run_once()))
        return 0
    while True:
        try:
            run_once()
        except Exception:  # keep running; the next pass retries
            logger.exception("retention pass failed")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
