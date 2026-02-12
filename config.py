"""
Configuration for the football prediction system.
"""

# sstats.net API
API_BASE_URL = "https://api.sstats.net"
API_KEY = "3nyawhy83wblului"

# Glicko2 trend analysis
TREND_MATCHES = 7          # Number of recent matches to analyze for trend
MIN_MATCHES_FOR_TREND = 4  # Minimum matches required to calculate trend

# Rating deviation filter — high RD means unreliable rating
MAX_RD = 120  # Skip teams with RD above this (default Glicko2 RD is 350 for new)

# Trend thresholds (rating change per match)
STRONG_TREND_THRESHOLD = 15    # Rating change per match to consider "strong" trend
MODERATE_TREND_THRESHOLD = 7   # Rating change per match to consider "moderate" trend
CONVERGENCE_THRESHOLD = 80     # Rating gap below which we consider graphs "converging"
CROSSING_RECENCY = 3           # How many matches back to check for crossing

# Value betting — minimum odds to consider a bet worthwhile
MIN_ODDS = {
    "under_2.5": 1.60,
    "under_2": 1.50,
    "btts_yes": 1.65,
    "win": 1.40,
    "double_chance": 1.25,
}

# Confidence thresholds
MIN_CONFIDENCE = 0.55  # Minimum confidence to output a prediction

# xG and stats filters
MAX_AVG_GOALS_FOR_UNDER = 2.3    # Average goals in recent matches for Under signal
MIN_AVG_GOALS_FOR_BTTS = 1.0     # Min avg goals per team for BTTS signal
MIN_BTTS_RATE = 0.45             # Min BTTS rate in recent matches

# Top leagues preset (ID → display name)
# Used by --top flag. IDs follow API-Football standard numbering.
# If IDs don't match your API, the system also filters by league name keywords.
TOP_LEAGUES = {
    39:  "England. Premier League",
    140: "Spain. La Liga",
    78:  "Germany. Bundesliga",
    135: "Italy. Serie A",
    61:  "France. Ligue 1",
    94:  "Portugal. Primeira Liga",
    88:  "Netherlands. Eredivisie",
    71:  "Brazil. Série A",
    119: "Denmark. Superligaen",
    113: "Sweden. Allsvenskan",
}

# Name keywords for fallback matching (case-insensitive)
# Used when league IDs don't match — matches if ANY keyword is found in league name
TOP_LEAGUE_KEYWORDS = [
    "premier league",
    "la liga", "laliga",
    "bundesliga",
    "serie a",
    "ligue 1",
    "primeira liga", "liga portugal",
    "eredivisie",
    "brasileir", "série a", "serie a",
    "superliga", "superligaen",
    "allsvenskan",
]

# Output
TIMEZONE = 3  # UTC+3 (Moscow)
OUTPUT_FORMAT = "table"  # "table" or "json"
