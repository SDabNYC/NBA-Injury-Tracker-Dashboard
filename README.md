# 🏀 NBA Injury Risk Dashboard

A Streamlit dashboard that assesses which NBA teams playing today
are most at risk due to player injuries — based on actual statistical impact.

---

## What It Does

1. **Fetches today's schedule** from the NBA Stats API
2. **Scrapes injury reports** from ESPN (with Yahoo as fallback)
3. **Loads season stats** for every injured player via `nba_api`
4. **Computes an Impact Score** per player using:
   - Points share (what % of team scoring they provide)
   - Usage rate (how much the offense runs through them)
   - Assists share (playmaking contribution)
   - Rebounds share
   - Player Efficiency Index (PIE)
   - Blocks & Steals share (defense)
5. **Rolls up to a Team Risk Score** (0–100) with diminishing returns
   for multiple injuries and availability weighting:
   - Out → 1.0x weight
   - Doubtful → 0.75x
   - Questionable → 0.40x
   - Day-To-Day → 0.20x
6. **Displays** risk tiers: 🟢 Low / 🟡 Medium / 🟠 High / 🔴 Critical

---

## Project Structure

```
nba_dashboard/
├── app.py                    ← Main Streamlit app (run this)
├── requirements.txt
│
├── data/
│   ├── schedule.py           ← Today's games (nba_api)
│   ├── injuries.py           ← Injury scraper (ESPN + Yahoo)
│   ├── player_stats.py       ← Season stats + team shares
│   └── cache_manager.py      ← Streamlit cache wrappers
│
├── scoring/
│   └── risk_engine.py        ← Core risk scoring model
│
├── ui/
│   ├── components.py         ← Cards, badges, layout helpers
│   └── charts.py             ← Plotly chart builders
│
└── utils/
    └── name_normalizer.py    ← Player/team name normalization
```

---

## Setup

### 1. Clone / copy the project

```bash
cd nba_dashboard
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv
source venv/bin/activate    # Mac/Linux
# or
venv\Scripts\activate       # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the dashboard

```bash
streamlit run app.py
```

The app will open at `http://localhost:8501`

---

## Tabs

| Tab | What you see |
|-----|-------------|
| 📊 Risk Overview | All teams ranked by risk score, grouped by tier |
| 🆚 Today's Matchups | Each game with gauge comparison between teams |
| 🔍 Team Deep Dive | Per-team drill: player list, bar chart, radar chart |
| 📋 Full Injury Table | Sortable/filterable table of all injured players |

---

## Sidebar Controls

- **Refresh** — clears the cache and re-fetches everything
- **Min games played** — filter out players with too few games for meaningful stats
- **Stat weights** — adjust how much scoring vs. playmaking vs. defense matters
- **Filters** — hide low-risk teams or set a minimum risk threshold

---

## Customization

### Change the risk tier thresholds

In `scoring/risk_engine.py`:

```python
RISK_TIERS = [
    (80, "Critical", "#FF2D2D", "🔴"),
    (55, "High",     "#FF8C00", "🟠"),
    (30, "Medium",   "#FFD700", "🟡"),
    (0,  "Low",      "#32CD32", "🟢"),
]
```

### Change the default stat weights

```python
STAT_WEIGHTS = {
    "points_share":    0.35,
    "usage_rate":      0.20,
    "assists_share":   0.15,
    "rebounds_share":  0.12,
    "per":             0.10,
    "blocks_share":    0.04,
    "steals_share":    0.04,
}
```

### Change cache durations

In `data/cache_manager.py`:

```python
SCHEDULE_TTL   = 300    # seconds
INJURIES_TTL   = 600
STATS_TTL      = 3600
```

---

## Known Gotchas

- **Name mismatches** — the `utils/name_normalizer.py` handles most cases.
  Add manual overrides to `NAME_OVERRIDES` if a specific player keeps breaking.
- **NBA API rate limits** — there's a 0.7s delay between calls. If you see
  `json.JSONDecodeError`, the API is throttling you. Increase `RATE_LIMIT_DELAY`.
- **ESPN scraping** — ESPN occasionally changes their HTML structure.
  If injuries come back empty, inspect `fetch_espn_injuries()` and update selectors.
- **Dates** — the official NBA injury report PDF drops at specific times.
  ESPN is usually more real-time for day-of updates.

---

## Data Sources

| Data | Source | Method |
|------|--------|--------|
| Today's schedule | NBA Stats API | `nba_api` library |
| Injury reports | ESPN | BeautifulSoup scraping |
| Injury fallback | Yahoo Sports | BeautifulSoup scraping |
| Player stats | NBA Stats API | `nba_api` library |
| Team averages | NBA Stats API | `nba_api` library |
