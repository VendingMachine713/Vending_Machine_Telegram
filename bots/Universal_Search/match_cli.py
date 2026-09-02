import argparse
import json
from pathlib import Path

from match_runtime import HardenedMatchEngine
from match_ui import money, reason_summary

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "universal_search.db"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="VM Universal Search demand/supply match engine.")
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser("refresh", help="Recalculate active WTB/supply matches.")
    refresh.add_argument("--min-score", type=float, default=45.0)

    bootstrap = sub.add_parser("bootstrap", help="Create a no-alert baseline from existing indexed history.")
    bootstrap.add_argument("--min-score", type=float, default=45.0)

    list_cmd = sub.add_parser("list", help="Show top marketplace matches.")
    list_cmd.add_argument("--min-score", type=float, default=45.0)
    list_cmd.add_argument("--limit", type=int, default=20)

    detail = sub.add_parser("show", help="Show one match.")
    detail.add_argument("id", type=int)

    sub.add_parser("stats", help="Show match engine statistics and alert queue state.")
    sub.add_parser("queue", help="Show durable passive-alert queue counts.")
    sub.add_parser("cleanup", help="Cancel stale alerts and prune retained queue history.")

    retry = sub.add_parser("retry-failed", help="Requeue failed alerts whose match is still active/new.")
    retry.add_argument("--user-id", type=int, default=0)
    retry.add_argument("--limit", type=int, default=50)

    notify = sub.add_parser("notifications", help="Read or change passive match-alert state.")
    notify.add_argument("state", choices=("status", "on", "off"), default="status", nargs="?")

    feedback = sub.add_parser("feedback", help="Record match feedback.")
    feedback.add_argument("id", type=int)
    feedback.add_argument("verdict", choices=("relevant", "not_relevant", "accepted", "ignore"))
    feedback.add_argument("--user-id", type=int, default=0)
    feedback.add_argument("--note", default="")
    return parser.parse_args(argv)


def print_match(row):
    print(
        f"#{row['id']} score={row['score']:.1f} confidence={row['confidence']:.0%} "
        f"status={row['status']}"
    )
    print(f"  WTB   : {row['demand_title'] or '(untitled)'} | budget={money(row['demand_budget'])}")
    print(f"  SUPPLY: {row['supply_title'] or '(untitled)'} | price={money(row['supply_price'])}")
    reasons = reason_summary(row["reasons_json"])
    if reasons:
        print("  WHY   : " + "; ".join(reasons))


def print_queue(engine):
    counts = engine.queue_status()
    if not counts:
        print("Alert queue is empty.")
        return
    print(" ".join(f"{key}={counts[key]}" for key in sorted(counts)))


def main(argv=None):
    args = parse_args(argv)
    engine = HardenedMatchEngine(DB)

    if args.command == "refresh":
        print(json.dumps(engine.refresh_all(min_score=args.min_score), indent=2))
        return

    if args.command == "bootstrap":
        print(json.dumps(engine.bootstrap(min_score=args.min_score), indent=2))
        return

    if args.command == "list":
        rows = engine.list_matches(min_score=args.min_score, limit=args.limit)
        if not rows:
            print("No active marketplace matches.")
            return
        for row in rows:
            print_match(row)
        return

    if args.command == "show":
        row = engine.get_match(args.id)
        if not row:
            raise SystemExit("Match not found.")
        print_match(row)
        print("  RAW REASONS:")
        try:
            print(json.dumps(json.loads(row["reasons_json"] or "[]"), indent=2))
        except json.JSONDecodeError:
            print(row["reasons_json"])
        return

    if args.command == "stats":
        totals, feedback = engine.stats()
        print(
            f"total={totals['total'] or 0} active={totals['active'] or 0} "
            f"new={totals['new_count'] or 0} high_confidence={totals['high_confidence'] or 0}"
        )
        print(
            f"baseline_completed_utc={engine.get_state('baseline_completed_utc', '-')}; "
            f"notifications={'on' if engine.notifications_enabled() else 'off'}"
        )
        print_queue(engine)
        for row in feedback:
            print(f"feedback {row['verdict']}: {row['count']}")
        return

    if args.command == "queue":
        print_queue(engine)
        return

    if args.command == "cleanup":
        cancelled = engine.cancel_stale_alerts()
        pruned = engine.cleanup_alert_history()
        print(f"[OK] cancelled_stale={cancelled} pruned_history={pruned}")
        print_queue(engine)
        return

    if args.command == "retry-failed":
        count = engine.retry_failed_alerts(args.user_id or None, limit=args.limit)
        print(f"[OK] requeued_failed_alerts={count}")
        print_queue(engine)
        return

    if args.command == "notifications":
        if args.state == "on":
            engine.set_notifications_enabled(True)
        elif args.state == "off":
            engine.set_notifications_enabled(False)
        print("on" if engine.notifications_enabled() else "off")
        return

    if args.command == "feedback":
        if not engine.record_feedback(args.id, args.user_id, args.verdict, args.note):
            raise SystemExit("Match not found.")
        print(f"[OK] Match #{args.id} feedback={args.verdict}")
        print_queue(engine)


if __name__ == "__main__":
    main()
