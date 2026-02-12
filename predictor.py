#!/usr/bin/env python3
"""
Football Match Predictor — Glicko2 Strategy

Selects tomorrow's matches, analyzes Glicko2 rating trends,
validates with stats, and outputs betting predictions.

Usage:
    python predictor.py                  # Tomorrow's predictions
    python predictor.py --today          # Today's predictions
    python predictor.py --date 2026-02-15  # Specific date
    python predictor.py --json           # JSON output
    python predictor.py --league 39      # Filter by league (e.g. 39 = EPL)
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

from api_client import SStatsAPI
from glicko_analyzer import GlickoAnalyzer
from stats_validator import StatsValidator
from config import TIMEZONE, MIN_CONFIDENCE, MAX_RD


def get_target_date(args):
    """Determine target date from arguments."""
    if args.date:
        return args.date
    if args.today:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d")


def fetch_matches(api, target_date, league_id=None):
    """Fetch matches for the target date."""
    print(f"\n{'='*60}")
    print(f"  FOOTBALL PREDICTIONS — {target_date}")
    print(f"  Strategy: Glicko2 Rating Dynamics")
    print(f"{'='*60}\n")

    print(f"[*] Fetching matches for {target_date}...")

    resp = api.get_matches_by_date(target_date)
    if not resp or not resp.get("data"):
        print("[*] No matches on exact date, trying upcoming...")
        resp = api.get_upcoming_matches(limit=300)

    if not resp or not resp.get("data"):
        print("[!] No matches found.")
        return []

    matches = resp["data"]

    # Filter by date if using upcoming endpoint
    matches = [m for m in matches if m.get("date", "").startswith(target_date)
               or m.get("dateUtc", "").startswith(target_date)]

    # Filter by league if specified
    if league_id:
        matches = [
            m for m in matches
            if m.get("season", {}).get("league", {}).get("id") == league_id
        ]

    # Filter out already finished/cancelled matches
    active_statuses = {1, 2}
    matches = [m for m in matches if m.get("status") in active_statuses or m.get("status") is None]

    print(f"[+] Found {len(matches)} upcoming matches for {target_date}")
    return matches


def prefilter_matches(api, matches):
    """
    Quick pre-filter: fetch Glicko2 for each match (1 API call each),
    keep only matches where both teams have reliable ratings (low RD).
    This avoids expensive history-building for hopeless matches.
    """
    print(f"[*] Pre-filtering: checking Glicko2 data for {len(matches)} matches...")

    filtered = []
    for i, match in enumerate(matches, 1):
        game_id = match.get("id")
        home = match.get("homeTeam", {}).get("name", "?")
        away = match.get("awayTeam", {}).get("name", "?")

        pct = i * 100 // len(matches)
        print(f"\r[*] Pre-filter: {i}/{len(matches)} ({pct}%) — {home} vs {away}   ", end="", flush=True)

        glicko_resp = api.get_glicko(game_id)
        if not glicko_resp or not glicko_resp.get("data"):
            continue

        glicko = glicko_resp["data"].get("glicko")
        if not glicko:
            continue

        home_rd = glicko.get("homeRd", 999)
        away_rd = glicko.get("awayRd", 999)

        # Skip teams with unreliable ratings
        if home_rd > MAX_RD or away_rd > MAX_RD:
            continue

        # Store glicko data for later use
        match["_glicko_data"] = glicko_resp["data"]
        filtered.append(match)

    print(f"\n[+] Pre-filter done: {len(filtered)}/{len(matches)} matches have reliable Glicko2 data")
    return filtered


def analyze_matches(api, matches, max_matches=None):
    """Analyze pre-filtered matches and collect predictions."""
    analyzer = GlickoAnalyzer(api)
    validator = StatsValidator(api)

    predictions = []
    total = len(matches)
    if max_matches:
        matches = matches[:max_matches]
        total = len(matches)

    for i, match in enumerate(matches, 1):
        game_id = match.get("id")
        home = match.get("homeTeam", {}).get("name", "?")
        away = match.get("awayTeam", {}).get("name", "?")
        league = match.get("season", {}).get("league", {}).get("name", "?")

        print(f"\r[*] Deep analysis {i}/{total}: {home} vs {away} ({league})   ", end="", flush=True)

        try:
            # Pass cached glicko data to avoid extra API call
            analysis = analyzer.analyze_match(game_id, cached_glicko=match.get("_glicko_data"))
            if analysis and analysis.get("signals"):
                analysis = validator.validate_signals(analysis)
                if analysis.get("signals"):
                    predictions.append(analysis)
                    print(f" -> {len(analysis['signals'])} signal(s)!", flush=True)
        except Exception as e:
            print(f"\n[!] Error analyzing {game_id}: {e}")

    print(f"\n[+] Analysis complete. API requests used: {api.request_count}")
    return predictions


def format_confidence(conf):
    """Format confidence as visual bar."""
    bars = int(conf * 10)
    return f"{'█' * bars}{'░' * (10 - bars)} {conf:.0%}"


def print_predictions_table(predictions):
    """Print predictions in a formatted table."""
    if not predictions:
        print("\n[!] No predictions found matching the strategy criteria.")
        print("    This means no matches had clear Glicko2 trend patterns.")
        return

    all_signals = []
    for pred in predictions:
        for sig in pred["signals"]:
            all_signals.append({**sig, **{
                "home_team": pred["home_team"],
                "away_team": pred["away_team"],
                "league": pred["league"],
                "date": pred["date"],
                "home_rating": pred["home_rating"],
                "away_rating": pred["away_rating"],
                "home_trend": pred["home_trend"],
                "away_trend": pred["away_trend"],
                "home_slope": pred["home_slope"],
                "away_slope": pred["away_slope"],
                "home_xg": pred.get("home_xg"),
                "away_xg": pred.get("away_xg"),
            }})

    all_signals.sort(key=lambda x: x["confidence"], reverse=True)

    print(f"\n{'='*80}")
    print(f"  PREDICTIONS — {len(all_signals)} signals from {len(predictions)} matches")
    print(f"{'='*80}")

    for i, sig in enumerate(all_signals, 1):
        trend_arrows = {
            "strong_up": "⬆⬆", "up": "⬆", "flat": "➡",
            "down": "⬇", "strong_down": "⬇⬇"
        }
        home_arrow = trend_arrows.get(sig["home_trend"], "?")
        away_arrow = trend_arrows.get(sig["away_trend"], "?")

        print(f"\n{'─'*80}")
        print(f"  #{i}  {sig['home_team']} vs {sig['away_team']}")
        print(f"       League: {sig['league']}  |  Date: {sig['date']}")
        print(f"       Ratings: {sig['home_rating']:.0f} {home_arrow} ({sig['home_slope']:+.1f}/match)"
              f"  vs  {sig['away_rating']:.0f} {away_arrow} ({sig['away_slope']:+.1f}/match)")

        if sig.get("home_xg") is not None and sig.get("away_xg") is not None:
            print(f"       xG: {sig['home_xg']:.2f} — {sig['away_xg']:.2f}")

        print(f"\n       >>> BET: {sig['label']}")
        print(f"       Confidence: {format_confidence(sig['confidence'])}")

        if sig.get("odds"):
            print(f"       Odds: {sig['odds']:.2f}")

        print(f"       Reason: {sig['reason']}")

        if sig.get("stats_notes"):
            print(f"       Stats: {sig['stats_notes']}")

        if sig.get("note"):
            print(f"       Note: {sig['note']}")

    print(f"\n{'='*80}")
    print(f"  SUMMARY: {len(all_signals)} predictions")
    print(f"  Strategy: Glicko2 Rating Dynamics + Stats Validation")
    print(f"  Min confidence: {MIN_CONFIDENCE:.0%}")
    print(f"{'='*80}\n")

    print("  DISCLAIMER: This is a statistical tool, not financial advice.")
    print("  Past performance does not guarantee future results.")
    print("  Always bet responsibly and only with money you can afford to lose.\n")


def print_predictions_json(predictions):
    """Print predictions as JSON."""
    output = []
    for pred in predictions:
        output.append({
            "match": f"{pred['home_team']} vs {pred['away_team']}",
            "league": pred["league"],
            "date": pred["date"],
            "home_rating": pred["home_rating"],
            "away_rating": pred["away_rating"],
            "trends": {
                "home": pred["home_trend"],
                "away": pred["away_trend"],
            },
            "signals": pred["signals"],
        })
    print(json.dumps(output, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(
        description="Football Match Predictor — Glicko2 Strategy"
    )
    parser.add_argument("--today", action="store_true", help="Analyze today's matches")
    parser.add_argument("--date", type=str, help="Specific date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--league", type=int, help="Filter by league ID")
    parser.add_argument("--max", type=int, help="Max matches to deep-analyze")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    target_date = get_target_date(args)

    api = SStatsAPI()
    matches = fetch_matches(api, target_date, league_id=args.league)

    if not matches:
        sys.exit(0)

    # Phase 1: Quick pre-filter (1 API call per match)
    matches = prefilter_matches(api, matches)
    if not matches:
        print("[!] No matches passed the pre-filter (all had high RD or no Glicko2 data).")
        sys.exit(0)

    # Phase 2: Deep analysis (builds rating history — ~10 calls per team, cached)
    predictions = analyze_matches(api, matches, max_matches=args.max)

    if args.json:
        print_predictions_json(predictions)
    else:
        print_predictions_table(predictions)


if __name__ == "__main__":
    main()
