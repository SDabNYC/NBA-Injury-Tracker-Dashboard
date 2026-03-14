"""
Fetches today's NBA schedule.
Always uses Eastern Time date (NBA's official timezone) to avoid
mismatches when the system clock is in a different timezone.
"""

import time
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
from nba_api.live.nba.endpoints import scoreboard as live_scoreboard
from nba_api.stats.endpoints import scoreboardv2

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


@dataclass
class Game:
    game_id: str
    home_team_abbrev: str
    away_team_abbrev: str
    home_team_name: str
    away_team_name: str
    game_time: str
    status: str
    home_score: Optional[int]
    away_score: Optional[int]


def get_todays_games() -> list[Game]:
    """
    Fetch today's NBA games using Eastern Time date.
    Tries live scoreboard first, falls back to ScoreboardV2.
    """
    # Always use ET date — NBA's official timezone
    today_et = datetime.now(ET).strftime("%Y-%m-%d")
    logger.info(f"Fetching schedule for ET date: {today_et}")

    # Try live scoreboard
    try:
        games = _fetch_live_scoreboard(today_et)
        if games:
            logger.info(f"Live scoreboard: {len(games)} games on {today_et}")
            return games
    except Exception as e:
        logger.warning(f"Live scoreboard failed: {e}")

    # Fallback: ScoreboardV2 with explicit date
    try:
        time.sleep(0.6)
        games = _fetch_stats_scoreboard(today_et)
        logger.info(f"ScoreboardV2: {len(games)} games on {today_et}")
        return games
    except Exception as e:
        logger.error(f"ScoreboardV2 also failed: {e}")

    return []


def _fetch_live_scoreboard(today_et: str) -> list[Game]:
    """Use the live NBA scoreboard endpoint, filter to today's ET date only."""
    sb   = live_scoreboard.ScoreBoard()
    data = sb.get_dict()

    games = []
    for g in data.get("scoreboard", {}).get("games", []):
        # Filter: only include games scheduled for today (ET)
        game_time_utc = g.get("gameTimeUTC", "")
        if game_time_utc:
            try:
                import re as _re
                ts = _re.sub(r"\.\d+", "", game_time_utc).replace("Z", "+00:00")
                dt_et = datetime.fromisoformat(ts).astimezone(ET)
                if dt_et.strftime("%Y-%m-%d") != today_et:
                    continue
            except Exception:
                pass

        home = g["homeTeam"]
        away = g["awayTeam"]
        status_num = g.get("gameStatus", 1)
        status = "Scheduled" if status_num == 1 else ("In Progress" if status_num == 2 else "Final")
        game_time_display = _format_game_time(game_time_utc)

        games.append(Game(
            game_id=g.get("gameId", ""),
            home_team_abbrev=home.get("teamTricode", ""),
            away_team_abbrev=away.get("teamTricode", ""),
            home_team_name=f"{home.get('teamCity', '')} {home.get('teamName', '')}".strip(),
            away_team_name=f"{away.get('teamCity', '')} {away.get('teamName', '')}".strip(),
            game_time=game_time_display,
            status=status,
            home_score=home.get("score"),
            away_score=away.get("score"),
        ))
    return games


def _fetch_stats_scoreboard(today_et: str) -> list[Game]:
    """Fallback: ScoreboardV2 with explicit ET date."""
    sb = scoreboardv2.ScoreboardV2(game_date=today_et, league_id="00")
    time.sleep(0.6)

    line_score  = sb.line_score.get_data_frame()
    game_header = sb.game_header.get_data_frame()

    games = []
    for _, header_row in game_header.iterrows():
        game_id = str(header_row["GAME_ID"])
        teams   = line_score[line_score["GAME_ID"] == header_row["GAME_ID"]]
        if len(teams) < 2:
            continue

        away_row = teams.iloc[0]
        home_row = teams.iloc[1]
        status_num = header_row.get("GAME_STATUS_ID", 1)
        status = "Scheduled" if status_num == 1 else ("In Progress" if status_num == 2 else "Final")

        games.append(Game(
            game_id=game_id,
            home_team_abbrev=str(home_row.get("TEAM_ABBREVIATION", "")),
            away_team_abbrev=str(away_row.get("TEAM_ABBREVIATION", "")),
            home_team_name=str(home_row.get("TEAM_CITY_NAME", "") + " " + home_row.get("TEAM_NAME", "")).strip(),
            away_team_name=str(away_row.get("TEAM_CITY_NAME", "") + " " + away_row.get("TEAM_NAME", "")).strip(),
            game_time=str(header_row.get("GAME_STATUS_TEXT", "TBD")).strip(),
            status=status,
            home_score=int(home_row["PTS"]) if pd.notna(home_row.get("PTS")) else None,
            away_score=int(away_row["PTS"]) if pd.notna(away_row.get("PTS")) else None,
        ))
    return games


def _format_game_time(utc_string: str) -> str:
    """Convert UTC ISO string to Eastern Time display."""
    if not utc_string:
        return "TBD"
    try:
        from datetime import timezone
        import re
        # Handle both "2025-03-13T00:00:00Z" and similar formats
        utc_string = re.sub(r"\.\d+", "", utc_string).replace("Z", "+00:00")
        dt_utc = datetime.fromisoformat(utc_string)
        # Convert to Eastern (UTC-5 in winter, UTC-4 in summer — approximate)
        from zoneinfo import ZoneInfo
        dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
        return dt_et.strftime("%-I:%M %p ET")
    except Exception:
        return utc_string


def get_teams_playing_today() -> set[str]:
    """Return a set of team abbreviations playing today."""
    games = get_todays_games()
    teams = set()
    for g in games:
        teams.add(g.home_team_abbrev)
        teams.add(g.away_team_abbrev)
    return teams
