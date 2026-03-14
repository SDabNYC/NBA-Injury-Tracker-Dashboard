"""
Streamlit UI components for the NBA Injury Risk Dashboard.
Team cards, matchup displays, and styled containers.
"""

import streamlit as st
from typing import Optional
from scoring.risk_engine import TeamRiskReport


def inject_custom_css():
    """Inject custom CSS for the dashboard styling."""
    st.markdown("""
    <style>
        /* ── Global ─────────────────────────────────── */
        .stApp {
            background-color: #0E1117;
        }

        /* ── Risk Cards ─────────────────────────────── */
        .risk-card {
            background: #1E2130;
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 8px;
            border-left: 5px solid #888;
            transition: transform 0.2s;
        }
        .risk-card:hover {
            transform: translateX(3px);
        }
        .risk-card-critical { border-left-color: #FF2D2D !important; }
        .risk-card-high     { border-left-color: #FF8C00 !important; }
        .risk-card-medium   { border-left-color: #FFD700 !important; }
        .risk-card-low      { border-left-color: #32CD32 !important; }

        .team-abbrev {
            font-size: 1.6rem;
            font-weight: 800;
            color: #FAFAFA;
            letter-spacing: 1px;
        }
        .risk-score {
            font-size: 2rem;
            font-weight: 900;
            line-height: 1;
        }
        .risk-label {
            font-size: 0.8rem;
            font-weight: 600;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            opacity: 0.85;
        }
        .injury-count {
            font-size: 0.75rem;
            color: #9AA0B3;
            margin-top: 4px;
        }

        /* ── Matchup Header ─────────────────────────── */
        .matchup-header {
            background: #1E2130;
            border-radius: 12px;
            padding: 14px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
        }
        .vs-text {
            color: #9AA0B3;
            font-size: 0.9rem;
            font-weight: 600;
        }
        .game-time {
            color: #9AA0B3;
            font-size: 0.8rem;
        }

        /* ── Section headers ────────────────────────── */
        .section-title {
            font-size: 1.1rem;
            font-weight: 700;
            color: #E8B84B;
            letter-spacing: 0.5px;
            padding-bottom: 6px;
            border-bottom: 1px solid #2A2D3E;
            margin-bottom: 14px;
        }

        /* ── Player status badges ───────────────────── */
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }
        .badge-out        { background: #3D1A1A; color: #FF6B6B; }
        .badge-doubtful   { background: #3D2A10; color: #FF8C00; }
        .badge-questionable { background: #3D3510; color: #FFD700; }
        .badge-dtd        { background: #1A2D1A; color: #90EE90; }
        .badge-gtd        { background: #2D2A10; color: #FFEAA0; }

        /* ── Stat chips ─────────────────────────────── */
        .stat-chip {
            display: inline-block;
            background: #2A2D3E;
            border-radius: 6px;
            padding: 3px 8px;
            font-size: 0.75rem;
            color: #FAFAFA;
            margin: 2px;
        }
        .stat-chip span {
            color: #E8B84B;
            font-weight: 700;
        }

        /* ── Metric override ────────────────────────── */
        [data-testid="metric-container"] {
            background: #1E2130;
            border-radius: 10px;
            padding: 12px 16px;
        }

        /* ── Scrollable player list ─────────────────── */
        .player-list {
            max-height: 360px;
            overflow-y: auto;
            padding-right: 4px;
        }

        /* ── Divider ────────────────────────────────── */
        .custom-divider {
            border: none;
            border-top: 1px solid #2A2D3E;
            margin: 20px 0;
        }
    </style>
    """, unsafe_allow_html=True)


def render_risk_card(report: TeamRiskReport):
    """Render a compact risk card for a team (used in the overview grid)."""
    tier_class = f"risk-card-{report.risk_tier.lower()}"
    injured_text = f"{report.total_injured} injured"
    if report.out_count > 0:
        injured_text += f" · {report.out_count} out"
    if report.questionable_count > 0:
        injured_text += f" · {report.questionable_count} questionable"

    top_player = ""
    if report.player_impacts:
        top = report.player_impacts[0]
        top_player = f"<div style='font-size:0.72rem;color:#9AA0B3;margin-top:6px;'>Top concern: <b style='color:#FAFAFA'>{top.player_name}</b> ({top.status})</div>"

    st.markdown(f"""
    <div class="risk-card {tier_class}">
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
                <div class="team-abbrev">{report.team_abbrev}</div>
                <div style="font-size:0.8rem;color:#9AA0B3;margin-top:2px;">{report.team_name}</div>
            </div>
            <div style="text-align:right;">
                <div class="risk-score" style="color:{report.risk_color}">{report.final_risk_score:.0f}</div>
                <div class="risk-label" style="color:{report.risk_color}">{report.risk_emoji} {report.risk_tier}</div>
            </div>
        </div>
        <div class="injury-count">{injured_text}</div>
        {top_player}
    </div>
    """, unsafe_allow_html=True)


def render_matchup_card(
    away_abbrev: str, away_name: str, away_report: Optional[TeamRiskReport],
    home_abbrev: str, home_name: str, home_report: Optional[TeamRiskReport],
    game_time: str, status: str,
):
    """Render a full matchup row with both teams' risk indicators."""
    def _mini_risk(report, abbrev):
        if report:
            return (
                f"<div style='text-align:center;'>"
                f"<div style='font-size:1.3rem;font-weight:800;color:#FAFAFA;'>{abbrev}</div>"
                f"<div style='font-size:1.5rem;font-weight:900;color:{report.risk_color};'>{report.final_risk_score:.0f}</div>"
                f"<div style='font-size:0.7rem;color:{report.risk_color};text-transform:uppercase;letter-spacing:1px;'>{report.risk_emoji} {report.risk_tier}</div>"
                f"</div>"
            )
        return f"<div style='text-align:center;color:#555;'>{abbrev}<br>No data</div>"

    away_html = _mini_risk(away_report, away_abbrev)
    home_html = _mini_risk(home_report, home_abbrev)

    status_color = "#32CD32" if status == "In Progress" else "#9AA0B3"
    status_text = f"🔴 LIVE" if status == "In Progress" else (f"✅ Final" if status == "Final" else game_time)

    st.markdown(f"""
    <div class="matchup-header">
        {away_html}
        <div style="text-align:center;">
            <div class="vs-text">VS</div>
            <div class="game-time" style="color:{status_color};">{status_text}</div>
        </div>
        {home_html}
    </div>
    """, unsafe_allow_html=True)


def render_player_injury_row(impact):
    """Render a single injured player row with stats and badge."""
    status_colors = {
        "Out":                ("#FF6B6B", "#3D1A1A"),
        "Injured Reserve":    ("#FF6B6B", "#3D1A1A"),
        "Doubtful":           ("#FF8C00", "#3D2A10"),
        "Questionable":       ("#FFD700", "#3D3510"),
        "Day-To-Day":         ("#90EE90", "#1A2D1A"),
        "Day-to-Day":         ("#90EE90", "#1A2D1A"),
        "Game Time Decision": ("#FFEAA0", "#2D2A10"),
    }
    text_color, bg_color = status_colors.get(impact.status, ("#FF6B6B", "#3D1A1A"))

    # Show the full injury detail if available, otherwise the injury type
    # Never show bare "Unknown" — show the reason text from the PDF instead
    if impact.injury_detail and impact.injury_detail.strip():
        injury_label = impact.injury_detail[:60]  # truncate long reasons
    elif impact.injury_type and impact.injury_type != "Unknown":
        injury_label = impact.injury_type
    else:
        injury_label = "—"

    # ── Header row ────────────────────────────────────────────────────────
    st.markdown(
        f"""<div style="background:#252838;border-radius:8px;padding:12px 14px 8px 14px;margin-bottom:2px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
                <span style="font-weight:700;color:#FAFAFA;font-size:0.95rem;">{impact.player_name}</span>
                &nbsp;&nbsp;
                <span style="display:inline-block;padding:2px 8px;border-radius:4px;
                             font-size:0.7rem;font-weight:700;letter-spacing:0.5px;
                             background:{bg_color};color:{text_color};">
                    {impact.status.upper()}
                </span>
            </div>
            <div style="font-size:0.78rem;color:#9AA0B3;">{injury_label}</div>
        </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Stats chips ───────────────────────────────────────────────────────
    if impact.found_in_stats:
        chip_style = (
            "background:#2A2D3E;border-radius:6px;padding:4px 10px;"
            "text-align:center;font-size:0.72rem;color:#FAFAFA;"
        )
        label_style = "color:#9AA0B3;display:block;font-size:0.65rem;margin-bottom:1px;"
        value_style = "color:#E8B84B;font-weight:700;font-size:0.82rem;"

        chips = [
            ("PPG",    f"{impact.ppg:.1f}"),
            ("RPG",    f"{impact.rpg:.1f}"),
            ("APG",    f"{impact.apg:.1f}"),
            ("USG%",   f"{impact.usage_pct:.1f}%"),
            ("TS%",    f"{impact.ts_pct:.1f}%"),
            ("Pts%",   f"{impact.points_share_pct:.1f}%"),
            ("Impact", f"{impact.weighted_impact_score * 100:.1f}"),
        ]

        cols = st.columns(len(chips))
        for col, (label, value) in zip(cols, chips):
            col.markdown(
                f'<div style="{chip_style}">'
                f'<span style="{label_style}">{label}</span>'
                f'<span style="{value_style}">{value}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        # No stats — player hasn't played enough games to have meaningful data
        # (could be long-term injured, new arrival, or G League player)
        st.markdown(
            '<div style="background:#252838;padding:4px 14px 8px 14px;">'
            '<span style="font-size:0.72rem;color:#555;">'
            'Insufficient games played this season — no stats on record'
            '</span></div>',
            unsafe_allow_html=True,
        )

    # ── Close card ────────────────────────────────────────────────────────
    st.markdown(
        '<div style="background:#252838;border-radius:0 0 8px 8px;'
        'height:6px;margin-bottom:10px;"></div>',
        unsafe_allow_html=True,
    )


def render_section_title(title: str, icon: str = ""):
    """Render a styled section title."""
    st.markdown(f'<div class="section-title">{icon} {title}</div>', unsafe_allow_html=True)


def render_divider():
    st.markdown('<hr class="custom-divider">', unsafe_allow_html=True)
