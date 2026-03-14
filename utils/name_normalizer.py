"""
Name normalization utilities.
Handles mismatches between player names across data sources.
"""

import re
import unicodedata
from typing import Optional
from fuzzywuzzy import fuzz, process

# ── Manual overrides: keys are lowercase, no punctuation ─────────────────────
NAME_OVERRIDES = {
    # Names the NBA API shortens or spells differently
    "lebron james":               "LeBron James",
    "jaren jackson":              "Jaren Jackson Jr.",
    "jaren jackson jr":           "Jaren Jackson Jr.",
    "gary trent":                 "Gary Trent Jr.",
    "gary trent jr":              "Gary Trent Jr.",
    "kelly oubre":                "Kelly Oubre Jr.",
    "kelly oubre jr":             "Kelly Oubre Jr.",
    "wendell carter":             "Wendell Carter Jr.",
    "wendell carter jr":          "Wendell Carter Jr.",
    "larry nance":                "Larry Nance Jr.",
    "larry nance jr":             "Larry Nance Jr.",
    "tim hardaway":               "Tim Hardaway Jr.",
    "tim hardaway jr":            "Tim Hardaway Jr.",
    "derrick jones":              "Derrick Jones Jr.",
    "derrick jones jr":           "Derrick Jones Jr.",
    "kenyon martin":              "Kenyon Martin Jr.",
    "kenyon martin jr":           "Kenyon Martin Jr.",
    "robert williams":            "Robert Williams III",
    "robert williams iii":        "Robert Williams III",
    "nicolas claxton":            "Nic Claxton",
    "nic claxton":                "Nic Claxton",
    "marcus morris sr":           "Marcus Morris Sr.",
    "otto porter":                "Otto Porter Jr.",
    "otto porter jr":             "Otto Porter Jr.",
    # Suffixes sometimes omitted or varied
    "dereck lively":              "Dereck Lively II",
    "dereck lively ii":           "Dereck Lively II",
    "jimmy butler":               "Jimmy Butler",   # no III in stats DB
    "jimmy butler iii":           "Jimmy Butler",
    "jaeseantate":                "Jae'Sean Tate",
    "jaesean tate":               "Jae'Sean Tate",
    "scotty pippen":              "Scotty Pippen Jr.",
    "scotty pippen jr":           "Scotty Pippen Jr.",
    "walter clayton":             "Walter Clayton Jr.",
    "walter clayton jr":          "Walter Clayton Jr.",
    "collin murray-boyles":       "Collin Murray-Boyles",
    "kentavious caldwell-pope":   "Kentavious Caldwell-Pope",
    "santi aldama":               "Santi Aldama",
    "noa essengue":               "Noa Essengue",
    "moussa cisse":               "Moussa Cisse",
    "johnny furphy":              "Johnny Furphy",
    "chris youngblood":           "Chris Youngblood",
    "chucky hepburn":             "Chucky Hepburn",
    "zach edey":                  "Zach Edey",
    "collin murrayboyles":        "Collin Murray-Boyles",
}

TEAM_NAME_MAP = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
    "LA Clippers": "LAC", "LA Lakers": "LAL", "76ers": "PHI", "Sixers": "PHI",
    "Blazers": "POR", "Thunder": "OKC", "Wolves": "MIN", "Pels": "NOP",
    "Cavs": "CLE", "Mavs": "DAL", "Warriors": "GSW",
}

TEAM_ABBREV_TO_FULL = {v: k for k, v in TEAM_NAME_MAP.items() if len(k) > 4}

ESPN_TEAM_MAP = {
    "GS Warriors": "GSW", "SA Spurs": "SAS", "NO Pelicans": "NOP",
    "NY Knicks": "NYK", "OKC Thunder": "OKC", "LA Lakers": "LAL",
    "LA Clippers": "LAC", "POR Trail Blazers": "POR",
}


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _capitalize_part(part: str) -> str:
    """
    Capitalize a single name part, handling:
    - Hyphenated names: Caldwell-Pope, Murray-Boyles
    - Apostrophe names: Jae'Sean, O'Neale
    - Roman numeral suffixes: II, III, IV (kept uppercase)
    - Jr./Sr. suffixes
    - 2-letter initials: KJ, PJ, AJ, TJ, DJ (kept uppercase)
    """
    upper = part.upper().rstrip(".")

    # Roman numerals and generational suffixes — keep uppercase
    if upper in ("II", "III", "IV", "V", "VI"):
        return upper
    if upper in ("JR", "SR"):
        return upper.capitalize() + "."

    # 2-letter all-uppercase initials (KJ, PJ, AJ, TJ, DJ, CJ, etc.)
    # Identified by: exactly 2 alpha chars, both uppercase in original
    if len(part) == 2 and part.isalpha() and part.isupper():
        return part.upper()

    # Handle hyphenated names: capitalize each segment
    if "-" in part:
        return "-".join(_capitalize_part(seg) for seg in part.split("-"))

    # Handle apostrophe names: capitalize after apostrophe too
    if "'" in part:
        segments = part.split("'")
        return "'".join(seg.capitalize() for seg in segments)

    return part.capitalize()


def normalize_player_name(name: str) -> str:
    """
    Normalize a player name to a canonical form suitable for matching.

    Handles:
    - Accented characters (Jokić → Jokic)
    - Hyphenated surnames (caldwell-pope → Caldwell-Pope)
    - Apostrophes (jae'sean → Jae'Sean)
    - Roman numeral suffixes (ii → II, iii → III)
    - Jr./Sr. suffixes
    - Manual overrides for known mismatches
    """
    if not name:
        return ""

    # Strip accents
    name = strip_accents(name.strip())

    # Build a clean lookup key: lowercase, no dots, no apostrophes, no hyphens
    key = name.lower()
    key = re.sub(r"[.'`]", "", key)   # remove dots, apostrophes, backticks
    key = re.sub(r"\s+", " ", key).strip()

    # Check override dict
    if key in NAME_OVERRIDES:
        return NAME_OVERRIDES[key]

    # Also try without hyphens in key (catches "caldwell-pope" → lookup "caldwellpope")
    key_no_hyphen = key.replace("-", "")
    if key_no_hyphen in NAME_OVERRIDES:
        return NAME_OVERRIDES[key_no_hyphen]

    # Capitalize each space-separated part
    parts = name.split()
    return " ".join(_capitalize_part(p) for p in parts)


def fuzzy_match_player(name: str, candidates: list, threshold: int = 72) -> Optional[str]:
    """
    Fuzzy-match a player name against a list of known names.
    Threshold lowered to 72 to handle suffix/apostrophe variations.
    Uses token_sort_ratio which handles word-order differences.
    """
    if not candidates:
        return None

    normalized_input = normalize_player_name(name)

    # Build map from normalized candidate → original candidate
    norm_map = {}
    for c in candidates:
        nc = normalize_player_name(c)
        norm_map[nc] = c

    # Try exact match first after normalization
    if normalized_input in norm_map:
        return norm_map[normalized_input]

    # Fuzzy match
    result = process.extractOne(
        normalized_input,
        list(norm_map.keys()),
        scorer=fuzz.token_sort_ratio,
    )

    if result and result[1] >= threshold:
        return norm_map[result[0]]

    # Second pass: strip suffixes (Jr., III etc.) and try again
    # catches "Jimmy Butler III" vs "Jimmy Butler"
    stripped_input = re.sub(
        r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", normalized_input, flags=re.IGNORECASE
    ).strip()

    if stripped_input != normalized_input:
        result2 = process.extractOne(
            stripped_input,
            list(norm_map.keys()),
            scorer=fuzz.token_sort_ratio,
        )
        if result2 and result2[1] >= threshold:
            return norm_map[result2[0]]

        # Also try matching stripped input against stripped candidates
        stripped_map = {
            re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", k, flags=re.IGNORECASE).strip(): v
            for k, v in norm_map.items()
        }
        result3 = process.extractOne(
            stripped_input,
            list(stripped_map.keys()),
            scorer=fuzz.token_sort_ratio,
        )
        if result3 and result3[1] >= threshold:
            return stripped_map[result3[0]]

    return None


def normalize_team_name(name: str) -> str:
    if not name:
        return ""
    if name in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[name]
    if name in ESPN_TEAM_MAP:
        return ESPN_TEAM_MAP[name]
    if name.upper() in TEAM_ABBREV_TO_FULL:
        return name.upper()
    result = process.extractOne(name, list(TEAM_NAME_MAP.keys()), scorer=fuzz.token_sort_ratio)
    if result and result[1] >= 75:
        return TEAM_NAME_MAP[result[0]]
    return name


def abbrev_to_full_name(abbrev: str) -> str:
    return TEAM_ABBREV_TO_FULL.get(abbrev.upper(), abbrev)
