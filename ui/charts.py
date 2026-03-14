"""
Plotly chart builders for the NBA Injury Risk Dashboard.
All functions return Plotly Figure objects ready for st.plotly_chart().
"""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

from scoring.risk_engine import TeamRiskReport, PlayerImpact

# ── Color palette ─────────────────────────────────────────────────────────────
DARK_BG = "#0E1117"
CARD_BG = "#1E2130"
ACCENT = "#E8B84B"       # Gold
TEXT_PRIMARY = "#FAFAFA"
TEXT_SECONDARY = "#9AA0B3"
GRID_COLOR = "#2A2D3E"

RISK_COLORS = {
    "Critical": "#FF2D2D",
    "High":     "#FF8C00",
    "Medium":   "#FFD700",
    "Low":      "#32CD32",
}


def risk_bar_chart(reports: list[TeamRiskReport]) -> go.Figure:
    """
    Horizontal bar chart showing all teams' risk scores for today's games.
    """
    if not reports:
        return _empty_figure("No data available")

    teams = [r.team_abbrev for r in reports]
    scores = [r.final_risk_score for r in reports]
    colors = [r.risk_color for r in reports]
    tiers = [r.risk_tier for r in reports]
    hovers = [
        f"<b>{r.team_name}</b><br>"
        f"Risk Score: <b>{r.final_risk_score:.1f}/100</b><br>"
        f"Tier: <b>{r.risk_tier}</b><br>"
        f"Players Out: {r.out_count} | Questionable: {r.questionable_count}"
        for r in reports
    ]

    fig = go.Figure(go.Bar(
        x=scores,
        y=teams,
        orientation="h",
        marker=dict(
            color=colors,
            line=dict(width=0),
        ),
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hovers,
        text=[f"{s:.0f}" for s in scores],
        textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=12),
    ))

    fig.update_layout(
        title=dict(
            text="Team Injury Risk Scores — Today's Games",
            font=dict(color=TEXT_PRIMARY, size=16),
            x=0.0,
        ),
        xaxis=dict(
            range=[0, 110],
            showgrid=True,
            gridcolor=GRID_COLOR,
            tickfont=dict(color=TEXT_SECONDARY),
            title=dict(text="Risk Score (0–100)", font=dict(color=TEXT_SECONDARY)),
        ),
        yaxis=dict(
            tickfont=dict(color=TEXT_PRIMARY, size=13),
            categoryorder="total ascending",
        ),
        plot_bgcolor=CARD_BG,
        paper_bgcolor=DARK_BG,
        margin=dict(l=20, r=40, t=50, b=20),
        height=max(300, len(teams) * 48),
        showlegend=False,
    )

    # Add risk zone lines
    for threshold, label, color, _ in [(80, "Critical", "#FF2D2D", ""), (55, "High", "#FF8C00", ""), (30, "Medium", "#FFD700", "")]:
        fig.add_vline(
            x=threshold, line_dash="dash", line_color=color,
            opacity=0.4,
            annotation_text=label,
            annotation_font_color=color,
            annotation_position="top",
        )

    return fig


def player_impact_waterfall(impacts: list[PlayerImpact], team_name: str) -> go.Figure:
    """
    Waterfall-style horizontal bar showing each injured player's impact contribution.
    """
    if not impacts:
        return _empty_figure("No injured players for this team")

    names = [p.player_name for p in impacts]
    scores = [p.weighted_impact_score * 100 for p in impacts]
    statuses = [p.status for p in impacts]
    colors = [RISK_COLORS.get("Out" if p.availability_weight >= 0.9 else
                              "High" if p.availability_weight >= 0.6 else
                              "Medium" if p.availability_weight >= 0.3 else "Low", "#888")
              for p in impacts]

    hover_texts = [
        f"<b>{p.player_name}</b><br>"
        f"Status: {p.status}<br>"
        f"Injury: {p.injury_type}<br>"
        f"Impact Score: {p.weighted_impact_score * 100:.1f}<br>"
        f"PPG: {p.ppg:.1f} | RPG: {p.rpg:.1f} | APG: {p.apg:.1f}<br>"
        f"Usage: {p.usage_pct:.1f}% | Pts Share: {p.points_share_pct:.1f}%"
        for p in impacts
    ]

    fig = go.Figure(go.Bar(
        x=scores,
        y=names,
        orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover_texts,
        text=[f"{s:.1f}" for s in scores],
        textposition="outside",
        textfont=dict(color=TEXT_PRIMARY, size=11),
    ))

    fig.update_layout(
        title=dict(
            text=f"Player Impact Scores — {team_name}",
            font=dict(color=TEXT_PRIMARY, size=14),
        ),
        xaxis=dict(
            title=dict(text="Weighted Impact (0–100)", font=dict(color=TEXT_SECONDARY)),
            showgrid=True,
            gridcolor=GRID_COLOR,
            tickfont=dict(color=TEXT_SECONDARY),
            range=[0, max(scores) * 1.3 + 5 if scores else 20],
        ),
        yaxis=dict(
            tickfont=dict(color=TEXT_PRIMARY, size=12),
            categoryorder="total ascending",
        ),
        plot_bgcolor=CARD_BG,
        paper_bgcolor=DARK_BG,
        margin=dict(l=20, r=50, t=50, b=20),
        height=max(250, len(names) * 45 + 80),
        showlegend=False,
    )

    return fig


def radar_chart(report: TeamRiskReport) -> go.Figure:
    """
    Radar chart showing which dimensions of the team are most impacted by injuries.
    """
    categories = ["Scoring", "Playmaking", "Rebounding", "Defense", "Depth"]
    depth_score = min(report.total_injured * 8, 100)  # proxy for squad depth impact

    values = [
        report.scoring_impact,
        report.playmaking_impact,
        report.rebounding_impact,
        report.defense_impact,
        depth_score,
    ]

    # Close the radar loop
    categories_closed = categories + [categories[0]]
    values_closed = values + [values[0]]

    fig = go.Figure()

    # Fill area
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=categories_closed,
        fill="toself",
        fillcolor=f"rgba({_hex_to_rgb(report.risk_color)}, 0.2)",
        line=dict(color=report.risk_color, width=2),
        name="Impact",
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickfont=dict(color=TEXT_SECONDARY, size=9),
                gridcolor=GRID_COLOR,
                linecolor=GRID_COLOR,
            ),
            angularaxis=dict(
                tickfont=dict(color=TEXT_PRIMARY, size=12),
                gridcolor=GRID_COLOR,
                linecolor=GRID_COLOR,
            ),
            bgcolor=CARD_BG,
        ),
        paper_bgcolor=DARK_BG,
        showlegend=False,
        margin=dict(l=30, r=30, t=30, b=30),
        height=300,
        title=dict(
            text=f"Impact Dimensions — {report.team_abbrev}",
            font=dict(color=TEXT_PRIMARY, size=13),
            x=0.5,
        ),
    )

    return fig


def stats_comparison_table(impacts: list[PlayerImpact]) -> pd.DataFrame:
    """Build a DataFrame suitable for st.dataframe() display."""
    if not impacts:
        return pd.DataFrame()

    rows = []
    for p in impacts:
        rows.append({
            "Player": p.player_name,
            "Status": p.status,
            "Injury": p.injury_type,
            "Impact Score": f"{p.weighted_impact_score * 100:.1f}",
            "PPG": f"{p.ppg:.1f}",
            "RPG": f"{p.rpg:.1f}",
            "APG": f"{p.apg:.1f}",
            "BPG": f"{p.bpg:.1f}",
            "SPG": f"{p.spg:.1f}",
            "Usage%": f"{p.usage_pct:.1f}%",
            "Pts Share": f"{p.points_share_pct:.1f}%",
            "GP": p.games_played,
        })

    return pd.DataFrame(rows)


def matchup_risk_comparison(
    home_report: TeamRiskReport,
    away_report: TeamRiskReport,
) -> go.Figure:
    """
    Side-by-side gauge comparison for a single matchup.
    Shows both teams' risk scores visually.
    """
    fig = go.Figure()

    for i, (report, side) in enumerate([(away_report, "Away"), (home_report, "Home")]):
        fig.add_trace(go.Indicator(
            mode="gauge+number",
            value=report.final_risk_score,
            domain={"x": [i * 0.5, i * 0.5 + 0.45], "y": [0.1, 0.9]},
            title={"text": f"{report.team_abbrev}<br><span style='font-size:0.8em;color:gray'>{side}</span>",
                   "font": {"color": TEXT_PRIMARY, "size": 14}},
            number={"font": {"color": report.risk_color, "size": 28}},
            gauge=dict(
                axis=dict(range=[0, 100], tickcolor=TEXT_SECONDARY),
                bar=dict(color=report.risk_color),
                bgcolor=CARD_BG,
                bordercolor=GRID_COLOR,
                steps=[
                    {"range": [0, 30], "color": "#1a2f1a"},
                    {"range": [30, 55], "color": "#2f2a10"},
                    {"range": [55, 80], "color": "#2f1a0a"},
                    {"range": [80, 100], "color": "#2f0a0a"},
                ],
                threshold=dict(
                    line=dict(color=report.risk_color, width=3),
                    thickness=0.8,
                    value=report.final_risk_score,
                ),
            ),
        ))

    fig.update_layout(
        paper_bgcolor=DARK_BG,
        font={"color": TEXT_PRIMARY},
        margin=dict(l=20, r=20, t=10, b=20),
        height=220,
    )

    return fig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(color=TEXT_SECONDARY, size=14),
    )
    fig.update_layout(
        paper_bgcolor=DARK_BG,
        plot_bgcolor=CARD_BG,
        margin=dict(l=20, r=20, t=20, b=20),
        height=200,
    )
    return fig


def _hex_to_rgb(hex_color: str) -> str:
    """Convert #RRGGBB to 'R, G, B' string for rgba()."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r}, {g}, {b}"
