"""
Injury data fetcher — Official NBA Injury Report PDF.

PDF URL pattern (confirmed from live page):
  https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM.pdf

PDF text format (confirmed from actual PDF):
  Full row:  "03/14/2026 01:00 (ET) BKN@PHI Brooklyn Nets Agbaji, Ochai Probable Injury/Illness..."
  New team:  "Philadelphia 76ers Bona, Adem Questionable Injury/Illness..."
  Same team: "Claxton, Nic Out Rest"
  Suffix:    "Porter Jr., Michael Out Injury/Illness..."

Key: every player row contains exactly one comma (Last, First format).
     The STATUS keyword anchors the split between name and reason.
"""

import re
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Dict, Set, Optional, Tuple

import requests
import pdfplumber
from bs4 import BeautifulSoup

from utils.name_normalizer import normalize_player_name

logger = logging.getLogger(__name__)

NBA_REPORT_PAGE = "https://official.nba.com/nba-injury-report-2025-26-season/"

STATUS_WEIGHTS = {
    "Out": 1.00, "Injured Reserve": 1.00, "Suspended": 1.00,
    "Doubtful": 0.75, "Game Time Decision": 0.35,
    "Questionable": 0.40, "Day-To-Day": 0.20,
}
SKIP_STATUSES = {"Available", "Probable", "Unknown"}

# All 30 teams — longer names first so regex matches greedily
TEAM_NAME_MAP = {
    "Golden State Warriors": "GSW", "Oklahoma City Thunder": "OKC",
    "Portland Trail Blazers": "POR", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "Los Angeles Clippers": "LAC",
    "Los Angeles Lakers": "LAL", "San Antonio Spurs": "SAS",
    "Philadelphia 76ers": "PHI", "Milwaukee Bucks": "MIL",
    "Cleveland Cavaliers": "CLE", "Washington Wizards": "WAS",
    "Memphis Grizzlies": "MEM", "Charlotte Hornets": "CHA",
    "Indiana Pacers": "IND", "Brooklyn Nets": "BKN",
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS",
    "Chicago Bulls": "CHI", "Dallas Mavericks": "DAL",
    "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Houston Rockets": "HOU", "Miami Heat": "MIA",
    "New York Knicks": "NYK", "Orlando Magic": "ORL",
    "Phoenix Suns": "PHX", "Sacramento Kings": "SAC",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA",
    # Short forms the NBA PDF actually uses
    "LA Clippers": "LAC", "LA Lakers": "LAL",
    "Golden State": "GSW", "Oklahoma City": "OKC",
    "New Orleans": "NOP", "San Antonio": "SAS",
    "New York": "NYK", "Portland": "POR",
}
KNOWN_ABBREVS = set(TEAM_NAME_MAP.values())

# Sorted longest-first for greedy matching
TEAMS_BY_LENGTH = sorted(TEAM_NAME_MAP.keys(), key=len, reverse=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://official.nba.com/",
}

# Status keywords — longer ones first (Game Time Decision before Game)
STATUS_KEYWORDS = [
    "Game Time Decision", "Injured Reserve", "Day-To-Day",
    "Questionable", "Doubtful", "Suspended", "Available", "Probable", "Out",
]


@dataclass
class InjuredPlayer:
    name: str
    team_abbrev: str
    status: str
    injury_type: str
    injury_detail: str
    return_date: str
    availability_weight: float = 1.0
    source: str = "NBA PDF"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_all_injuries() -> List[InjuredPlayer]:
    """Download and parse the latest official NBA injury report PDF."""
    pdf_url, report_label = _find_latest_pdf_url()
    logger.info(f"Using PDF: {pdf_url}  [{report_label}]")

    resp = requests.get(pdf_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    logger.info(f"PDF: {len(resp.content):,} bytes")

    players = _parse_pdf(resp.content)
    logger.info(f"Parsed {len(players)} injured players from PDF")
    return players


def get_latest_report_info() -> Tuple[str, str]:
    """Return (url, label) of the latest PDF — used for dashboard header."""
    return _find_latest_pdf_url()


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: find the latest PDF URL on the NBA official page
# ─────────────────────────────────────────────────────────────────────────────

def _find_latest_pdf_url() -> Tuple[str, str]:
    """
    Scrape official.nba.com/nba-injury-report-2025-26-season/ and
    return (url, label) of the most recently published PDF.

    Confirmed URL structure from live page:
      https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-03-14_09_15AM.pdf
    Link text: "9:15 a.m ET report"
    """
    resp = requests.get(NBA_REPORT_PAGE, headers=HEADERS, timeout=20)
    logger.info(f"Report page: HTTP {resp.status_code}")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    today_str = date.today().strftime("%Y-%m-%d")

    # Collect all links pointing to the referee/injury CDN
    pdf_links: List[Tuple[str, str]] = []  # (url, label)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Normalize protocol-relative URLs
        if href.startswith("//"):
            href = "https:" + href
        if "referee/injury" in href and href.endswith(".pdf"):
            label = a.get_text(strip=True) or href.split("/")[-1]
            pdf_links.append((href, label))

    logger.info(f"Found {len(pdf_links)} injury PDF links")

    if not pdf_links:
        raise RuntimeError(
            f"No PDF links found on {NBA_REPORT_PAGE}. "
            "Run the app and check the Debug tab."
        )

    # Sort by datetime in filename
    # Pattern: Injury-Report_YYYY-MM-DD_HH_MMAM.pdf  (confirmed)
    def _dt_key(url: str) -> datetime:
        m = re.search(
            r"Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf",
            url, re.IGNORECASE,
        )
        if not m:
            return datetime.min
        ds = m.group(1)
        hh, mm = int(m.group(2)), int(m.group(3))
        ampm   = m.group(4).upper()
        if ampm == "PM" and hh != 12:
            hh += 12
        elif ampm == "AM" and hh == 12:
            hh = 0
        try:
            return datetime.strptime(f"{ds} {hh:02d}:{mm:02d}", "%Y-%m-%d %H:%M")
        except ValueError:
            return datetime.min

    # Prefer today's reports; fall back to latest overall
    todays = [(u, l) for u, l in pdf_links if today_str in u]
    pool   = todays if todays else pdf_links
    pool.sort(key=lambda x: _dt_key(x[0]))
    best_url, best_label = pool[-1]

    if not todays:
        logger.warning(f"No today's PDF found — using latest: {best_url}")

    return best_url, best_label


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: parse the PDF
# ─────────────────────────────────────────────────────────────────────────────

def _parse_pdf(pdf_bytes: bytes) -> List[InjuredPlayer]:
    """Extract all text from the PDF and parse it line by line."""
    all_lines: List[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        logger.info(f"PDF pages: {len(pdf.pages)}")
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            all_lines.extend(text.split("\n"))
    return _parse_lines(all_lines)


def _parse_lines(lines: List[str]) -> List[InjuredPlayer]:
    """
    State machine parser for NBA injury report PDF text.

    Line types (determined by content):
      A) Full game row:  starts with date MM/DD/YYYY
         → update current team, parse player
      B) New team row:   starts with/contains a known team name
         → update current team, parse player
      C) Player row:     contains a comma (Last, First) + status keyword
         → parse player using current team
      D) Skip:           headers, page numbers, NOT YET SUBMITTED

    The comma in "Lastname, Firstname" is the reliable player identifier.
    The STATUS keyword anchors everything: name is before it, reason after.
    """
    players: List[InjuredPlayer] = []
    seen: Set[Tuple[str, str]] = set()
    current_team_full   = ""
    current_team_abbrev = ""

    SKIP_FRAGMENTS = [
        "game date", "game time", "matchup", "current status",
        "injury report:", "page ", "report generated",
        "not yet submitted",
    ]

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # Skip headers / page markers
        ll = line.lower()
        if any(f in ll for f in SKIP_FRAGMENTS):
            continue

        # ── Update current team if this line mentions a known team name ──
        for team_full in TEAMS_BY_LENGTH:
            if team_full in line:
                current_team_full   = team_full
                current_team_abbrev = TEAM_NAME_MAP[team_full]
                break

        # ── Must have a comma to contain a player name ───────────────────
        if "," not in line:
            continue
        if not current_team_abbrev:
            continue

        # ── Find the status keyword ───────────────────────────────────────
        status_kw, status_pos = _find_status(line)
        if not status_kw:
            continue

        status = _normalize_status(status_kw)
        if status in SKIP_STATUSES:
            continue

        # ── Everything before the status = date/matchup/team/player name ─
        prefix = line[:status_pos].strip()

        # Strip full date+time+matchup prefix: "MM/DD/YYYY HH:MM (ET) XXX@YYY "
        prefix = re.sub(
            r"^\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s*\(ET\)\s*\w{3,8}@\w{3,8}\s*",
            "", prefix
        ).strip()

        # Strip time-only+matchup prefix (new game slot without date):
        # e.g. "03:00 (ET) MIL@ATL " or "08:30 (ET) DEN@LAL "
        prefix = re.sub(
            r"^\d{1,2}:\d{2}\s*\(ET\)\s*\w{3,8}@\w{3,8}\s*",
            "", prefix
        ).strip()

        # Strip any stray matchup pattern remaining anywhere in prefix
        # e.g. if first_name field captured "Alex 03:00 (et) Mil@atl"
        prefix = re.sub(
            r"\d{1,2}:\d{2}\s*\(ET\)\s*\w{3,8}@\w{3,8}",
            "", prefix, flags=re.IGNORECASE
        ).strip()

        # Strip team name from prefix (appears at start for new-team rows)
        if current_team_full in prefix:
            prefix = prefix.replace(current_team_full, "").strip()

        # ── Extract player name from "Last, First [Suffix]" pattern ──────
        # The last comma in prefix separates Last from First
        comma_pos = prefix.rfind(",")
        if comma_pos == -1:
            continue

        last_name  = prefix[:comma_pos].strip()
        first_name = prefix[comma_pos + 1:].strip()

        # Sanity: last_name and first_name should be non-empty alphabetic words
        if not last_name or not first_name:
            continue
        if not re.search(r"[A-Za-z]{2,}", last_name):
            continue
        if not re.search(r"[A-Za-z]{2,}", first_name):
            continue

        # Reject names that still contain game-time/matchup artifacts
        if re.search(r"\d{1,2}:\d{2}", first_name):
            continue
        if "@" in first_name or "@" in last_name:
            continue
        # Reject if last_name contains digits (date artifacts)
        if re.search(r"\d{4}", last_name):
            continue
        # Reject implausibly long name fragments
        if len(first_name) > 30 or len(last_name) > 30:
            continue

        # ── Reason: everything after the status keyword ───────────────────
        reason = line[status_pos + len(status_kw):].strip()
        reason = re.sub(r"^[\s\-–]+", "", reason).strip()

        # ── Build the canonical name: "First Last" ────────────────────────
        full_name    = f"{first_name} {last_name}"
        player_name  = normalize_player_name(full_name)
        if not player_name or len(player_name) < 4:
            continue

        # ── Deduplicate ───────────────────────────────────────────────────
        key = (player_name, current_team_abbrev)
        if key in seen:
            continue
        seen.add(key)

        players.append(InjuredPlayer(
            name=player_name,
            team_abbrev=current_team_abbrev,
            status=status,
            injury_type=_extract_injury_type(reason),
            injury_detail=reason[:250],
            return_date="",
            availability_weight=STATUS_WEIGHTS.get(status, 0.5),
            source="NBA PDF",
        ))

    return players


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_status(line: str) -> Tuple[Optional[str], int]:
    """Find the first (leftmost) status keyword in a line."""
    best_kw  = None
    best_pos = len(line) + 1

    for kw in STATUS_KEYWORDS:
        # Word-boundary match, case-insensitive
        m = re.search(r"\b" + re.escape(kw) + r"\b", line, re.IGNORECASE)
        if m and m.start() < best_pos:
            best_pos = m.start()
            best_kw  = kw  # use canonical casing

    if best_kw:
        return best_kw, best_pos
    return None, -1


def _normalize_status(kw: str) -> str:
    k = kw.strip().lower()
    if "injured reserve" in k: return "Injured Reserve"
    if "suspended"       in k: return "Suspended"
    if "game time"       in k: return "Game Time Decision"
    if "doubtful"        in k: return "Doubtful"
    if "questionable"    in k: return "Questionable"
    if "day-to-day"      in k: return "Day-To-Day"
    if k == "out":             return "Out"
    if "available"       in k: return "Available"
    if "probable"        in k: return "Probable"
    return "Unknown"


def _extract_injury_type(description: str) -> str:
    parts = [
        "achilles", "knee", "ankle", "shoulder", "hamstring", "quad",
        "hip", "groin", "back", "foot", "wrist", "hand", "finger",
        "elbow", "neck", "head", "concussion", "illness", "personal",
        "shin", "calf", "toe", "rib", "abdomen", "chest", "thigh",
        "hernia", "tendon", "ligament", "pelvic", "oblique", "thumb",
        "sesamoid", "plantar", "fascia", "eye", "bilateral",
    ]
    dl = description.lower()
    for part in parts:
        if part in dl:
            return part.title()
    return "Unknown"


def filter_injuries_for_teams(
    injuries: List[InjuredPlayer], team_abbrevs: Set[str]
) -> List[InjuredPlayer]:
    return [p for p in injuries if p.team_abbrev in team_abbrevs]


def group_by_team(injuries: List[InjuredPlayer]) -> Dict[str, List[InjuredPlayer]]:
    result: Dict[str, List[InjuredPlayer]] = {}
    for p in injuries:
        result.setdefault(p.team_abbrev, []).append(p)
    return result
