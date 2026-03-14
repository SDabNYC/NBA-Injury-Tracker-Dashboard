"""
Risk Scoring Engine — definitive model, no user-adjustable weights.

═══════════════════════════════════════════════════════════════
PLAYER IMPACT MODEL
═══════════════════════════════════════════════════════════════

Based on basketball analytics research (RAPTOR, EPM, win probability
work by FiveThirtyEight / Second Spectrum), the best box-score predictors
of how much a player contributes to winning are:

  OFFENSIVE CONTRIBUTION (65% of model)
  ├─ Scoring creation  (55% of offense)
  │   pts_share × 0.55  +  ast_share × 0.45
  │   Rationale: losing a scorer hurts, but losing a creator who
  │   generates shots for others hurts almost as much.
  └─ Usage efficiency  (45% of offense)
      usage_normalized × ts_efficiency_normalized
      Rationale: high-usage players occupy defensive attention
      even when they don't score — their absence disrupts the
      entire offensive structure. Weighting by efficiency avoids
      rewarding high-volume bad shooters.

  DEFENSIVE CONTRIBUTION (20% of model)
  ├─ Rim protection:  blocks_share × 0.40
  ├─ Ball disruption: steals_share × 0.40
  └─ Rebounding:      reb_share   × 0.20
     Rationale: blocks + steals directly prevent scoring;
     rebounding matters but is more replaceable.

  OVERALL EFFICIENCY (15% of model)
      PIE_normalized
      Player Impact Estimate from NBA Stats — composite efficiency.
      Acts as a tiebreaker / bonus for elite two-way players.

Final formula:
  offensive  = (pts_share*0.55 + ast_share*0.45)*0.55 + (usage*ts)*0.45
  defensive  = blk_share*0.40 + stl_share*0.40 + reb_share*0.20
  efficiency = PIE_normalized
  raw_impact = offensive*0.65 + defensive*0.20 + efficiency*0.15

═══════════════════════════════════════════════════════════════
TEAM RISK DISTRIBUTION
═══════════════════════════════════════════════════════════════

Problem with fixed thresholds (e.g. score > 80 = Critical):
If today's worst injury situation only produces a raw score of 35,
everyone lands in Low/Medium — the rating is useless.

Solution: hybrid normalization
  1. Compute raw scores for all teams playing today
  2. Normalize relative to today's range (so there's always spread)
  3. Apply a soft absolute floor — teams with truly trivial injuries
     cannot be labeled High/Critical even if they're "worst today"

Tier assignment uses percentile-based cutoffs within today's games:
  Critical : top 15% AND absolute score ≥ 25
  High     : top 40% AND absolute score ≥ 12
  Medium   : top 70%
  Low      : rest
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import numpy as np

from data.injuries import InjuredPlayer
from data.player_stats import PlayerStats


# ── Absolute minimum thresholds to qualify for each tier ─────────────────────
# These prevent labeling "role player with a sore toe" as Critical
# even if every other team has zero injuries today.
ABSOLUTE_FLOOR = {
    "Critical": 25.0,   # must lose ≥ 25% of team's weighted scoring creation
    "High":     12.0,   # ≥ 12%
    "Medium":    4.0,   # ≥ 4%
}

# Percentile cutoffs within today's playing teams (0–100)
PERCENTILE_CUTOFFS = {
    "Critical": 85,   # top 15%
    "High":     60,   # top 40%
    "Medium":   30,   # top 70%
}

TIER_META = {
    "Critical": ("#FF2D2D", "🔴"),
    "High":     ("#FF8C00", "🟠"),
    "Medium":   ("#FFD700", "🟡"),
    "Low":      ("#32CD32", "🟢"),
}


@dataclass
class PlayerImpact:
    player_name: str
    team_abbrev: str
    status: str
    injury_type: str
    injury_detail: str             # Full reason from PDF e.g. "G League - Two-Way"
    availability_weight: float
    raw_impact_score: float        # 0–1, before availability weight
    weighted_impact_score: float   # raw × availability weight
    # Component breakdown for radar chart
    offensive_component: float = 0.0
    defensive_component: float = 0.0
    efficiency_component: float = 0.0
    # Display stats
    ppg:   float = 0.0
    rpg:   float = 0.0
    apg:   float = 0.0
    bpg:   float = 0.0
    spg:   float = 0.0
    usage_pct:       float = 0.0
    points_share_pct: float = 0.0
    ts_pct:          float = 0.0
    games_played:    int   = 0
    found_in_stats:  bool  = True


@dataclass
class TeamRiskReport:
    team_abbrev:     str
    team_name:       str
    raw_impact_sum:  float   # unnormalized, sum of player impacts
    final_risk_score: float  # 0–100 after relative normalization
    risk_tier:       str
    risk_color:      str
    risk_emoji:      str
    player_impacts:  List[PlayerImpact] = field(default_factory=list)
    total_injured:   int   = 0
    out_count:       int   = 0
    questionable_count: int = 0
    # Radar chart dimensions (0–100 each)
    scoring_impact:    float = 0.0
    playmaking_impact: float = 0.0
    rebounding_impact: float = 0.0
    defense_impact:    float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Core: single player impact
# ─────────────────────────────────────────────────────────────────────────────

def compute_player_impact(
    injured: InjuredPlayer,
    stats: Optional[PlayerStats],
    stats_display: Optional[PlayerStats] = None,
) -> PlayerImpact:
    """
    Compute impact of losing this player.
    stats         — filtered (min_games) — used for the risk SCORE
    stats_display — unfiltered           — used for the display CHIPS on the card
    Falls back to stats_display for scoring when stats is None but display exists.
    """
    display = stats_display if stats_display is not None else stats

    def _compute_components(s):
        """Compute offensive/defensive/efficiency from a PlayerStats object."""
        scoring_creation = s.points_share * 0.55 + s.assists_share * 0.45
        usage_norm = float(np.clip((s.usage_rate - 5.0) / 35.0, 0.0, 1.0))
        ts = s.true_shooting_pct or s.fg_percentage or 0.50
        ts_norm = float(np.clip((ts - 0.40) / 0.30, 0.0, 1.0))
        offensive  = scoring_creation * 0.55 + (usage_norm * ts_norm) * 0.45
        defensive  = s.blocks_share * 0.40 + s.steals_share * 0.40 + s.rebounds_share * 0.20
        pie_norm   = float(np.clip(s.player_efficiency_rating / 20.0, 0.0, 1.0))
        raw        = float(np.clip(offensive * 0.65 + defensive * 0.20 + pie_norm * 0.15, 0.0, 1.0))
        ts_display = ts
        return offensive, defensive, pie_norm, raw, ts_display

    if stats is None and display is None:
        # Truly no data — assign a very small default so unmatched bench/G-League
        # players never outscore a matched star who happens to be Questionable.
        # 0.02 × 1.0 (Out) = 0.02, which is well below any matched player's score.
        return PlayerImpact(
            player_name=injured.name, team_abbrev=injured.team_abbrev,
            status=injured.status, injury_type=injured.injury_type,
            injury_detail=injured.injury_detail,
            availability_weight=injured.availability_weight,
            raw_impact_score=0.02,
            weighted_impact_score=0.02 * injured.availability_weight,
            found_in_stats=False,
        )

    # Use filtered stats for the score, display stats for the chips
    score_source   = stats if stats is not None else display
    display_source = display  # always unfiltered if available

    offensive, defensive, pie_norm, raw, ts_val = _compute_components(score_source)
    weighted = raw * injured.availability_weight

    # Display chips always use the unfiltered source
    ds = display_source
    ts_display = ds.true_shooting_pct or ds.fg_percentage or 0.50

    return PlayerImpact(
        player_name=injured.name,
        team_abbrev=injured.team_abbrev,
        status=injured.status,
        injury_type=injured.injury_type,
        injury_detail=injured.injury_detail,
        availability_weight=injured.availability_weight,
        raw_impact_score=raw,
        weighted_impact_score=weighted,
        offensive_component=offensive,
        defensive_component=defensive,
        efficiency_component=pie_norm,
        ppg=ds.points_per_game,
        rpg=ds.rebounds_per_game,
        apg=ds.assists_per_game,
        bpg=ds.blocks_per_game,
        spg=ds.steals_per_game,
        usage_pct=ds.usage_rate,
        points_share_pct=ds.points_share * 100,
        ts_pct=ts_display * 100,
        games_played=ds.games_played,
        found_in_stats=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core: per-team raw impact sum
# ─────────────────────────────────────────────────────────────────────────────

def compute_team_raw_impact(
    team_abbrev: str,
    team_name: str,
    injured_players: List[InjuredPlayer],
    player_stats_map: Dict[str, PlayerStats],
    player_stats_full: Dict[str, PlayerStats] = None,
) -> Tuple["TeamRiskReport", float]:
    """
    First pass: compute raw impact sum for one team.
    player_stats_map  — filtered (min_games) — used for SCORING
    player_stats_full — unfiltered           — used for DISPLAY stats on cards
    """
    from data.player_stats import lookup_player

    # Fall back to scoring map if full map not provided
    display_map = player_stats_full if player_stats_full is not None else player_stats_map

    impacts = []
    for injured in injured_players:
        # Use filtered map for the impact score calculation
        stats_for_score   = lookup_player(injured.name, player_stats_map)
        # Use full map for the display stats shown on the card
        stats_for_display = lookup_player(injured.name, display_map)
        impact = compute_player_impact(injured, stats_for_score, stats_for_display)
        impacts.append(impact)

    impacts.sort(key=lambda x: x.weighted_impact_score, reverse=True)
    raw_sum = _diminishing_sum([i.weighted_impact_score for i in impacts])

    scoring_imp    = sum(i.offensive_component * i.availability_weight for i in impacts if i.found_in_stats)
    playmaking_imp = sum(i.weighted_impact_score * (i.apg / max(i.ppg + i.apg, 1)) for i in impacts if i.found_in_stats)
    rebounding_imp = sum(i.weighted_impact_score * i.defensive_component for i in impacts if i.found_in_stats)
    defense_imp    = sum(i.defensive_component * i.availability_weight for i in impacts if i.found_in_stats)

    report = TeamRiskReport(
        team_abbrev=team_abbrev,
        team_name=team_name,
        raw_impact_sum=raw_sum,
        final_risk_score=0.0,
        risk_tier="Low",
        risk_color=TIER_META["Low"][0],
        risk_emoji=TIER_META["Low"][1],
        player_impacts=impacts,
        total_injured=len(impacts),
        out_count=sum(1 for p in injured_players if p.status in ("Out", "Injured Reserve")),
        questionable_count=sum(1 for p in injured_players if p.status in ("Questionable", "Doubtful", "Game Time Decision")),
        scoring_impact=min(scoring_imp * 100, 100),
        playmaking_impact=min(playmaking_imp * 100, 100),
        rebounding_impact=min(rebounding_imp * 100, 100),
        defense_impact=min(defense_imp * 100, 100),
    )
    return report, raw_sum


# ─────────────────────────────────────────────────────────────────────────────
# Full assessment with relative normalization
# ─────────────────────────────────────────────────────────────────────────────

def run_full_risk_assessment(
    teams_playing,
    injuries_by_team: Dict[str, List[InjuredPlayer]],
    player_stats_map: Dict[str, PlayerStats],
    team_name_map: Dict[str, str],
    player_stats_full: Dict[str, PlayerStats] = None,
) -> List["TeamRiskReport"]:
    """
    Two-pass assessment:
      Pass 1 — compute raw impact sums for all teams
      Pass 2 — normalize relative to today's range, assign tiers
    """

    # ── Pass 1: raw scores ────────────────────────────────────────────────
    reports = []
    raw_sums = []

    for abbrev in teams_playing:
        injured   = injuries_by_team.get(abbrev, [])
        full_name = team_name_map.get(abbrev, abbrev)
        report, raw = compute_team_raw_impact(
            abbrev, full_name, injured, player_stats_map, player_stats_full
        )
        reports.append(report)
        raw_sums.append(raw)

    # ── Pass 2: relative normalization ───────────────────────────────────
    _normalize_and_assign_tiers(reports, raw_sums)

    return sorted(reports, key=lambda r: r.final_risk_score, reverse=True)


def _normalize_and_assign_tiers(
    reports: List[TeamRiskReport],
    raw_sums: List[float],
) -> None:
    """
    Normalize raw_sums to 0–100 relative to today's range,
    then assign tiers using percentile cutoffs + absolute floors.
    Mutates reports in-place.
    """
    if not raw_sums:
        return

    arr = np.array(raw_sums, dtype=float)

    # If everything is 0 (no injuries at all today), everyone is Low
    if arr.max() == 0:
        for r in reports:
            r.final_risk_score = 0.0
            r.risk_tier  = "Low"
            r.risk_color = TIER_META["Low"][0]
            r.risk_emoji = TIER_META["Low"][1]
        return

    # Relative normalization: scale so the highest raw score = 100
    # This guarantees meaningful spread across today's teams
    normalized = (arr / arr.max()) * 100.0

    # Also compute the absolute score for the floor check
    # raw_sum is in [0, ~1.5]; scale to 0–100 using a fixed reference
    # where 1.0 raw = "lost your entire starting lineup" = 100% risk
    ABSOLUTE_REFERENCE = 1.0   # a team losing impact ≥ 1.0 is a true 100
    absolute = np.clip(arr / ABSOLUTE_REFERENCE * 100.0, 0.0, 100.0)

    # Hybrid: blend relative (70%) and absolute (30%)
    # This prevents a team from being called "Critical" just because
    # everyone else is healthy, but still shows clear separation
    final_scores = normalized * 0.70 + absolute * 0.30

    # Compute percentile ranks within today's group
    ranks = arr.argsort().argsort()   # rank 0 = lowest
    n     = len(arr)
    percentiles = (ranks / max(n - 1, 1)) * 100.0

    for i, (report, score, pct, abs_score) in enumerate(
        zip(reports, final_scores, percentiles, absolute)
    ):
        report.final_risk_score = float(round(score, 1))

        # Assign tier using percentile position + absolute floor
        if pct >= PERCENTILE_CUTOFFS["Critical"] and abs_score >= ABSOLUTE_FLOOR["Critical"]:
            tier = "Critical"
        elif pct >= PERCENTILE_CUTOFFS["High"] and abs_score >= ABSOLUTE_FLOOR["High"]:
            tier = "High"
        elif pct >= PERCENTILE_CUTOFFS["Medium"] and abs_score >= ABSOLUTE_FLOOR["Medium"]:
            tier = "Medium"
        else:
            tier = "Low"

        color, emoji = TIER_META[tier]
        report.risk_tier  = tier
        report.risk_color = color
        report.risk_emoji = emoji


def _diminishing_sum(scores: List[float]) -> float:
    """
    Sum with diminishing returns: each additional injured player
    contributes less than the previous one.
    Factor 0.80 per rank: 1st = 1.0×, 2nd = 0.80×, 3rd = 0.64×, ...
    """
    if not scores:
        return 0.0
    total = 0.0
    for i, s in enumerate(sorted(scores, reverse=True)):
        total += s * (0.80 ** i)
    return total
