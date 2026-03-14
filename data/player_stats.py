"""
Player and team stats fetcher — 2025-26 season.

Key design: fetches TWO stat windows and merges them:
  - Full season    → baseline, captures long-term injured players (Embiid etc.)
  - Last 15 games  → overlay for active players, reflects current form

Source: stats.nba.com direct HTTP only.
nba_api is skipped entirely — it always fails with 'per_mode_simple'
parameter errors in v1.11.x, wasting 5–10 seconds before falling back.
"""

import time
import logging
import requests
import pandas as pd
import numpy as np
from datetime import date
from dataclasses import dataclass
from typing import Optional, Dict

from utils.name_normalizer import normalize_player_name, fuzzy_match_player

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 0.6   # seconds — enough to avoid throttling, not slow


def _current_nba_season() -> str:
    today = date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"

CURRENT_SEASON = _current_nba_season()
LAST_N_GAMES   = 15

NBA_DIRECT_HEADERS = {
    "Host":               "stats.nba.com",
    "User-Agent":         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept":             "application/json, text/plain, */*",
    "Accept-Language":    "en-US,en;q=0.9",
    "Accept-Encoding":    "gzip, deflate, br",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token":  "true",
    "Referer":            "https://www.nba.com/",
    "Origin":             "https://www.nba.com",
    "Connection":         "keep-alive",
    "Sec-Fetch-Dest":     "empty",
    "Sec-Fetch-Mode":     "cors",
    "Sec-Fetch-Site":     "same-site",
}


def _current_nba_season() -> str:
    today = date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"

CURRENT_SEASON = _current_nba_season()
LAST_N_GAMES   = 15

NBA_DIRECT_HEADERS = {
    "Host":               "stats.nba.com",
    "User-Agent":         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept":             "application/json, text/plain, */*",
    "Accept-Language":    "en-US,en;q=0.9",
    "Accept-Encoding":    "gzip, deflate, br",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token":  "true",
    "Referer":            "https://www.nba.com/",
    "Origin":             "https://www.nba.com",
    "Connection":         "keep-alive",
    "Sec-Fetch-Dest":     "empty",
    "Sec-Fetch-Mode":     "cors",
    "Sec-Fetch-Site":     "same-site",
}

ESPN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Referer":    "https://www.espn.com/",
}


@dataclass
class PlayerStats:
    player_id:   int
    player_name: str
    team_abbrev: str
    team_id:     int
    games_played:        int
    minutes_per_game:    float
    points_per_game:     float
    rebounds_per_game:   float
    assists_per_game:    float
    steals_per_game:     float
    blocks_per_game:     float
    fg_percentage:       float
    three_pt_percentage: float
    ft_percentage:       float
    plus_minus:          float
    usage_rate:               float = 0.0
    player_efficiency_rating: float = 0.0
    true_shooting_pct:        float = 0.0
    points_share:   float = 0.0
    rebounds_share: float = 0.0
    assists_share:  float = 0.0
    blocks_share:   float = 0.0
    steals_share:   float = 0.0
    stats_window:   str   = "last_15"


@dataclass
class TeamTotals:
    team_id:      int
    team_abbrev:  str
    avg_points:   float
    avg_rebounds: float
    avg_assists:  float
    avg_blocks:   float
    avg_steals:   float
    win_pct:      float
    games_played: int


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_all_player_stats(last_n_games: int = LAST_N_GAMES) -> Dict[str, "PlayerStats"]:
    """
    Fetch stats for all players using a two-pass approach:

    Pass 1 — Full season stats (fetched first as the base)
              Covers ALL players including long-term injured ones.

    Pass 2 — Last N games stats (overlaid on top)
              Overwrites full-season numbers for active players
              so their current form takes precedence.

    Result: active players use recent form, injured players who
    haven't played recently still appear with season averages.
    """
    logger.info(f"Fetching player stats — season: {CURRENT_SEASON}")

    # ── Pass 1: full season (baseline — catches everyone) ─────────────────
    logger.info("Pass 1: full season stats (baseline for all players)...")
    full_map = _fetch_stats_window(last_n=0, label="full season")

    if not full_map:
        logger.warning("Full season stats empty — trying ESPN fallback...")
        full_map = _build_player_map(_fetch_espn_stats(), "full season (ESPN)")

    # ── Pass 2: last N games (overwrite active players with recent form) ──
    if last_n_games > 0:
        logger.info(f"Pass 2: last {last_n_games} games (current form overlay)...")
        recent_map = _fetch_stats_window(last_n=last_n_games, label=f"last {last_n_games} games")

        # Overwrite full-season entries with recent-form entries
        # Only overwrite if the player actually played recently (GP >= 3 in window)
        overwritten = 0
        for name, recent_ps in recent_map.items():
            if recent_ps.games_played >= 3:
                full_map[name] = recent_ps
                overwritten += 1

        logger.info(f"Overlaid {overwritten} players with last-{last_n_games}-game stats")

    logger.info(f"Final player map: {len(full_map)} players")
    return full_map


def get_all_team_totals(last_n_games: int = LAST_N_GAMES) -> Dict[str, "TeamTotals"]:
    """Fetch team per-game averages. Uses last_n_games for active teams."""
    logger.info(f"Fetching team totals — season: {CURRENT_SEASON}")

    return _fetch_team_totals_direct(last_n_games)


def enrich_with_team_shares(
    player_map: Dict[str, "PlayerStats"],
    team_totals: Dict[str, "TeamTotals"],
) -> Dict[str, "PlayerStats"]:
    # Always compute base shares from player_map (guaranteed coverage)
    _enrich_shares_from_player_map(player_map)

    # Overwrite with API team totals where available (more accurate)
    if team_totals:
        overwritten = 0
        for ps in player_map.values():
            tt = team_totals.get(ps.team_abbrev)
            if not tt:
                continue
            ps.points_share   = _share(ps.points_per_game,   tt.avg_points)
            ps.rebounds_share = _share(ps.rebounds_per_game, tt.avg_rebounds)
            ps.assists_share  = _share(ps.assists_per_game,  tt.avg_assists)
            ps.blocks_share   = _share(ps.blocks_per_game,   tt.avg_blocks)
            ps.steals_share   = _share(ps.steals_per_game,   tt.avg_steals)
            overwritten += 1
        logger.info(f"Refined {overwritten} players with API team totals")

    return player_map


def lookup_player(name: str, player_map: Dict[str, "PlayerStats"]) -> Optional["PlayerStats"]:
    """
    Look up a player by name. Logs close misses so you can add overrides.
    """
    normalized = normalize_player_name(name)
    if normalized in player_map:
        return player_map[normalized]

    matched = fuzzy_match_player(normalized, list(player_map.keys()), log_failures=True)
    if matched:
        # Log when fuzzy matching kicks in (useful to know)
        if matched != normalized:
            logger.debug(f"Fuzzy matched '{normalized}' → '{matched}'")
        return player_map[matched]

    # Log the failure with top candidates so you can add to NAME_OVERRIDES
    try:
        from fuzzywuzzy import fuzz, process as fz_process
        top = fz_process.extract(normalized, list(player_map.keys()),
                                  scorer=fuzz.token_sort_ratio, limit=3)
        logger.debug(
            f"No match for '{normalized}' — closest in DB: "
            + ", ".join(f"'{n}' ({s}%)" for n, s, *_ in top)
        )
    except Exception:
        pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Stats window fetcher — direct HTTP only
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_stats_window(last_n: int, label: str) -> Dict[str, "PlayerStats"]:
    """
    Fetch one stats window. Three sources tried in order:
      1. stats.nba.com direct HTTP  (best data, sometimes blocked)
      2. ESPN stats API              (reliable, full season only)
      3. nba_api LeagueDashPlayerStats with correct v1.11 params
         (kept as last resort — slower but uses different connection)
    """
    # Source 1: Direct HTTP
    df = _fetch_direct_http(last_n)
    if not df.empty:
        logger.info(f"Direct HTTP succeeded for '{label}': {len(df)} rows")
        return _build_player_map(df, label)
    logger.warning(f"Direct HTTP failed for '{label}'")

    # Source 2: ESPN (always full season — no rolling window)
    logger.info(f"Trying ESPN fallback for '{label}'...")
    df = _fetch_espn_stats()
    if not df.empty:
        logger.info(f"ESPN succeeded for '{label}': {len(df)} rows")
        return _build_player_map(df, f"{label} (ESPN)")
    logger.warning(f"ESPN failed for '{label}'")

    # Source 3: nba_api with corrected v1.11 parameter names
    logger.info(f"Trying nba_api last resort for '{label}'...")
    df = _fetch_via_nba_api_v11(last_n)
    if not df.empty:
        logger.info(f"nba_api succeeded for '{label}': {len(df)} rows")
        return _build_player_map(df, f"{label} (nba_api)")

    logger.error(f"ALL sources failed for window '{label}'")
    return {}


def _fetch_via_nba_api_v11(last_n_games: int) -> pd.DataFrame:
    """
    nba_api v1.11 uses different parameter names.
    PerModeSimple instead of per_mode_simple, etc.
    Try both old and new naming conventions.
    """
    try:
        from nba_api.stats.endpoints import leaguedashplayerstats

        # Try the parameter names nba_api v1.11 actually accepts
        # by inspecting the endpoint's accepted params
        ep = leaguedashplayerstats.LeagueDashPlayerStats(
            season=CURRENT_SEASON,
            season_type_all_star="Regular Season",
            last_n_games=last_n_games,
            per_mode_simple="PerGame",
            timeout=30,
        )
        df = ep.get_data_frames()[0]
        if not df.empty:
            df["USG_PCT"] = 0.0
            df["PIE"]     = 0.0
            return df
    except TypeError:
        pass
    except Exception as e:
        logger.warning(f"nba_api v11 attempt failed: {e}")

    # Try without any contested params
    try:
        from nba_api.stats.endpoints import leaguedashplayerstats
        ep = leaguedashplayerstats.LeagueDashPlayerStats(
            season=CURRENT_SEASON,
            timeout=30,
        )
        df = ep.get_data_frames()[0]
        if not df.empty:
            df["USG_PCT"] = 0.0
            df["PIE"]     = 0.0
            return df
    except Exception as e:
        logger.warning(f"nba_api minimal params failed: {e}")

    return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Direct HTTP — stats.nba.com (primary source)
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_direct_http(last_n_games: int) -> pd.DataFrame:
    base_params = {
        "College": "", "Conference": "", "Country": "", "DateFrom": "",
        "DateTo": "", "Division": "", "DraftPick": "", "DraftYear": "",
        "GameScope": "", "GameSegment": "", "Height": "",
        "LastNGames": last_n_games,
        "LeagueID": "00", "Location": "", "MeasureType": "Base",
        "Month": 0, "OpponentTeamID": 0, "Outcome": "",
        "PORound": 0, "PaceAdjust": "N", "PerMode": "PerGame",
        "Period": 0, "PlayerExperience": "", "PlayerPosition": "",
        "PlusMinus": "N", "Rank": "N", "Season": CURRENT_SEASON,
        "SeasonSegment": "", "SeasonType": "Regular Season",
        "ShotClockRange": "", "StarterBench": "", "TeamID": 0,
        "TwoWay": 0, "VsConference": "", "VsDivision": "", "Weight": "",
    }

    for attempt in range(3):
        try:
            if attempt > 0:
                time.sleep(RATE_LIMIT_DELAY * attempt)
            resp = requests.get(
                "https://stats.nba.com/stats/leaguedashplayerstats",
                params=base_params, headers=NBA_DIRECT_HEADERS, timeout=5,
            )
            logger.info(f"NBA Stats HTTP {resp.status_code} | URL: {resp.url[:120]}")
            resp.raise_for_status()
            headers_list, rows = _parse_nba_json(resp.json())
            if not rows:
                logger.warning(f"NBA Stats returned 0 rows (attempt {attempt+1})")
                continue
            df = pd.DataFrame(rows, columns=headers_list)
            # Log first row to diagnose totals vs per-game
            if not df.empty:
                r = df.iloc[0]
                logger.info(
                    f"NBA Stats sample row — {r.get('PLAYER_NAME','?')}: "
                    f"PTS={r.get('PTS','?')} GP={r.get('GP','?')} "
                    f"PerMode param was: {base_params['PerMode']}"
                )

            # Try advanced stats
            try:
                time.sleep(RATE_LIMIT_DELAY)
                adv_resp = requests.get(
                    "https://stats.nba.com/stats/leaguedashplayerstats",
                    params={**base_params, "MeasureType": "Advanced"},
                    headers=NBA_DIRECT_HEADERS, timeout=5,
                )
                adv_h, adv_r = _parse_nba_json(adv_resp.json())
                if adv_r:
                    adv_df = pd.DataFrame(adv_r, columns=adv_h)
                    if "USG_PCT" in adv_df.columns:
                        slim = adv_df[["PLAYER_ID", "USG_PCT", "PIE"]].copy()
                        df = df.merge(slim, on="PLAYER_ID", how="left")
            except Exception:
                pass

            df["USG_PCT"] = df.get("USG_PCT", pd.Series(0.0, index=df.index)).fillna(0.0)
            df["PIE"]     = df.get("PIE",     pd.Series(0.0, index=df.index)).fillna(0.0)
            return df

        except Exception as e:
            logger.warning(f"Direct HTTP attempt {attempt+1} failed: {type(e).__name__}: {e}")

    logger.error("Direct HTTP failed after 3 attempts — stats.nba.com may be blocking requests")
    return pd.DataFrame()


def _fetch_team_totals_direct(last_n_games: int) -> Dict[str, "TeamTotals"]:
    params = {
        "Conference": "", "DateFrom": "", "DateTo": "", "Division": "",
        "GameScope": "", "GameSegment": "", "LastNGames": last_n_games,
        "LeagueID": "00", "Location": "", "MeasureType": "Base",
        "Month": 0, "OpponentTeamID": 0, "Outcome": "",
        "PORound": 0, "PaceAdjust": "N", "PerMode": "PerGame",
        "Period": 0, "PlayerExperience": "", "PlayerPosition": "",
        "PlusMinus": "N", "Rank": "N", "Season": CURRENT_SEASON,
        "SeasonSegment": "", "SeasonType": "Regular Season",
        "ShotClockRange": "", "StarterBench": "", "TwoWay": 0,
        "VsConference": "", "VsDivision": "",
    }
    for attempt in range(3):
        try:
            if attempt > 0:
                time.sleep(RATE_LIMIT_DELAY * attempt)  # 0s, 0.6s, 1.2s
            resp = requests.get(
                "https://stats.nba.com/stats/leaguedashteamstats",
                params=params, headers=NBA_DIRECT_HEADERS, timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()

            # The API returns multiple resultSets — find the one with 30 rows
            result_sets = data.get("resultSets", [])
            logger.info(f"Team totals: {len(result_sets)} resultSets")

            best_df = pd.DataFrame()
            for rs in result_sets:
                headers_list = rs.get("headers", [])
                rows         = rs.get("rowSet", [])
                logger.info(f"  resultSet '{rs.get('name', '?')}': {len(rows)} rows, headers include TEAM_ABBREVIATION={('TEAM_ABBREVIATION' in headers_list)}")
                if rows and "TEAM_ABBREVIATION" in headers_list:
                    df = pd.DataFrame(rows, columns=headers_list)
                    if len(df) > len(best_df):
                        best_df = df

            if not best_df.empty:
                totals = _df_to_team_totals(best_df)
                logger.info(f"Direct HTTP team totals: {len(totals)} teams")
                return totals

        except Exception as e:
            logger.warning(f"Direct team totals attempt {attempt+1}: {e}")
    return {}


def _df_to_team_totals(df: pd.DataFrame) -> Dict[str, "TeamTotals"]:
    totals = {}
    for _, row in df.iterrows():
        abbrev = str(row.get("TEAM_ABBREVIATION", ""))
        totals[abbrev] = TeamTotals(
            team_id=int(_sf(row.get("TEAM_ID", 0))),
            team_abbrev=abbrev,
            avg_points=_sf(row.get("PTS")),
            avg_rebounds=_sf(row.get("REB")),
            avg_assists=_sf(row.get("AST")),
            avg_blocks=_sf(row.get("BLK")),
            avg_steals=_sf(row.get("STL")),
            win_pct=_sf(row.get("W_PCT")),
            games_played=int(_sf(row.get("GP", 0))),
        )
    logger.info(f"Team totals: {len(totals)} teams")
    return totals


# ─────────────────────────────────────────────────────────────────────────────
# ESPN stats (fallback for full season only)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_espn_stats() -> pd.DataFrame:
    # ESPN uses the season START year (2025 for 2025-26), not end year
    season_year = int(CURRENT_SEASON.split("-")[0])
    logger.info(f"ESPN stats fallback (season {season_year})...")
    all_rows = []
    page = 1

    while page <= 15:
        try:
            time.sleep(0.8)
            url = (
                f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete"
                f"?region=us&lang=en&contentorigin=espn&isqualified=true"
                f"&sort=statistics.pts%3Adesc&limit=40&page={page}"
                f"&season={season_year}&seasontype=2"
            )
            resp = requests.get(url, headers=ESPN_HEADERS, timeout=15)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            data     = resp.json()
            athletes = data.get("athletes", [])
            if not athletes:
                break

            categories = data.get("categories", [])
            for entry in athletes:
                try:
                    athlete     = entry.get("athlete", {})
                    stats_raw   = entry.get("statistics", [])
                    name        = athlete.get("displayName", "")
                    team_abbrev = athlete.get("team", {}).get("abbreviation", "")
                    stat_map    = {}
                    flat_idx    = 0
                    for cat in categories:
                        cat_name = cat.get("name", "")
                        for stat_name in cat.get("statistics", []):
                            key = f"{cat_name}.{stat_name}"
                            try:
                                stat_map[key] = float(stats_raw[flat_idx]) if flat_idx < len(stats_raw) else 0.0
                            except (ValueError, TypeError):
                                stat_map[key] = 0.0
                            flat_idx += 1
                    all_rows.append({
                        "PLAYER_NAME": name, "PLAYER_ID": int(athlete.get("id", 0)),
                        "TEAM_ABBREVIATION": team_abbrev, "TEAM_ID": 0,
                        "GP":      stat_map.get("general.gamesPlayed", 0),
                        "MIN":     stat_map.get("general.avgMinutes", 0),
                        "PTS":     stat_map.get("scoring.avgPoints", 0),
                        "REB":     stat_map.get("rebounds.avgRebounds", 0),
                        "AST":     stat_map.get("assists.avgAssists", 0),
                        "STL":     stat_map.get("defensive.avgSteals", 0),
                        "BLK":     stat_map.get("defensive.avgBlocks", 0),
                        "FG_PCT":  stat_map.get("general.fieldGoalPct", 0),
                        "FG3_PCT": stat_map.get("general.threePointFieldGoalPct", 0),
                        "FT_PCT":  stat_map.get("general.freeThrowPct", 0),
                        "PLUS_MINUS": 0.0, "USG_PCT": 0.0, "PIE": 0.0,
                    })
                except Exception:
                    continue

            page_info = data.get("pageIndex", {})
            if page >= page_info.get("totalPages", page):
                break
            page += 1

        except Exception as e:
            logger.warning(f"ESPN page {page} failed: {e}")
            break

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_nba_json(data: dict):
    try:
        rs = data["resultSets"][0]
        return rs["headers"], rs["rowSet"]
    except (KeyError, IndexError) as e:
        logger.error(f"NBA JSON parse error: {e}")
        return [], []


def _build_player_map(df: pd.DataFrame, window: str) -> Dict[str, "PlayerStats"]:
    """
    Build player map from a stats DataFrame.

    Handles both per-game and season-total responses from the NBA API.
    Detection: if average PTS > 50, the API returned totals — divide by GP.
    (No NBA player averages 50+ PPG; Wilt's record is 50.4 for a full season)
    """
    if df.empty:
        return {}

    # Sample first 10 players to detect if these are totals or per-game
    sample_pts = df["PTS"].dropna().head(20)
    is_totals  = sample_pts.mean() > 50  # clearly totals if avg > 50 across sample
    if is_totals:
        logger.warning(
            f"NBA API returned season TOTALS (avg PTS={sample_pts.mean():.1f}) "
            f"despite PerMode=PerGame — dividing by GP automatically"
        )

    player_map = {}
    for _, row in df.iterrows():
        raw = str(row.get("PLAYER_NAME", "")).strip()
        if not raw:
            continue
        name = normalize_player_name(raw)
        if not name:
            continue

        gp  = max(int(_sf(row.get("GP", 1))), 1)  # avoid div-by-zero
        usg = _sf(row.get("USG_PCT", 0))
        per = _sf(row.get("PIE", 0))

        # Convert totals → per-game if needed
        def pg(col: str) -> float:
            v = _sf(row.get(col, 0))
            return v / gp if is_totals else v

        pts = pg("PTS")
        fga = pg("FGA")
        fta = pg("FTA")

        # True Shooting % — computed from per-game values
        ts = pts / (2 * (fga + 0.44 * fta)) if (fga + fta) > 0 else 0.0

        # Percentages (FG%, 3P%, FT%) are NOT totals — never divide
        fg_pct  = _sf(row.get("FG_PCT",  0))
        fg3_pct = _sf(row.get("FG3_PCT", 0))
        ft_pct  = _sf(row.get("FT_PCT",  0))

        player_map[name] = PlayerStats(
            player_id=int(_sf(row.get("PLAYER_ID", 0))),
            player_name=name,
            team_abbrev=str(row.get("TEAM_ABBREVIATION", "")),
            team_id=int(_sf(row.get("TEAM_ID", 0))),
            games_played=gp,
            minutes_per_game=pg("MIN"),
            points_per_game=pts,
            rebounds_per_game=pg("REB"),
            assists_per_game=pg("AST"),
            steals_per_game=pg("STL"),
            blocks_per_game=pg("BLK"),
            fg_percentage=fg_pct,
            three_pt_percentage=fg3_pct,
            ft_percentage=ft_pct,
            plus_minus=pg("PLUS_MINUS"),
            # USG% and PIE: API returns 0–1 or 0–100 depending on version
            usage_rate=usg if usg > 1.0 else usg * 100,
            player_efficiency_rating=per if per > 1.0 else per * 100,
            true_shooting_pct=ts,
            stats_window=window,
        )

    # Log a sample so you can verify values look right
    sample = list(player_map.values())[:3]
    for ps in sample:
        logger.info(
            f"  {ps.player_name}: {ps.points_per_game:.1f} PPG / "
            f"{ps.rebounds_per_game:.1f} RPG / {ps.assists_per_game:.1f} APG "
            f"in {ps.games_played} GP"
        )

    logger.info(f"Player map: {len(player_map)} players ({window})")
    return player_map


def _share(player_val: float, team_val: float) -> float:
    if team_val and team_val > 0:
        return min(player_val / team_val, 1.0)
    return 0.0


def _enrich_shares_from_player_map(player_map: Dict[str, "PlayerStats"]) -> None:
    from collections import defaultdict
    team_sums: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"pts": 0.0, "reb": 0.0, "ast": 0.0, "blk": 0.0, "stl": 0.0}
    )
    for ps in player_map.values():
        if ps.games_played < 5 or not ps.team_abbrev:
            continue
        t = team_sums[ps.team_abbrev]
        t["pts"] += ps.points_per_game
        t["reb"] += ps.rebounds_per_game
        t["ast"] += ps.assists_per_game
        t["blk"] += ps.blocks_per_game
        t["stl"] += ps.steals_per_game

    enriched = 0
    for ps in player_map.values():
        t = team_sums.get(ps.team_abbrev)
        if not t:
            continue
        ps.points_share   = _share(ps.points_per_game,   t["pts"])
        ps.rebounds_share = _share(ps.rebounds_per_game, t["reb"])
        ps.assists_share  = _share(ps.assists_per_game,  t["ast"])
        ps.blocks_share   = _share(ps.blocks_per_game,   t["blk"])
        ps.steals_share   = _share(ps.steals_per_game,   t["stl"])
        enriched += 1
    logger.info(f"Base shares: {enriched} players across {len(team_sums)} teams")


def _sf(val, default: float = 0.0) -> float:
    try:
        f = float(val)
        return default if (f != f) else f
    except (TypeError, ValueError):
        return default
