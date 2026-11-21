"""Background worker: sends due-soon / overdue reminders and the managers' daily digest.

Usage (from backend/):
    python -m app.workers.reminders           # run every 60 seconds until stopped
    python -m app.workers.reminders --once    # one pass (for testing or a scheduler)

Safe to run more than once at the same time: each reminder is recorded once in reminder_log.
"""

import argparse
import logging
import time

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_engine
from app.services import reminders

logger = logging.getLogger("voiceflow.worker")


def run_once() -> reminders.RunStats:
    with Session(get_engine()) as db:
        stats = reminders.run(db)
        db.commit()
    logger.info("reminder pass", extra={"data": vars(stats)})
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="VoiceFlow reminders worker")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    parser.add_argument("--interval", type=int, default=60, help="seconds between passes")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    if args.once:
        print(vars(run_once()))
        return 0
    while True:
        try:
            run_once()
        except Exception:  # keep running; the next pass retries
            logger.exception("reminder pass failed")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
