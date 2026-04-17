import argparse
import json
import os
import random
import sys
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import db


DEFAULT_DURATION_SECONDS = 50 * 60


def choose_student_count(rng: random.Random) -> int:
    # Most sessions are complete (40), with only 1-3 absences in some sessions.
    population = [40, 39, 38, 37]
    weights = [0.72, 0.16, 0.08, 0.04]
    return rng.choices(population, weights=weights, k=1)[0]


def bounded_int(value: float, minimum: int = 0) -> int:
    return max(minimum, int(round(value)))


def build_random_student_actions(session_duration_seconds: int, rng: random.Random) -> dict:
    student_count = choose_student_count(rng)
    duration = max(60, int(session_duration_seconds or DEFAULT_DURATION_SECONDS))

    tallies: dict[str, dict[str, int]] = {}
    for student_id in range(1, student_count + 1):
        actions: dict[str, int] = {}

        # Upright is duration in seconds and should represent most of detected session time.
        upright_ratio = rng.uniform(0.62, 0.96)
        upright_seconds = bounded_int(duration * upright_ratio, 1)
        actions["upright"] = upright_seconds

        # Sleep is also duration in seconds. Mostly none/low, occasionally higher.
        if rng.random() < 0.30:
            max_sleep = max(45, min(int(duration * 0.35), 20 * 60))
            sleep_seconds = rng.randint(20, max_sleep)
            actions["sleep"] = sleep_seconds

        # Event-like counts.
        handraise = rng.choices([0, 1, 2, 3, 4, 5, 6], weights=[0.1, 0.2, 0.25, 0.2, 0.14, 0.08, 0.03], k=1)[0]
        write = rng.choices([0, 1, 2, 3, 4], weights=[0.32, 0.28, 0.2, 0.13, 0.07], k=1)[0]
        yawn = rng.choices([0, 1, 2, 3], weights=[0.55, 0.28, 0.13, 0.04], k=1)[0]
        turnhead = rng.choices([0, 1, 2, 3, 4], weights=[0.22, 0.3, 0.25, 0.15, 0.08], k=1)[0]

        if handraise > 0:
            actions["handraise"] = handraise
        if write > 0:
            actions["write"] = write
        if yawn > 0:
            actions["yawn"] = yawn
        if turnhead > 0:
            actions["turnhead"] = turnhead

        tallies[str(student_id)] = actions

    return tallies


def get_session_duration_seconds(start_time, end_time) -> int:
    if not start_time or not end_time:
        return DEFAULT_DURATION_SECONDS

    if isinstance(start_time, str):
        try:
            start_time = datetime.fromisoformat(start_time)
        except ValueError:
            return DEFAULT_DURATION_SECONDS
    if isinstance(end_time, str):
        try:
            end_time = datetime.fromisoformat(end_time)
        except ValueError:
            return DEFAULT_DURATION_SECONDS

    delta = (end_time - start_time).total_seconds()
    if delta <= 0:
        return DEFAULT_DURATION_SECONDS
    return int(delta)


def run_backfill(seed: int | None, only_missing: bool) -> dict:
    rng = random.Random(seed)
    stats = {
        "seed": seed,
        "sessions_scanned": 0,
        "sessions_updated": 0,
        "sessions_skipped_existing": 0,
    }

    db.init_db()

    with db.get_cursor() as cur:
        cur.execute(
            """
            SELECT id, start_time, end_time, summary_stats
            FROM sessions
            WHERE status = 'completed'
            ORDER BY id
            """
        )
        sessions = cur.fetchall() or []
        stats["sessions_scanned"] = len(sessions)

        for row in sessions:
            session_id = row["id"]
            summary_stats = row.get("summary_stats") or {}
            if not isinstance(summary_stats, dict):
                summary_stats = {}

            existing = summary_stats.get("studentActionTallies")
            if existing is None:
                existing = summary_stats.get("student_action_tallies")

            if only_missing and isinstance(existing, dict) and existing:
                stats["sessions_skipped_existing"] += 1
                continue

            duration_seconds = get_session_duration_seconds(row.get("start_time"), row.get("end_time"))
            summary_stats["studentActionTallies"] = build_random_student_actions(duration_seconds, rng)

            cur.execute(
                "UPDATE sessions SET summary_stats = %s::jsonb WHERE id = %s",
                (json.dumps(summary_stats), session_id),
            )
            stats["sessions_updated"] += 1

    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill random per-student action tallies for completed sessions.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for deterministic generation.",
    )
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Only fill sessions with missing studentActionTallies.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = run_backfill(seed=args.seed, only_missing=args.only_missing)
    print(json.dumps(result))
