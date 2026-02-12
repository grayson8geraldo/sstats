"""
API client for sstats.net
"""

import time
import requests
from config import API_BASE_URL, API_KEY, TIMEZONE


class SStatsAPI:
    def __init__(self):
        self.base_url = API_BASE_URL
        self.session = requests.Session()
        self.session.params = {"apikey": API_KEY, "timeZone": TIMEZONE}

    def _get(self, endpoint, params=None, retries=3):
        """Make GET request with retries."""
        url = f"{self.base_url}/{endpoint}"
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[ERROR] API call failed: {endpoint} — {e}")
                    return None

    def _post(self, endpoint, json_data=None, retries=3):
        """Make POST request with retries."""
        url = f"{self.base_url}/{endpoint}"
        for attempt in range(retries):
            try:
                resp = self.session.post(url, json=json_data, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[ERROR] API POST failed: {endpoint} — {e}")
                    return None

    def get_upcoming_matches(self, limit=200):
        """Get upcoming matches (tomorrow and beyond)."""
        return self._get("Games/list", {"upcoming": "true", "limit": limit, "order": 1})

    def get_today_matches(self):
        """Get today's matches."""
        return self._get("Games/list", {"today": "true", "limit": 500, "order": 1})

    def get_matches_by_date(self, date_str):
        """Get matches for a specific date (YYYY-MM-DD)."""
        return self._get("Games/list", {"date": date_str, "limit": 500, "order": 1})

    def get_glicko(self, game_id):
        """Get Glicko2 ratings for a specific match."""
        return self._get(f"Games/glicko/{game_id}")

    def get_match_details(self, game_id):
        """Get detailed match info (stats, lineups, events)."""
        return self._get(f"Games/{game_id}")

    def get_team_recent_matches(self, team_id, limit=15):
        """Get recent finished matches for a team."""
        return self._get("Games/list", {
            "team": team_id,
            "ended": "true",
            "limit": limit,
            "order": -1,
        })

    def get_last_games_stats(self, game_id, limit=10, same_league=False):
        """Get average stats from last N games for both teams in a fixture."""
        params = {"gameId": game_id, "limit": limit}
        if same_league:
            params["sameLeague"] = "true"
        return self._get("Games/last-games-stats", params)

    def get_odds(self, game_id):
        """Get pre-match odds."""
        return self._get(f"Odds/{game_id}")

    def get_profits(self, game_id, limit=25):
        """Get historical profit analysis for a match."""
        return self._get("Games/profits", {"gameId": game_id, "limit": limit})

    def get_injuries(self, game_id):
        """Get injury information for a match."""
        return self._get("Games/injuries", {"gameId": game_id})

    def get_team_info(self, team_id):
        """Get team details."""
        return self._get(f"Teams/{team_id}")

    def get_text_summary(self, game_id, limit=10):
        """Get text summary for a match."""
        return self._get("Games/text-summary", {"id": game_id, "limit": limit})

    def query_matches(self, condition, fields, limit=100):
        """Advanced SQL-like query."""
        return self._post("Games/query", {
            "condition": condition,
            "fields": fields,
            "format": "json",
            "limit": limit,
            "order": "Date",
        })
