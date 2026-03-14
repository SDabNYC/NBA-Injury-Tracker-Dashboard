"""
NBA Injury Risk Dashboard
─────────────────────────
Streamlit app that assesses which teams playing today
are most at risk due to player injuries, based on
statistical impact analysis.

Run with:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import logging
from datetime import datetime

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="NBA Injury Risk Dashboard",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Local imports (after page config) ────────────────────────────────────────
from data.cache_manager import load_all_data
from data.injuries import group_by_team, filter_injuries_for_teams
from scoring.risk_engine import run_full_risk_assessment, TeamRiskReport
from ui.components import (
    inject_custom_css,
    render_risk_card,
    render_matchup_card,
    render_player_injury_row,
    render_section_title,
    render_divider,
)
from ui.charts import (
    risk_bar_chart,
    player_impact_waterfall,
    radar_chart,
    stats_comparison_table,
    matchup_risk_comparison,
)
from utils.name_normalizer import abbrev_to_full_name, TEAM_ABBREV_TO_FULL


# ── CSS ───────────────────────────────────────────────────────────────────────
inject_custom_css()


# ════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🏀 NBA Risk Dashboard")
    st.markdown("---")

    # Refresh button
    refresh_clicked = st.button("🔄 Refresh All Data", width="stretch")

    st.markdown("---")
    st.markdown("### ⚙️ Risk Model Settings")

    # Stats window — how many recent games to use
    st.markdown("**📅 Stats Window**")
    stats_window_option = st.radio(
        "Base stats on:",
        options=["Last 7 games", "Last 15 games", "Full season"],
        index=1,
        help="Last 15 games reflects current form. Full season is more stable but includes old numbers.",
        horizontal=True,
    )
    last_n_games_map = {"Last 7 games": 7, "Last 15 games": 15, "Full season": 0}
    selected_last_n = last_n_games_map[stats_window_option]

    if stats_window_option == "Full season":
        st.caption("⚠️ Full season includes early-season games — may not reflect current form")
    elif stats_window_option == "Last 7 games":
        st.caption("⚡ Very reactive — scores may swing a lot for hot/cold streaks")
    else:
        st.caption("✅ Recommended — good balance of recency and stability")

    st.markdown("---")

    # Minimum games filter
    min_games = st.slider(
        "Min games played (filter players)",
        min_value=1, max_value=30, value=5,
        help="Exclude players who've barely played — their stats aren't meaningful yet",
    )

    st.markdown("---")
    st.markdown("### 📊 Impact Model")
    st.markdown("""
    <div style='font-size:0.78rem;color:#9AA0B3;line-height:1.8;'>
    <b style='color:#E8B84B;'>Offense</b> &nbsp;65%<br>
    &nbsp;· Scoring + playmaking share<br>
    &nbsp;· Usage × true shooting<br>
    <b style='color:#E8B84B;'>Defense</b> &nbsp;20%<br>
    &nbsp;· Blocks, steals, rebounds<br>
    <b style='color:#E8B84B;'>Efficiency</b> &nbsp;15%<br>
    &nbsp;· Player Impact Estimate (PIE)<br>
    <br>
    Risk tiers are relative to today's<br>
    teams + an absolute impact floor.
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🔍 Filter")
    show_only_today = st.checkbox("Only show teams playing today", value=True)
    hide_low_risk   = st.checkbox("Hide Low risk teams", value=False)
    min_risk_score  = st.slider("Min risk score to show", 0, 100, 0)

    st.markdown("---")
    st.caption("Data sources: ESPN · NBA Stats API")
    st.caption("Refresh rate: Stats 1h · Injuries 10min · Schedule 5min")


# ════════════════════════════════════════════════════════════════════
# LOAD DATA
# ════════════════════════════════════════════════════════════════════
data = load_all_data(force_refresh=refresh_clicked, last_n_games=selected_last_n)

games        = data["games"]
teams_today  = data["teams_playing"]
all_injuries = data["all_injuries"]
team_totals  = data["team_totals"]
errors       = data["errors"]

# Keep a full unfiltered copy for injury card display — ensures
# players like Embiid (few games played due to injury) still show stats
player_stats_full = data["player_stats"]

# Apply min_games filter only for the RISK SCORING model
# (very low game counts make averages unreliable for scoring purposes)
# But we still want to DISPLAY stats for all injured players regardless
player_stats = {
    name: ps for name, ps in player_stats_full.items()
    if ps.games_played >= min_games
} if min_games > 1 else player_stats_full

# Filter injuries to teams playing today (or all teams)
teams_to_assess = teams_today if show_only_today else set(
    p.team_abbrev for p in all_injuries
)

injuries_filtered = filter_injuries_for_teams(all_injuries, teams_to_assess)
injuries_by_team  = group_by_team(injuries_filtered)

# Build team name map
team_name_map = {abbrev: abbrev_to_full_name(abbrev) for abbrev in teams_to_assess}
# Also enrich from actual game data
for g in games:
    team_name_map[g.home_team_abbrev] = g.home_team_name
    team_name_map[g.away_team_abbrev] = g.away_team_name

# Run risk assessment — uses filtered stats (min_games) for scoring
all_reports: list[TeamRiskReport] = run_full_risk_assessment(
    teams_playing=teams_to_assess,
    injuries_by_team=injuries_by_team,
    player_stats_map=player_stats,        # filtered — reliable averages for scoring
    player_stats_full=player_stats_full,  # unfiltered — for display in cards
    team_name_map=team_name_map,
)

# Build lookup dict
reports_by_team: dict[str, TeamRiskReport] = {r.team_abbrev: r for r in all_reports}

# Apply sidebar filters
filtered_reports = [
    r for r in all_reports
    if r.final_risk_score >= min_risk_score
    and not (hide_low_risk and r.risk_tier == "Low")
]


# ════════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════════
col_title, col_meta = st.columns([3, 1])
with col_title:
    st.markdown("# 🏀 NBA Injury Risk Dashboard")
    today_str  = datetime.now().strftime("%A, %B %d, %Y")
    loaded_str = data["loaded_at"].strftime("%-I:%M %p")
    window_str = f"last {selected_last_n} games" if selected_last_n > 0 else "full season"

    # Try to show which injury report version was loaded
    try:
        from data.injuries import get_latest_report_info
        _, report_label = get_latest_report_info()
        report_str = f"Injury report: {report_label}"
    except Exception:
        report_str = f"Data loaded: {loaded_str}"

    st.markdown(
        f"<span style='color:#9AA0B3;'>{today_str} · {report_str} · Stats: {window_str}</span>",
        unsafe_allow_html=True
    )

with col_meta:
    st.markdown("<br>", unsafe_allow_html=True)
    games_count  = len(games)
    injured_count = len(injuries_filtered)
    critical_count = sum(1 for r in all_reports if r.risk_tier == "Critical")
    m1, m2, m3 = st.columns(3)
    m1.metric("Games Today", games_count)
    m2.metric("Players Injured", injured_count)
    m3.metric("🔴 Critical Teams", critical_count)

# Show any data load errors
if errors:
    with st.expander("⚠️ Data warnings", expanded=False):
        for err in errors:
            st.warning(err)

render_divider()


# ════════════════════════════════════════════════════════════════════
# TAB LAYOUT
# ════════════════════════════════════════════════════════════════════
tab_overview, tab_matchups, tab_deepdive, tab_table, tab_debug = st.tabs([
    "📊 Risk Overview",
    "🆚 Today's Matchups",
    "🔍 Team Deep Dive",
    "📋 Full Injury Table",
    "🛠️ Debug",
])


# ─────────────────────────────────────────────
# TAB 1: RISK OVERVIEW
# ─────────────────────────────────────────────
with tab_overview:
    if not filtered_reports:
        st.info("No games found for today, or no teams meet the current filter criteria.")
    else:
        # Summary bar chart
        render_section_title("All Teams at a Glance", "📊")
        fig_bar = risk_bar_chart(filtered_reports)
        st.plotly_chart(fig_bar, width="stretch")

        render_divider()

        # Risk tier groups
        tiers = ["Critical", "High", "Medium", "Low"]
        tier_reports = {t: [r for r in filtered_reports if r.risk_tier == t] for t in tiers}

        for tier in tiers:
            t_reports = tier_reports[tier]
            if not t_reports:
                continue

            tier_colors = {"Critical": "#FF2D2D", "High": "#FF8C00", "Medium": "#FFD700", "Low": "#32CD32"}
            color = tier_colors[tier]
            emojis = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}

            st.markdown(
                f"<h3 style='color:{color};margin-bottom:8px;'>{emojis[tier]} {tier} Risk</h3>",
                unsafe_allow_html=True
            )
            cols = st.columns(min(len(t_reports), 3))
            for i, report in enumerate(t_reports):
                with cols[i % 3]:
                    render_risk_card(report)

            st.markdown("<br>", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# TAB 2: TODAY'S MATCHUPS
# ─────────────────────────────────────────────
with tab_matchups:
    if not games:
        st.info("No games scheduled for today (or schedule couldn't be loaded).")
    else:
        render_section_title("Today's Games", "🆚")

        for game in games:
            home = game.home_team_abbrev
            away = game.away_team_abbrev

            home_report = reports_by_team.get(home)
            away_report = reports_by_team.get(away)

            render_matchup_card(
                away_abbrev=away, away_name=game.away_team_name, away_report=away_report,
                home_abbrev=home, home_name=game.home_team_name, home_report=home_report,
                game_time=game.game_time, status=game.status,
            )

            # Gauge comparison
            if home_report and away_report:
                fig_gauge = matchup_risk_comparison(home_report, away_report)
                st.plotly_chart(fig_gauge, width="stretch", key=f"gauge_{game.game_id}")

            # Quick bullet summaries
            with st.expander(f"Injury details: {away} @ {home}", expanded=False):
                dc1, dc2 = st.columns(2)

                for col, abbrev, name in [(dc1, away, game.away_team_name), (dc2, home, game.home_team_name)]:
                    with col:
                        report = reports_by_team.get(abbrev)
                        st.markdown(f"**{name}**")
                        if report and report.player_impacts:
                            for impact in report.player_impacts[:5]:
                                render_player_injury_row(impact)
                        else:
                            st.markdown("<span style='color:#9AA0B3;font-size:0.85rem;'>No significant injuries reported</span>",
                                       unsafe_allow_html=True)

            render_divider()


# ─────────────────────────────────────────────
# TAB 3: TEAM DEEP DIVE
# ─────────────────────────────────────────────
with tab_deepdive:
    render_section_title("Team Deep Dive", "🔍")

    # Team selector
    selectable_teams = sorted(
        [(r.team_abbrev, f"{r.team_abbrev} — {r.team_name} ({r.risk_emoji} {r.risk_tier})")
         for r in all_reports],
        key=lambda x: x[0]
    )

    if not selectable_teams:
        st.info("No teams to analyze.")
    else:
        selected_abbrev = st.selectbox(
            "Select a team",
            options=[t[0] for t in selectable_teams],
            format_func=lambda x: next((t[1] for t in selectable_teams if t[0] == x), x),
        )

        report = reports_by_team.get(selected_abbrev)

        if not report:
            st.info(f"No data for {selected_abbrev}.")
        else:
            # ── Header ──
            st.markdown(
                f"<h2 style='color:{report.risk_color};'>"
                f"{report.risk_emoji} {report.team_name} "
                f"<span style='font-size:1rem;color:#9AA0B3;'>Risk Score: {report.final_risk_score:.1f} / 100</span>"
                f"</h2>",
                unsafe_allow_html=True
            )

            # ── Top metrics ──
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Risk Tier",       report.risk_tier)
            mc2.metric("Total Injured",   report.total_injured)
            mc3.metric("Definitely Out",  report.out_count)
            mc4.metric("Questionable",    report.questionable_count)

            render_divider()

            # ── Charts ──
            chart_col, radar_col = st.columns([3, 2])

            with chart_col:
                render_section_title("Player Impact Breakdown", "📊")
                if report.player_impacts:
                    fig_waterfall = player_impact_waterfall(report.player_impacts, report.team_name)
                    st.plotly_chart(fig_waterfall, width="stretch")
                else:
                    st.info("No injured players found for this team.")

            with radar_col:
                render_section_title("Dimensions Affected", "🕸️")
                fig_radar = radar_chart(report)
                st.plotly_chart(fig_radar, width="stretch")

                # Dimension explanations
                st.markdown("""
                <div style='font-size:0.72rem;color:#9AA0B3;line-height:1.6;'>
                <b>Scoring</b> — points share lost<br>
                <b>Playmaking</b> — assists / creation lost<br>
                <b>Rebounding</b> — boards lost<br>
                <b>Defense</b> — blocks + steals lost<br>
                <b>Depth</b> — total number of injuries
                </div>
                """, unsafe_allow_html=True)

            render_divider()

            # ── Injured players detail list ──
            render_section_title("Injured Players", "🩹")

            if report.player_impacts:
                for impact in report.player_impacts:
                    render_player_injury_row(impact)

                # Full stats table
                render_section_title("Full Stats Table", "📋")
                df_table = stats_comparison_table(report.player_impacts)
                if not df_table.empty:
                    st.dataframe(
                        df_table,
                        width="stretch",
                        hide_index=True,
                    )
            else:
                st.info("No injury data found for this team today.")


# ─────────────────────────────────────────────
# TAB 4: FULL INJURY TABLE
# ─────────────────────────────────────────────
with tab_table:
    render_section_title("All Injuries — Today's Teams", "📋")

    if not injuries_filtered:
        st.info("No injury data available for today's teams.")
    else:
        # Build a flat table of all injured players with their stats + impact scores
        table_rows = []
        for report in all_reports:
            for imp in report.player_impacts:
                table_rows.append({
                    "Team":         imp.team_abbrev,
                    "Player":       imp.player_name,
                    "Status":       imp.status,
                    "Injury":       imp.injury_type,
                    "Impact Score": round(imp.weighted_impact_score * 100, 1),
                    "PPG":          round(imp.ppg, 1),
                    "RPG":          round(imp.rpg, 1),
                    "APG":          round(imp.apg, 1),
                    "BPG":          round(imp.bpg, 1),
                    "SPG":          round(imp.spg, 1),
                    "Usage %":      round(imp.usage_pct, 1),
                    "Pts Share":    f"{round(imp.points_share_pct, 1)}%",
                    "GP":           imp.games_played,
                    "In Stats DB":  "✅" if imp.found_in_stats else "❌",
                })

        df_all = pd.DataFrame(table_rows)

        if not df_all.empty:
            # Sorting & filtering
            filter_col1, filter_col2, filter_col3 = st.columns(3)
            with filter_col1:
                team_filter = st.multiselect("Filter by team", sorted(df_all["Team"].unique()), default=[])
            with filter_col2:
                status_filter = st.multiselect("Filter by status", sorted(df_all["Status"].unique()), default=[])
            with filter_col3:
                sort_by = st.selectbox("Sort by", ["Impact Score", "PPG", "Usage %", "Player"], index=0)

            df_display = df_all.copy()
            if team_filter:
                df_display = df_display[df_display["Team"].isin(team_filter)]
            if status_filter:
                df_display = df_display[df_display["Status"].isin(status_filter)]

            df_display = df_display.sort_values(sort_by, ascending=False)

            st.dataframe(
                df_display,
                width="stretch",
                hide_index=True,
                height=min(600, len(df_display) * 36 + 50),
            )

            # Download button
            csv = df_display.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Download as CSV",
                data=csv,
                file_name=f"nba_injuries_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )


# ─────────────────────────────────────────────
# TAB 5: DEBUG
# ─────────────────────────────────────────────
with tab_debug:
    st.markdown("## 🛠️ Data Pipeline Diagnostics")
    st.caption("Use this tab to see exactly what data is being collected at each stage.")

    render_divider()

    # ── 1. Schedule ──
    render_section_title("1. Today's Schedule", "📅")
    if games:
        st.success(f"✅ Found **{len(games)}** games today")
        sched_rows = [{
            "Away": g.away_team_abbrev,
            "Home": g.home_team_abbrev,
            "Time": g.game_time,
            "Status": g.status,
        } for g in games]
        st.dataframe(pd.DataFrame(sched_rows), hide_index=True, width="stretch")
    else:
        st.error("❌ No games found — schedule fetch may have failed")

    st.markdown(f"**Teams playing today:** `{sorted(teams_today)}`")

    render_divider()

    # ── 2. Raw injuries ──
    render_section_title("2. Raw Injury Scrape", "🩹")
    st.markdown(f"Total players scraped (all teams): **{len(all_injuries)}**")

    if all_injuries:
        st.success(f"✅ Scraped {len(all_injuries)} injured players")

        # Team distribution
        team_counts = {}
        for p in all_injuries:
            team_counts[p.team_abbrev] = team_counts.get(p.team_abbrev, 0) + 1
        st.markdown("**Players per team:**")
        tc_df = pd.DataFrame(
            sorted(team_counts.items(), key=lambda x: x[1], reverse=True),
            columns=["Team", "Injured Players"]
        )
        st.dataframe(tc_df, hide_index=True, width="stretch")

        # Source distribution
        sources = {}
        for p in all_injuries:
            sources[p.source] = sources.get(p.source, 0) + 1
        st.markdown(f"**Sources:** {sources}")

        # Full raw list
        with st.expander("Show all scraped players"):
            raw_rows = [{
                "Name": p.name,
                "Team": p.team_abbrev,
                "Status": p.status,
                "Injury": p.injury_type,
                "Weight": p.availability_weight,
                "Source": p.source,
            } for p in all_injuries]
            st.dataframe(pd.DataFrame(raw_rows), hide_index=True, width="stretch")
    else:
        st.error("❌ Zero injured players scraped — scraper likely failed or got blocked")
        st.info(
            "**Common fixes:**\n"
            "1. ESPN may have changed their HTML structure — check the logs\n"
            "2. You may be getting rate-limited — wait 60s and refresh\n"
            "3. Try running: `python -c \"from data.injuries import fetch_espn_injuries; print(fetch_espn_injuries())\"`"
        )

    render_divider()

    # ── 3. Injuries matched to today's teams ──
    render_section_title("3. Injuries Matched to Today's Games", "🔗")
    st.markdown(f"Injuries filtered to today's teams: **{len(injuries_filtered)}**")

    if injuries_filtered:
        st.success(f"✅ {len(injuries_filtered)} injuries matched to today's {len(teams_today)} teams")
    else:
        if all_injuries:
            st.error("❌ Players scraped, but NONE match today's teams")
            st.warning(
                "This usually means team abbreviations didn't normalize correctly.\n"
                f"Today's teams: `{sorted(teams_today)}`\n\n"
                "Scraped team abbrevs: `" +
                str(sorted({p.team_abbrev for p in all_injuries})) + "`"
            )
        else:
            st.warning("No injuries to match (scrape returned empty)")

    render_divider()

    # ── 4. Player stats lookup ──
    render_section_title("4. Player Stats Database", "📊")
    window_str = f"last {selected_last_n} games" if selected_last_n > 0 else "full season"
    st.markdown(
        f"Players in stats DB: **{len(player_stats_full)}** total · "
        f"**{len(player_stats)}** meet min {min_games} games filter · "
        f"window: **{window_str}**"
    )

    if player_stats_full:
        sample = next(iter(player_stats_full.values()))
        source_hint = "NBA Stats API" if sample.player_id != 0 else "ESPN fallback"
        st.success(f"✅ Stats DB loaded · source: **{source_hint}**")

        with st.expander("Preview 5 sample players from stats DB"):
            import random
            sample_names = random.sample(list(player_stats_full.keys()), min(5, len(player_stats_full)))
            sample_rows = [{
                "Name": player_stats_full[n].player_name,
                "Team": player_stats_full[n].team_abbrev,
                "GP": player_stats_full[n].games_played,
                "PPG": player_stats_full[n].points_per_game,
                "RPG": player_stats_full[n].rebounds_per_game,
                "USG%": round(player_stats_full[n].usage_rate, 1),
            } for n in sample_names]
            st.dataframe(pd.DataFrame(sample_rows), hide_index=True)

        # Check match rate against the FULL (unfiltered) map — same as the engine uses
        if injuries_filtered:
            matched_full = 0
            matched_filtered = 0
            unmatched = []
            from data.player_stats import lookup_player
            for inj in injuries_filtered:
                in_full     = lookup_player(inj.name, player_stats_full)
                in_filtered = lookup_player(inj.name, player_stats)
                if in_full:
                    matched_full += 1
                else:
                    unmatched.append(inj.name)
                if in_filtered:
                    matched_filtered += 1

            match_rate = matched_full / len(injuries_filtered) * 100
            color = "✅" if match_rate >= 70 else ("⚠️" if match_rate >= 40 else "❌")
            st.markdown(
                f"{color} **Name match rate (full DB):** {matched_full}/{len(injuries_filtered)} "
                f"({match_rate:.0f}%)"
            )
            st.caption(
                f"Of those, {matched_filtered} also meet the min-{min_games}-games filter "
                f"and contribute to risk scores. The remaining {matched_full - matched_filtered} "
                f"(e.g. Embiid — too few games played) still show stats on their card "
                f"but use a reduced weight in the risk score."
            )
            if unmatched:
                with st.expander(f"Truly unmatched names ({len(unmatched)}) — not found in any stats"):
                    st.write(unmatched)
                    st.caption(
                        "These are typically G League / two-way players with no NBA stats. "
                        "They receive a small default impact score of 0.08 and are shown "
                        "with 'Insufficient games played' on their card. They do NOT "
                        "significantly affect team risk scores."
                    )
    else:
        st.error("❌ Stats DB empty")
        st.warning(
            "The NBA Stats API is blocked or timed out.\n\n"
            "**Try these steps:**\n"
            "1. Click **🔄 Refresh All Data** in the sidebar\n"
            "2. Wait 60 seconds and try again — the API throttles heavily\n"
            "3. Check your internet connection"
        )

    render_divider()

    # ── 5. Risk scores ──
    render_section_title("5. Final Risk Scores", "🎯")
    if all_reports:
        score_rows = [{
            "Team": r.team_abbrev,
            "Risk Score": round(r.final_risk_score, 1),
            "Tier": r.risk_tier,
            "Injured": r.total_injured,
            "Out": r.out_count,
            "Questionable": r.questionable_count,
        } for r in all_reports]
        st.dataframe(
            pd.DataFrame(score_rows).sort_values("Risk Score", ascending=False),
            hide_index=True, width="stretch"
        )
        zero_risk = sum(1 for r in all_reports if r.final_risk_score == 0)
        if zero_risk == len(all_reports):
            st.error("❌ ALL teams are at 0 risk — data pipeline has an upstream failure")
        elif zero_risk > 0:
            st.warning(f"⚠️ {zero_risk} teams have 0 risk (likely no injuries matched for those teams)")
        else:
            st.success("✅ Risk scores look healthy")
    else:
        st.error("❌ No risk reports generated")

    render_divider()

    # ── 6. Raw data errors ──
    render_section_title("6. Load Errors", "⚠️")
    if errors:
        for err in errors:
            st.error(err)
    else:
        st.success("✅ No errors during data load")


# ════════════════════════════════════════════════════════════════════
# FOOTER
# ════════════════════════════════════════════════════════════════════
render_divider()
st.markdown(
    "<div style='text-align:center;color:#555;font-size:0.75rem;'>"
    "Data from ESPN · NBA Stats API · Injury impact model uses weighted stat shares<br>"
    "Not financial or betting advice. For entertainment purposes."
    "</div>",
    unsafe_allow_html=True
)
