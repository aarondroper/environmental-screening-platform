"""Screening worker: `python -m esp.worker`. Polls the PostgreSQL job queue."""

import logging
import os
import signal
import socket
import time
from types import FrameType

from sqlalchemy.orm import sessionmaker

from esp import jobs
from esp.config import get_settings
from esp.db import get_engine
from esp.logging import configure_logging

log = logging.getLogger("esp.worker")

POLL_SECONDS = 1.0


def work_once(sessions: sessionmaker, worker_id: str) -> bool:  # type: ignore[type-arg]
    """Claim and run at most one job. Returns whether a job was processed."""
    with sessions() as session:
        job_id = jobs.claim(session, worker_id)
        if job_id is None:
            return False
        jobs.run(session, job_id)
        return True


def main() -> None:
    configure_logging(get_settings().log_level)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    sessions = sessionmaker(bind=get_engine(), expire_on_commit=False)
    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("worker started", extra={"worker_id": worker_id})
    while not stopping:
        try:
            if not work_once(sessions, worker_id):
                time.sleep(POLL_SECONDS)
        except Exception:
            log.exception("worker loop error")
            time.sleep(5)
    log.info("worker stopped", extra={"worker_id": worker_id})


if __name__ == "__main__":
    main()
