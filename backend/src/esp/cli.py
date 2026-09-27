"""Operator commands: `esp ingest ssurgo --areas CO644 [CO645 ...]`."""

import argparse
import json
import sys

import httpx
from sqlalchemy.orm import sessionmaker

from esp.config import get_settings
from esp.db import get_engine
from esp.ingest import ingest_ssurgo
from esp.logging import configure_logging
from esp.sources.ssurgo import WebSoilSurvey

USER_AGENT = "environmental-screening-platform (+https://github.com/aarondroper/environmental-screening-platform)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="esp")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Acquire, validate and promote a dataset")
    sources = ingest.add_subparsers(dest="dataset", required=True)
    ssurgo = sources.add_parser("ssurgo", help="NRCS SSURGO survey-area packages")
    ssurgo.add_argument("--areas", nargs="+", required=True, help="Survey area symbols, e.g. CO644")
    ssurgo.add_argument(
        "--no-promote", action="store_true", help="Validate only; leave the active version"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    sessions = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
    ) as client:
        outcome = ingest_ssurgo(
            sessions,
            WebSoilSurvey(client),
            args.areas,
            settings.raw_dir,
            promote=not args.no_promote,
        )
    print(json.dumps({k: str(v) for k, v in outcome.__dict__.items()}))
    return 0 if outcome.status in ("succeeded", "unchanged") else 1


if __name__ == "__main__":
    sys.exit(main())
