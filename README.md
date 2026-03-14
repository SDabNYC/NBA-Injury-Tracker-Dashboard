# 🏀 NBA Injury Risk Dashboard

A Streamlit dashboard that assesses which NBA teams playing today are most at risk due to player injuries — based on statistical impact analysis.

---

## What It Does

1. **Fetches today's schedule** from the NBA Stats API (using Eastern Time)
2. **Downloads the official NBA Injury Report PDF** from `official.nba.com/nba-injury-report-2025-26-season/` — the authoritative source, updated every ~15 minutes throughout game day
3. **Loads season stats** for every player via direct calls to `stats.nba.com` — using a dual-window approach:
   - Full season averages (baseline — captures long-term injured players like Embiid)
   - Last 15 games overlay (current form — overwrites active players with recent numbers)
4. **Computes an Impact Score** per injured player using a 3-component model:
   - **Offense (65%)** — scoring + playmaking share, weighted by usage × true shooting efficiency
   - **Defense (20%)** — blocks share, steals share, rebounds share
   - **Efficiency (15%)** — Player Impact Estimate (PIE)
5. **Rolls up to a Team Risk Score (0–100)** with:
   - Diminishing returns for multiple injuries (losing 3 role players ≠ losing 1 star)
   - Availability weighting by status: Out → 1.0×, Doubtful → 0.75×, Questionable → 0.40×, Day-To-Day → 0.20×
   - Relative normalization across today's teams so there's always meaningful spread
6. **Displays risk tiers** with an absolute floor to prevent inflated ratings on light injury days:
   - 🟢 Low / 🟡 Medium / 🟠 High / 🔴 Critical

---

## Project Structure

```
nba_dashboard/
├── app.py                    ← Main Streamlit app (run this)
├── requirements.txt
│
├── data/
│   ├── schedule.py           ← Today's games (NBA Stats API, ET timezone)
│   ├── injuries.py           ← Official NBA PDF scraper + parser
│   ├── player_stats.py       ← Season stats via stats.nba.com direct HTTP
│   └── cache_manager.py      ← Streamlit cache wrappers (date-keyed)
│
├── scoring/
│   └── risk_engine.py        ← 3-component impact model + relative normalization
│
├── ui/
│   ├── components.py         ← Player cards, matchup displays, risk cards
│   └── charts.py             ← Plotly charts (bar, waterfall, radar, gauge)
│
└── utils/
    └── name_normalizer.py    ← Player/team name normalization + fuzzy matching
```

---

## Setup

```bash
# 1. Navigate to the project folder
cd nba_dashboard

# 2. Create a virtual environment (requires Python 3.10+)
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
streamlit run app.py
```

---

## Tabs

| Tab | What you see |
|-----|-------------|
| 📊 Risk Overview | All teams ranked by risk score, grouped by tier |
| 🆚 Today's Matchups | Each game with gauge comparison between teams |
| 🔍 Team Deep Dive | Per-team drill: player list, bar chart, radar chart |
| 📋 Full Injury Table | Sortable/filterable table of all injured players |
| 🛠️ Debug | Full data pipeline diagnostics — what was fetched, match rates, errors |

---

## Data Sources

| Data | Source | Method |
|------|--------|--------|
| Today's schedule | NBA Stats API | `nba_api` + direct HTTP fallback |
| Injury reports | Official NBA Injury Report PDF | Scraped from `official.nba.com`, parsed with `pdfplumber` |
| Player stats | `stats.nba.com` | Direct HTTP (dual window: full season + last 15 games) |
| Team averages | `stats.nba.com` | Direct HTTP |

---

## How the Risk Score Works

**Per player:**
```
offense  = (pts_share × 0.55 + ast_share × 0.45) × 0.55
         + (usage_normalized × true_shooting_normalized) × 0.45

defense  = blk_share × 0.40 + stl_share × 0.40 + reb_share × 0.20

impact   = offense × 0.65 + defense × 0.20 + PIE_normalized × 0.15

weighted = impact × availability_weight  (1.0 if Out, 0.75 if Doubtful, etc.)
```

**Per team:**
- Sum player impacts with diminishing returns (each additional injury counts 80% of the previous)
- Normalize relative to all teams playing today (highest = 100)
- Blend with an absolute scale (30%) to prevent inflating ratings on quiet injury days
- Assign tier based on percentile rank + absolute floor threshold

---

## Injury Report Timing

The official NBA injury report updates continuously throughout game day — roughly every 15 minutes from early morning until tipoff. The dashboard header shows which report version is loaded (e.g. "9:15 AM ET report"). Hit **🔄 Refresh** in the sidebar to pull the latest version at any time.

---

## Known Limitations

- **Players with very few games** (e.g. long-term injured stars) appear in the stats DB with limited data. Their stats are shown on the card but carry less weight in the risk score.
- **G League / two-way players** listed on injury reports have no NBA stats and receive a small default impact of 0.08.
- **NOT YET SUBMITTED** teams in the injury PDF (common early in the day) will show 0 risk until their report is filed.
- The NBA Stats API occasionally throttles requests — if stats don't load, wait 60 seconds and hit Refresh.
