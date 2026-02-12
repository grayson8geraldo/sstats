"""
Glicko2 trend analyzer — core strategy logic.

Analyzes Glicko2 rating dynamics for both teams and generates betting signals.
"""

import numpy as np
from config import (
    TREND_MATCHES, MIN_MATCHES_FOR_TREND, MAX_RD,
    STRONG_TREND_THRESHOLD, MODERATE_TREND_THRESHOLD,
    CONVERGENCE_THRESHOLD, CROSSING_RECENCY,
    MIN_CONFIDENCE,
)


def compute_trend(ratings):
    """
    Compute the trend (slope) of a rating series using linear regression.
    Returns slope (rating change per match) and R² (fit quality).
    """
    if len(ratings) < MIN_MATCHES_FOR_TREND:
        return 0.0, 0.0

    x = np.arange(len(ratings), dtype=float)
    y = np.array(ratings, dtype=float)

    # Linear regression
    n = len(x)
    sum_x = np.sum(x)
    sum_y = np.sum(y)
    sum_xy = np.sum(x * y)
    sum_x2 = np.sum(x ** 2)

    denom = n * sum_x2 - sum_x ** 2
    if denom == 0:
        return 0.0, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    # R² — goodness of fit
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return slope, r_squared


def detect_crossing(home_ratings, away_ratings, recency=CROSSING_RECENCY):
    """
    Detect if the rating graphs crossed recently.
    Returns (crossed: bool, matches_ago: int or None).
    """
    if len(home_ratings) < 2 or len(away_ratings) < 2:
        return False, None

    min_len = min(len(home_ratings), len(away_ratings))
    home = home_ratings[-min_len:]
    away = away_ratings[-min_len:]

    # Check differences: sign change = crossing
    diffs = [h - a for h, a in zip(home, away)]

    for i in range(len(diffs) - 1, 0, -1):
        if diffs[i] * diffs[i - 1] < 0:  # Sign change
            matches_ago = len(diffs) - 1 - i
            if matches_ago <= recency:
                return True, matches_ago

    return False, None


def detect_convergence(home_ratings, away_ratings):
    """
    Detect if rating graphs are converging (getting closer).
    Returns (converging: bool, current_gap: float, trend_of_gap: float).
    """
    if len(home_ratings) < MIN_MATCHES_FOR_TREND or len(away_ratings) < MIN_MATCHES_FOR_TREND:
        return False, None, None

    min_len = min(len(home_ratings), len(away_ratings))
    home = home_ratings[-min_len:]
    away = away_ratings[-min_len:]

    gaps = [abs(h - a) for h, a in zip(home, away)]
    current_gap = gaps[-1]

    gap_trend, _ = compute_trend(gaps)

    converging = gap_trend < -MODERATE_TREND_THRESHOLD and current_gap < CONVERGENCE_THRESHOLD * 2
    return converging, current_gap, gap_trend


def classify_trend(slope):
    """Classify trend as strong_up, up, flat, down, strong_down."""
    if slope > STRONG_TREND_THRESHOLD:
        return "strong_up"
    elif slope > MODERATE_TREND_THRESHOLD:
        return "up"
    elif slope < -STRONG_TREND_THRESHOLD:
        return "strong_down"
    elif slope < -MODERATE_TREND_THRESHOLD:
        return "down"
    return "flat"


class GlickoAnalyzer:
    """Analyzes Glicko2 data and generates betting signals."""

    def __init__(self, api_client):
        self.api = api_client
        self._history_cache = {}  # team_id → rating history

    def build_rating_history(self, team_id, limit=TREND_MATCHES + 3):
        """
        Build Glicko2 rating history for a team from their recent matches.
        Uses cache to avoid duplicate API calls for the same team.
        Returns list of dicts sorted oldest→newest.
        """
        if team_id in self._history_cache:
            return self._history_cache[team_id]

        resp = self.api.get_team_recent_matches(team_id, limit=limit)
        if not resp or not resp.get("data"):
            self._history_cache[team_id] = []
            return []

        matches = resp["data"]
        history = []

        for match in matches:
            game_id = match.get("id")
            if not game_id:
                continue

            glicko_resp = self.api.get_glicko(game_id)
            if not glicko_resp or not glicko_resp.get("data"):
                continue

            glicko = glicko_resp["data"].get("glicko")
            if not glicko:
                continue

            home_team = glicko_resp["data"].get("fixture", {}).get("homeTeam", {})
            away_team = glicko_resp["data"].get("fixture", {}).get("awayTeam", {})

            if home_team.get("id") == team_id:
                rating = glicko.get("homeRating")
                rd = glicko.get("homeRd")
                vol = glicko.get("homeVolatility")
            elif away_team.get("id") == team_id:
                rating = glicko.get("awayRating")
                rd = glicko.get("awayRd")
                vol = glicko.get("awayVolatility")
            else:
                continue

            if rating is not None:
                history.append({
                    "game_id": game_id,
                    "rating": rating,
                    "rd": rd,
                    "volatility": vol,
                })

        history.reverse()
        self._history_cache[team_id] = history
        return history

    def analyze_match(self, game_id, cached_glicko=None):
        """
        Full analysis for a single upcoming match.
        Uses cached_glicko if available (from pre-filter phase).
        Returns dict with signals and confidence.
        """
        if cached_glicko:
            data = cached_glicko
        else:
            glicko_resp = self.api.get_glicko(game_id)
            if not glicko_resp or not glicko_resp.get("data"):
                return None
            data = glicko_resp["data"]
        fixture = data.get("fixture", {})
        glicko = data.get("glicko", {})

        home_team = fixture.get("homeTeam", {})
        away_team = fixture.get("awayTeam", {})
        home_id = home_team.get("id")
        away_id = away_team.get("id")

        if not home_id or not away_id:
            return None

        # Check RD — skip if ratings are unreliable
        home_rd = glicko.get("homeRd", 999)
        away_rd = glicko.get("awayRd", 999)
        if home_rd > MAX_RD or away_rd > MAX_RD:
            return None

        # Build rating histories
        home_history = self.build_rating_history(home_id)
        away_history = self.build_rating_history(away_id)

        if len(home_history) < MIN_MATCHES_FOR_TREND or len(away_history) < MIN_MATCHES_FOR_TREND:
            return None

        home_ratings = [h["rating"] for h in home_history[-TREND_MATCHES:]]
        away_ratings = [h["rating"] for h in away_history[-TREND_MATCHES:]]

        # Compute trends
        home_slope, home_r2 = compute_trend(home_ratings)
        away_slope, away_r2 = compute_trend(away_ratings)

        home_trend = classify_trend(home_slope)
        away_trend = classify_trend(away_slope)

        # Detect crossing and convergence
        crossed, cross_ago = detect_crossing(home_ratings, away_ratings)
        converging, gap, gap_trend = detect_convergence(home_ratings, away_ratings)

        # Current ratings
        current_home = glicko.get("homeRating", 0)
        current_away = glicko.get("awayRating", 0)
        home_xg = glicko.get("homeXg")
        away_xg = glicko.get("awayXg")
        home_win_prob = glicko.get("homeWinProbability")
        away_win_prob = glicko.get("awayWinProbability")

        # Generate signals
        signals = self._generate_signals(
            home_trend, away_trend, home_slope, away_slope,
            home_r2, away_r2,
            crossed, cross_ago,
            converging, gap, gap_trend,
            current_home, current_away,
            home_xg, away_xg,
            home_win_prob, away_win_prob,
            fixture, game_id,
        )

        return {
            "game_id": game_id,
            "home_team": home_team.get("name", "?"),
            "away_team": away_team.get("name", "?"),
            "league": fixture.get("season", {}).get("league", {}).get("name", "?"),
            "date": fixture.get("date", "?"),
            "home_rating": current_home,
            "away_rating": current_away,
            "home_rd": home_rd,
            "away_rd": away_rd,
            "home_trend": home_trend,
            "away_trend": away_trend,
            "home_slope": round(home_slope, 1),
            "away_slope": round(away_slope, 1),
            "home_xg": home_xg,
            "away_xg": away_xg,
            "home_win_prob": home_win_prob,
            "away_win_prob": away_win_prob,
            "crossed_recently": crossed,
            "crossing_matches_ago": cross_ago,
            "converging": converging,
            "rating_gap": round(gap, 1) if gap else None,
            "signals": signals,
        }

    def _generate_signals(
        self, home_trend, away_trend, home_slope, away_slope,
        home_r2, away_r2,
        crossed, cross_ago,
        converging, gap, gap_trend,
        current_home, current_away,
        home_xg, away_xg,
        home_win_prob, away_win_prob,
        fixture, game_id,
    ):
        """Generate betting signals based on Glicko2 analysis."""
        signals = []
        min_r2 = 0.3  # Minimum R² to trust the trend

        # --- STRATEGY 1: Both trends DOWN → Under 2/2.5 ---
        if home_trend in ("down", "strong_down") and away_trend in ("down", "strong_down"):
            confidence = 0.5
            # Boost if both have good R²
            if home_r2 > min_r2 and away_r2 > min_r2:
                confidence += 0.1
            # Boost if strong trends
            if home_trend == "strong_down" and away_trend == "strong_down":
                confidence += 0.1
            # Boost/reduce based on xG
            if home_xg is not None and away_xg is not None:
                total_xg = home_xg + away_xg
                if total_xg < 2.0:
                    confidence += 0.1
                elif total_xg > 2.8:
                    confidence -= 0.15

            self._add_under_signal(signals, confidence, fixture, game_id)

        # --- STRATEGY 2: Both trends UP → BTTS Yes ---
        if home_trend in ("up", "strong_up") and away_trend in ("up", "strong_up"):
            confidence = 0.5
            if home_r2 > min_r2 and away_r2 > min_r2:
                confidence += 0.1
            if home_trend == "strong_up" and away_trend == "strong_up":
                confidence += 0.1
            # Boost based on xG
            if home_xg is not None and away_xg is not None:
                if home_xg > 1.0 and away_xg > 1.0:
                    confidence += 0.1
                elif home_xg < 0.7 or away_xg < 0.7:
                    confidence -= 0.15

            self._add_btts_signal(signals, confidence, fixture, game_id)

        # --- STRATEGY 3: Recent crossing → Winner is the one going up ---
        if crossed and cross_ago is not None:
            if home_slope > MODERATE_TREND_THRESHOLD and away_slope < -MODERATE_TREND_THRESHOLD:
                confidence = 0.5
                recency_boost = max(0, (CROSSING_RECENCY - cross_ago) * 0.05)
                confidence += recency_boost
                if home_r2 > min_r2:
                    confidence += 0.1
                # Boost by win probability
                if home_win_prob and home_win_prob > 0.45:
                    confidence += 0.05
                self._add_win_signal(signals, "home", confidence, fixture, game_id)

            elif away_slope > MODERATE_TREND_THRESHOLD and home_slope < -MODERATE_TREND_THRESHOLD:
                confidence = 0.5
                recency_boost = max(0, (CROSSING_RECENCY - cross_ago) * 0.05)
                confidence += recency_boost
                if away_r2 > min_r2:
                    confidence += 0.1
                if away_win_prob and away_win_prob > 0.35:
                    confidence += 0.05
                self._add_win_signal(signals, "away", confidence, fixture, game_id)

        # --- STRATEGY 4: Converging → Double chance for the rising team ---
        if converging and gap is not None:
            if home_slope > MODERATE_TREND_THRESHOLD and away_slope < 0:
                confidence = 0.5
                if gap < CONVERGENCE_THRESHOLD:
                    confidence += 0.1
                if home_r2 > min_r2:
                    confidence += 0.05
                self._add_double_chance_signal(signals, "home", confidence, fixture, game_id)

            elif away_slope > MODERATE_TREND_THRESHOLD and home_slope < 0:
                confidence = 0.5
                if gap < CONVERGENCE_THRESHOLD:
                    confidence += 0.1
                if away_r2 > min_r2:
                    confidence += 0.05
                self._add_double_chance_signal(signals, "away", confidence, fixture, game_id)

        # Filter by minimum confidence
        signals = [s for s in signals if s["confidence"] >= MIN_CONFIDENCE]
        return signals

    def _get_odds_from_fixture(self, fixture, market_name):
        """Extract odds from fixture data by market name."""
        odds_list = fixture.get("odds", []) or []
        for market in odds_list:
            if market.get("marketName") == market_name:
                return {o["name"]: o.get("value") for o in market.get("odds", [])}
        return {}

    def _add_under_signal(self, signals, confidence, fixture, game_id):
        """Add Under 2.5 signal."""
        odds = self._get_odds_from_fixture(fixture, "Goals Over/Under")
        under_25_odds = odds.get("Under 2.5")

        signal = {
            "type": "under_2.5",
            "label": "ТМ 2.5 (Under 2.5 Goals)",
            "confidence": round(min(confidence, 0.85), 2),
            "odds": under_25_odds,
            "reason": "Both teams' Glicko2 ratings declining — teams in poor form",
        }
        signals.append(signal)

    def _add_btts_signal(self, signals, confidence, fixture, game_id):
        """Add BTTS Yes signal."""
        odds = self._get_odds_from_fixture(fixture, "Both Teams Score")
        btts_odds = odds.get("Yes")

        signal = {
            "type": "btts_yes",
            "label": "Обе забьют — Да (BTTS Yes)",
            "confidence": round(min(confidence, 0.85), 2),
            "odds": btts_odds,
            "reason": "Both teams' Glicko2 ratings rising — both in attacking form",
        }
        signals.append(signal)

    def _add_win_signal(self, signals, side, confidence, fixture, game_id):
        """Add Win signal."""
        odds = self._get_odds_from_fixture(fixture, "Match Winner")
        if side == "home":
            win_odds = odds.get("Home")
            label = "П1 (Home Win)"
        else:
            win_odds = odds.get("Away")
            label = "П2 (Away Win)"

        signal = {
            "type": f"win_{side}",
            "label": label,
            "confidence": round(min(confidence, 0.85), 2),
            "odds": win_odds,
            "reason": f"Glicko2 graphs crossed recently — {side} team rising",
        }
        signals.append(signal)

    def _add_double_chance_signal(self, signals, side, confidence, fixture, game_id):
        """Add Double Chance signal."""
        odds = self._get_odds_from_fixture(fixture, "Double Chance")
        if side == "home":
            dc_odds = odds.get("Home/Draw")
            label = "1X — Дома не проиграет (Home or Draw)"
        else:
            dc_odds = odds.get("Draw/Away")
            label = "X2 — Гости не проиграют (Draw or Away)"

        signal = {
            "type": f"double_chance_{side}",
            "label": label,
            "confidence": round(min(confidence, 0.85), 2),
            "odds": dc_odds,
            "reason": f"Glicko2 graphs converging — {side} team gaining momentum",
        }
        signals.append(signal)
