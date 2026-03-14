"""
Name normalization utilities.
Handles mismatches between player names across data sources.
"""

import re
import unicodedata
from typing import Optional
from fuzzywuzzy import fuzz, process

# ── Manual overrides ──────────────────────────────────────────────────────────
# Keys: lowercase, no punctuation, no hyphens
# Values: canonical form as it appears in NBA Stats API
NAME_OVERRIDES = {
    # Generational suffixes
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
    "scotty pippen":              "Scotty Pippen Jr.",
    "scotty pippen jr":           "Scotty Pippen Jr.",
    "walter clayton":             "Walter Clayton Jr.",
    "walter clayton jr":          "Walter Clayton Jr.",
    "otto porter":                "Otto Porter Jr.",
    "otto porter jr":             "Otto Porter Jr.",
    "dereck lively":              "Dereck Lively II",
    "dereck lively ii":           "Dereck Lively II",

    # Internal capitals — capitalize() breaks these
    "daron holmes":               "DaRon Holmes II",
    "daron holmes ii":            "DaRon Holmes II",
    "day ron sharpe":             "Day'Ron Sharpe",
    "dayron sharpe":              "Day'Ron Sharpe",

    # Initials
    "kj simpson":                 "KJ Simpson",
    "pj hall":                    "PJ Hall",
    "pj washington":              "PJ Washington",
    "aj green":                   "AJ Green",
    "tj warren":                  "T.J. Warren",
    "cj mccollum":                "CJ McCollum",
    "cj mccollum":                "CJ McCollum",

    # Aliases and short forms
    "nicolas claxton":            "Nic Claxton",
    "nic claxton":                "Nic Claxton",
    "marcus morris sr":           "Marcus Morris Sr.",
    "jimmy butler":               "Jimmy Butler",
    "jimmy butler iii":           "Jimmy Butler",
    "jaesean tate":               "Jae'Sean Tate",
    "jaeseantate":                "Jae'Sean Tate",

    # Accented names
    "giannis antetokounmpo":      "Giannis Antetokounmpo",
    "nikola jokic":               "Nikola Jokic",
    "nikola jokic":               "Nikola Jokic",
    "luka doncic":                "Luka Doncic",
    "bojan bogdanovic":           "Bojan Bogdanovic",
    "bogdan bogdanovic":          "Bogdan Bogdanovic",
    "kristaps porzingis":         "Kristaps Porzingis",
    "dario saric":                "Dario Saric",

    # European names stored differently
    "maxi kleber":                "Maxi Kleber",
    "tidjane salaun":             "Tidjane Salaun",
    "santi aldama":               "Santi Aldama",
    "noa essengue":               "Noa Essengue",
    "moussa cisse":               "Moussa Cisse",
    "egor demin":                 "Egor Demin",

    # Traded players / name stored under different team
    "terry rozier":               "Terry Rozier",
    "terry rozier iii":           "Terry Rozier",

    # Rookies and recent signings
    "zach edey":                  "Zach Edey",
    "asa newell":                 "Asa Newell",
    "kyshawn george":             "Kyshawn George",
    "collin murray-boyles":       "Collin Murray-Boyles",
    "collin murrayboyles":        "Collin Murray-Boyles",
    "kentavious caldwell-pope":   "Kentavious Caldwell-Pope",
    "kentavious caldwellpope":    "Kentavious Caldwell-Pope",

    # G League / two-way (no NBA stats — kept so lookup returns None quickly)
    # Don't add these — let them fail naturally and get the 0.02 default
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
    Capitalize a single name part correctly, handling:
    - 2-letter initials: KJ, PJ → keep uppercase
    - Roman numerals: II, III → keep uppercase
    - Hyphenated names: Caldwell-Pope → capitalize each segment
    - Apostrophe names: Jae'Sean → capitalize after apostrophe
    - Jr./Sr. → capitalize with period
    """
    upper = part.upper().rstrip(".")

    if upper in ("II", "III", "IV", "V", "VI"):
        return upper
    if upper in ("JR", "SR"):
        return upper.capitalize() + "."

    # 2-letter uppercase initials (KJ, PJ, AJ, etc.)
    if len(part) == 2 and part.isalpha() and part.isupper():
        return part.upper()

    if "-" in part:
        return "-".join(_capitalize_part(seg) for seg in part.split("-"))

    if "'" in part:
        return "'".join(seg.capitalize() for seg in part.split("'"))

    return part.capitalize()


def normalize_player_name(name: str) -> str:
    """
    Normalize a player name for matching.
    Strips accents, handles suffixes, applies overrides.
    """
    if not name:
        return ""

    name = strip_accents(name.strip())

    # Build lookup key: lowercase, no punctuation
    key = name.lower()
    key = re.sub(r"[.'`]", "", key)
    key = re.sub(r"\s+", " ", key).strip()

    if key in NAME_OVERRIDES:
        return NAME_OVERRIDES[key]

    key_no_hyphen = key.replace("-", "")
    if key_no_hyphen in NAME_OVERRIDES:
        return NAME_OVERRIDES[key_no_hyphen]

    parts = name.split()
    return " ".join(_capitalize_part(p) for p in parts)


def fuzzy_match_player(
    name: str,
    candidates: list,
    threshold: int = 70,
    log_failures: bool = False,
) -> Optional[str]:
    """
    Fuzzy-match a player name against a list of known names.
    Runs 3 passes with progressively looser matching:
      Pass 1: full normalized name, threshold 70
      Pass 2: suffix-stripped name, threshold 70
      Pass 3: last-name-only match, threshold 85 (conservative)
    """
    if not candidates:
        return None

    normalized_input = normalize_player_name(name)

    # Build normalized candidate map
    norm_map = {}
    for c in candidates:
        nc = normalize_player_name(c)
        norm_map[nc] = c

    # Pass 1: exact normalized match
    if normalized_input in norm_map:
        return norm_map[normalized_input]

    # Pass 1b: fuzzy full name
    result = process.extractOne(
        normalized_input, list(norm_map.keys()), scorer=fuzz.token_sort_ratio
    )
    if result and result[1] >= threshold:
        return norm_map[result[0]]

    # Pass 2: strip suffixes (Jr., III, II etc.) from both sides
    stripped_input = re.sub(
        r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", normalized_input, flags=re.IGNORECASE
    ).strip()

    if stripped_input != normalized_input:
        # Try against stripped candidates
        stripped_map = {
            re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv|v)$", "", k, flags=re.IGNORECASE).strip(): v
            for k, v in norm_map.items()
        }
        result2 = process.extractOne(
            stripped_input, list(stripped_map.keys()), scorer=fuzz.token_sort_ratio
        )
        if result2 and result2[1] >= threshold:
            return stripped_map[result2[0]]

    # Pass 3: last-name-only match (high threshold to avoid false positives)
    # e.g. "Giannis Antetokounmpo" last name is very distinctive
    name_parts = normalized_input.split()
    if len(name_parts) >= 2:
        last_name = name_parts[-1]
        if len(last_name) >= 5:  # only for long surnames to avoid "James" matching wrong
            for candidate_norm, candidate_orig in norm_map.items():
                cand_parts = candidate_norm.split()
                if cand_parts and fuzz.ratio(last_name.lower(), cand_parts[-1].lower()) >= 90:
                    # Verify first name also somewhat matches
                    if len(name_parts) >= 1 and len(cand_parts) >= 1:
                        first_match = fuzz.ratio(name_parts[0].lower(), cand_parts[0].lower())
                        if first_match >= 60:
                            return candidate_orig

    if log_failures:
        # Log top candidates to help debug
        top = process.extract(
            normalized_input, list(norm_map.keys()),
            scorer=fuzz.token_sort_ratio, limit=3
        )
        import logging
        logging.getLogger(__name__).debug(
            f"No match for '{normalized_input}' — top candidates: {top}"
        )

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
