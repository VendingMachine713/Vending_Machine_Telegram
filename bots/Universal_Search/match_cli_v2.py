import argparse
import json
from pathlib import Path

from core import Store
from marketplace import MarketplaceStore
from match_engine_v2_runtime import HardenedMatchEngineV2
from match_ui_v2 import format_demand_stats

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "universal_search.db"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Universal Search Match Engine v2 operations.")
    sub = p.add_subparsers(dest="command", required=True)

    boot = sub.add_parser("bootstrap", help="Create/refresh v2 baseline without historical reminder flood.")
    boot.add_argument("--min-score", type=float, default=45.0)
    boot.add_argument("--ttl-days", type=int, default=30)
    boot.add_argument("--reminder-lead-days", type=int, default=7)

    events = sub.add_parser("events", help="Process pending marketplace-change events.")
    events.add_argument("--limit", type=int, default=250)
    events.add_argument("--min-score", type=float, default=45.0)
    events.add_argument("--candidate-limit", type=int, default=500)

    expiry = sub.add_parser("expiry-refresh", help="Reconcile active WTB expiry/reminder state.")
    expiry.add_argument("--ttl-days", type=int, default=30)
    expiry.add_argument("--reminder-lead-days", type=int, default=7)

    demand = sub.add_parser("demand-stats", help="Show demand intelligence and calibration.")
    demand.add_argument("--alert-score", type=float, default=65.0)
    demand.add_argument("--json", action="store_true")

    calibration = sub.add_parser("calibration", help="Show advisory-only threshold calibration.")
    calibration.add_argument("--alert-score", type=float, default=65.0)
    calibration.add_argument("--min-samples", type=int, default=20)

    sub.add_parser("event-backlog", help="Show pending marketplace-change event count.")
    return p.parse_args(argv)


def make_engine():
    DB.parent.mkdir(parents=True, exist_ok=True)
    Store(DB)
    MarketplaceStore(DB)
    return HardenedMatchEngineV2(DB)


def main(argv=None):
    args = parse_args(argv)
    engine = make_engine()

    if args.command == "bootstrap":
        print(json.dumps(engine.bootstrap_v2(
            min_score=args.min_score,
            ttl_days=args.ttl_days,
            reminder_lead_days=args.reminder_lead_days,
        ), indent=2))
        return

    if args.command == "events":
        print(json.dumps(engine.process_events(
            limit=args.limit,
            min_score=args.min_score,
            candidate_limit=args.candidate_limit,
        ), indent=2))
        return

    if args.command == "expiry-refresh":
        print(json.dumps(engine.refresh_wtb_expiry(
            ttl_days=args.ttl_days,
            reminder_lead_days=args.reminder_lead_days,
        ), indent=2))
        return

    if args.command == "demand-stats":
        stats = engine.demand_stats(alert_threshold=args.alert_score)
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            # Telegram formatter is HTML; strip only the simple tags used here for console readability.
            text = format_demand_stats(stats).replace("<b>", "").replace("</b>", "")
            print(text)
        return

    if args.command == "calibration":
        print(json.dumps(engine.calibration_summary(
            current_threshold=args.alert_score,
            min_samples=args.min_samples,
        ), indent=2))
        return

    print(engine.event_backlog_count())


if __name__ == "__main__":
    main()
