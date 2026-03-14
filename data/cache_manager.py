"""
Cache manager.

Cache keys include today's date so the cache automatically
invalidates when the day changes — no more stale yesterday data.

TTLs are secondary safety nets within the same day.
"""

import streamlit as st
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

# TTLs within a single day (secondary safety net)
SCHEDULE_TTL = 300     # 5 min — games update frequently
INJURIES_TTL = 900     # 15 min — PDF updates ~every 15 min on game day
STATS_TTL    = 3600    # 1 hour — season stats stable within a day


def _today() -> str:
    """Returns today's date string — used as part of cache keys."""
    return date.today().isoformat()  # e.g. "2026-03-14"


@st.cache_data(ttl=SCHEDULE_TTL, show_spinner=False)
def cached_get_todays_games(today: str):
    """today param is part of cache key — forces refresh on new day."""
    from data.schedule import get_todays_games
    return get_todays_games()


@st.cache_data(ttl=INJURIES_TTL, show_spinner=False)
def cached_get_all_injuries(today: str):
    """Refreshes every 15 min and always on a new day."""
    from data.injuries import get_all_injuries
    return get_all_injuries()


@st.cache_data(ttl=STATS_TTL, show_spinner=False)
def cached_get_all_player_stats(today: str, last_n_games: int = 15):
    from data.player_stats import get_all_player_stats
    return get_all_player_stats(last_n_games=last_n_games)


@st.cache_data(ttl=STATS_TTL, show_spinner=False)
def cached_get_all_team_totals(today: str, last_n_games: int = 15):
    from data.player_stats import get_all_team_totals
    return get_all_team_totals(last_n_games=last_n_games)


def load_all_data(force_refresh: bool = False, last_n_games: int = 15):
    if force_refresh:
        st.cache_data.clear()
        logger.info("Cache cleared — fetching fresh data")

    today = _today()

    result = {
        "games": [], "teams_playing": set(),
        "all_injuries": [], "player_stats": {},
        "team_totals": {}, "errors": [],
        "loaded_at": datetime.now(),
        "last_n_games": last_n_games,
        "date": today,
    }

    with st.spinner("📅 Fetching today's schedule..."):
        try:
            result["games"] = cached_get_todays_games(today)
            result["teams_playing"] = (
                {g.home_team_abbrev for g in result["games"]} |
                {g.away_team_abbrev for g in result["games"]}
            )
        except Exception as e:
            result["errors"].append(f"Schedule: {e}")
            logger.error(f"Schedule: {e}")

    with st.spinner("🩹 Fetching NBA injury report PDF..."):
        try:
            result["all_injuries"] = cached_get_all_injuries(today)
        except Exception as e:
            result["errors"].append(f"Injuries: {e}")
            logger.error(f"Injuries: {e}")

    window = f"last {last_n_games} games" if last_n_games > 0 else "full season"
    with st.spinner(f"📊 Fetching player stats ({window})..."):
        try:
            result["player_stats"] = cached_get_all_player_stats(today, last_n_games)
        except Exception as e:
            result["errors"].append(f"Player stats: {e}")
            logger.error(f"Stats: {e}")

    with st.spinner(f"🏀 Fetching team totals..."):
        try:
            result["team_totals"] = cached_get_all_team_totals(today, last_n_games)
        except Exception as e:
            result["errors"].append(f"Team totals: {e}")
            logger.error(f"Team totals: {e}")

    from data.player_stats import enrich_with_team_shares
    result["player_stats"] = enrich_with_team_shares(
        result["player_stats"], result["team_totals"]
    )

    return result
