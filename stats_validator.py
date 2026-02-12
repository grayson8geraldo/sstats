"""
Stats validator — validates Glicko2 signals with additional statistical data.

Checks xG, recent goals, BTTS rate, and other stats to confirm or reject signals.
"""

from config import (
    MAX_AVG_GOALS_FOR_UNDER, MIN_AVG_GOALS_FOR_BTTS,
    MIN_BTTS_RATE, MIN_ODDS,
)


class StatsValidator:
    """Validates and enriches signals with statistical confirmation."""

    def __init__(self, api_client):
        self.api = api_client

    def validate_signals(self, analysis):
        """
        Validate all signals for a match using additional stats.
        Modifies signals in place — adjusts confidence, adds stats info.
        """
        if not analysis or not analysis.get("signals"):
            return analysis

        game_id = analysis["game_id"]

        # Fetch additional stats
        last_stats = self.api.get_last_games_stats(game_id, limit=10)
        profits = self.api.get_profits(game_id, limit=25)

        home_stats, away_stats = self._parse_last_stats(last_stats)

        for signal in analysis["signals"]:
            self._validate_signal(signal, home_stats, away_stats, profits)

        # Re-filter after validation
        from config import MIN_CONFIDENCE
        analysis["signals"] = [
            s for s in analysis["signals"] if s["confidence"] >= MIN_CONFIDENCE
        ]

        return analysis

    def _parse_last_stats(self, last_stats):
        """Parse the last-games-stats response into home/away dicts."""
        home = {}
        away = {}

        if not last_stats or not last_stats.get("data"):
            return home, away

        data = last_stats["data"]

        # The API returns stats for both teams
        if isinstance(data, dict):
            home = data.get("home", data.get("homeTeam", {}))
            away = data.get("away", data.get("awayTeam", {}))
        elif isinstance(data, list) and len(data) >= 2:
            home = data[0] if isinstance(data[0], dict) else {}
            away = data[1] if isinstance(data[1], dict) else {}

        return home, away

    def _validate_signal(self, signal, home_stats, away_stats, profits):
        """Validate a single signal with stats."""
        sig_type = signal["type"]

        # Check minimum odds
        min_odds = MIN_ODDS.get(sig_type, MIN_ODDS.get(sig_type.split("_")[0], 1.0))
        if signal.get("odds") and signal["odds"] < min_odds:
            signal["confidence"] -= 0.15
            signal["note"] = f"Low odds ({signal['odds']}) — poor value"

        if sig_type == "under_2.5":
            self._validate_under(signal, home_stats, away_stats, profits)
        elif sig_type == "btts_yes":
            self._validate_btts(signal, home_stats, away_stats, profits)
        elif sig_type.startswith("win_"):
            self._validate_win(signal, home_stats, away_stats, profits)
        elif sig_type.startswith("double_chance_"):
            self._validate_double_chance(signal, home_stats, away_stats, profits)

    def _validate_under(self, signal, home_stats, away_stats, profits):
        """Validate Under 2.5 signal with goals stats."""
        notes = []

        # Check average goals
        home_scored = _safe_float(home_stats.get("avgGoalsScored",
                                  home_stats.get("goalsScored",
                                  home_stats.get("avgScored"))))
        home_conceded = _safe_float(home_stats.get("avgGoalsConceded",
                                    home_stats.get("goalsConceded",
                                    home_stats.get("avgMissed"))))
        away_scored = _safe_float(away_stats.get("avgGoalsScored",
                                  away_stats.get("goalsScored",
                                  away_stats.get("avgScored"))))
        away_conceded = _safe_float(away_stats.get("avgGoalsConceded",
                                    away_stats.get("goalsConceded",
                                    away_stats.get("avgMissed"))))

        if home_scored is not None and away_scored is not None:
            est_total = (home_scored + away_conceded) / 2 + (away_scored + home_conceded) / 2 \
                if home_conceded is not None and away_conceded is not None \
                else home_scored + away_scored

            if est_total < MAX_AVG_GOALS_FOR_UNDER:
                signal["confidence"] += 0.08
                notes.append(f"Avg goals confirm: ~{est_total:.1f}")
            elif est_total > 3.0:
                signal["confidence"] -= 0.15
                notes.append(f"High avg goals: ~{est_total:.1f} — contradicts Under")

        # Check profit history
        under_profit = self._get_profit_value(profits, "Under")
        if under_profit is not None:
            if under_profit > 0:
                signal["confidence"] += 0.05
                notes.append(f"Historical Under profit: +{under_profit:.0f}%")
            elif under_profit < -20:
                signal["confidence"] -= 0.1
                notes.append(f"Historical Under loss: {under_profit:.0f}%")

        if notes:
            signal["stats_notes"] = "; ".join(notes)

    def _validate_btts(self, signal, home_stats, away_stats, profits):
        """Validate BTTS signal with scoring stats."""
        notes = []

        home_scored = _safe_float(home_stats.get("avgGoalsScored",
                                  home_stats.get("goalsScored",
                                  home_stats.get("avgScored"))))
        away_scored = _safe_float(away_stats.get("avgGoalsScored",
                                  away_stats.get("goalsScored",
                                  away_stats.get("avgScored"))))

        if home_scored is not None and away_scored is not None:
            if home_scored >= MIN_AVG_GOALS_FOR_BTTS and away_scored >= MIN_AVG_GOALS_FOR_BTTS:
                signal["confidence"] += 0.08
                notes.append(f"Both teams score well: {home_scored:.1f} / {away_scored:.1f}")
            elif home_scored < 0.6 or away_scored < 0.6:
                signal["confidence"] -= 0.15
                notes.append(f"Low scoring: {home_scored:.1f} / {away_scored:.1f}")

        # Check BTTS rate
        home_btts = _safe_float(home_stats.get("bttsRate", home_stats.get("btts")))
        away_btts = _safe_float(away_stats.get("bttsRate", away_stats.get("btts")))
        if home_btts is not None and away_btts is not None:
            avg_btts = (home_btts + away_btts) / 2
            # Normalize if it's a count vs a rate
            if avg_btts > 1:
                avg_btts = avg_btts / 100.0 if avg_btts > 10 else avg_btts / 10.0
            if avg_btts >= MIN_BTTS_RATE:
                signal["confidence"] += 0.05
                notes.append(f"BTTS rate: {avg_btts:.0%}")

        if notes:
            signal["stats_notes"] = "; ".join(notes)

    def _validate_win(self, signal, home_stats, away_stats, profits):
        """Validate Win signal."""
        notes = []
        win_profit = self._get_profit_value(profits, "Win")
        if win_profit is not None and win_profit > 0:
            signal["confidence"] += 0.05
            notes.append(f"Historical win profit: +{win_profit:.0f}%")

        if notes:
            signal["stats_notes"] = "; ".join(notes)

    def _validate_double_chance(self, signal, home_stats, away_stats, profits):
        """Validate Double Chance signal."""
        notes = []
        dc_profit = self._get_profit_value(profits, "Double")
        if dc_profit is not None and dc_profit > 0:
            signal["confidence"] += 0.05
            notes.append(f"Historical DC profit: +{dc_profit:.0f}%")

        if notes:
            signal["stats_notes"] = "; ".join(notes)

    def _get_profit_value(self, profits, keyword):
        """Extract profit value from profits response matching keyword."""
        if not profits or not profits.get("data"):
            return None

        data = profits["data"]
        if isinstance(data, dict):
            for key, val in data.items():
                if keyword.lower() in key.lower():
                    return _safe_float(val)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name", item.get("type", ""))
                    if keyword.lower() in name.lower():
                        return _safe_float(item.get("profit", item.get("value")))
        return None


def _safe_float(val):
    """Safely convert to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
