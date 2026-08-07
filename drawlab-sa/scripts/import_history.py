#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "historical-results.json"
RULE_CHANGE_DATE = date(2026, 6, 1)
TIMEOUT = (6, 18)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DrawLabSA-History/2.0; +https://mr-meow-za.github.io/yeet/drawlab-sa/)"
}
GAMES = {
    "Daily Lotto": {
        "archive": "https://za.national-lottery.com/daily-lotto/results/{year}-archive",
        "count": 5,
        "max": 36,
        "weekdays": set(range(7)),
    },
    "Lotto": {
        "archive": "https://za.national-lottery.com/lotto/results/{year}-archive",
        "count": 6,
        "max": 52,
        "legacy_max": 58,
        "weekdays": {2, 5},
    },
    "PowerBall": {
        "archive": "https://za.national-lottery.com/powerball/results/{year}-archive",
        "count": 5,
        "max": 50,
        "bonus_max": 16,
        "legacy_bonus_max": 20,
        "weekdays": {1, 4},
    },
}
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def load_state():
    if OUT.exists():
        try:
            return json.loads(OUT.read_text())
        except Exception:
            pass
    return {
        "schema_version": 2,
        "updated_at": None,
        "status": "initialising",
        "coverage": {},
        "quality": {},
        "results": [],
        "errors": [],
    }


def extract_date(text):
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso:
        return iso.group(1)
    match = re.search(rf"\b(\d{{1,2}})\s+({MONTHS})\s+(20\d{{2}})\b", text, re.I)
    if not match:
        return None
    return datetime.strptime(" ".join(match.groups()), "%d %B %Y").date().isoformat()


def draw_url(game, date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    slug = f"{dt.day:02d}-{dt.strftime('%B').lower()}-{dt.year}"
    if game == "PowerBall":
        return f"https://za.national-lottery.com/powerball/results/{slug}"
    path = "daily-lotto" if game == "Daily Lotto" else "lotto"
    return f"https://za.national-lottery.com/{path}/results/{slug}"


def element_numbers(element):
    numbers = []
    selectors = (
        "[data-number]",
        '[class*="ball"]',
        '[class*="number"]',
        "li",
    )
    for selector in selectors:
        found = []
        for node in element.select(selector):
            raw = node.get("data-number") or node.get_text(" ", strip=True)
            if re.fullmatch(r"\s*\d{1,2}\s*", raw or ""):
                found.append(int(raw))
        if found:
            numbers = found
            break
    return numbers


def limits_for_draw(game, date_str):
    draw_date = date.fromisoformat(date_str)
    if game == "Lotto":
        return (58 if draw_date < RULE_CHANGE_DATE else 52), None
    if game == "PowerBall":
        return 50, (20 if draw_date < RULE_CHANGE_DATE else 16)
    return 36, None


def rule_version(game, date_str):
    draw_date = date.fromisoformat(date_str)
    if game == "Lotto":
        return "legacy-6of58" if draw_date < RULE_CHANGE_DATE else "current-6of52"
    if game == "PowerBall":
        return "legacy-5of50-pb20" if draw_date < RULE_CHANGE_DATE else "current-5of50-pb16"
    return "5of36"


def build_row(game, date_str, sequence):
    spec = GAMES[game]
    required = spec["count"] + (1 if game in ("Lotto", "PowerBall") else 0)
    if len(sequence) < required:
        return None

    main_max, bonus_max = limits_for_draw(game, date_str)
    main = sequence[: spec["count"]]
    if len(set(main)) != spec["count"]:
        return None
    if any(not 1 <= number <= main_max for number in main):
        return None

    bonus = None
    if game == "Lotto":
        bonus = sequence[spec["count"]]
        if not 1 <= bonus <= main_max or bonus in main:
            return None
    elif game == "PowerBall":
        bonus = sequence[spec["count"]]
        if bonus_max is None or not 1 <= bonus <= bonus_max:
            return None

    return {
        "date": date_str,
        "game": game,
        "numbers": sorted(main),
        "bonus": bonus,
        "source": draw_url(game, date_str),
        "archive_source": GAMES[game]["archive"].format(year=date_str[:4]),
        "verified": True,
        "parser_version": "archive-v3-rule-aware",
        "rule_version": rule_version(game, date_str),
    }


def parse_table_rows(game, soup, year):
    rows = {}
    spec = GAMES[game]
    for table_row in soup.select("table tr"):
        cells = table_row.select("td")
        if len(cells) < 2:
            continue
        date_str = extract_date(cells[0].get_text(" ", strip=True))
        if not date_str or not date_str.startswith(str(year)):
            continue

        sequence = element_numbers(cells[1])
        if len(sequence) < spec["count"]:
            sequence = [int(x) for x in re.findall(r"\b\d{1,2}\b", cells[1].get_text(" ", strip=True))]
        row = build_row(game, date_str, sequence)
        if row:
            rows[date_str] = row
    return rows


def powerball_sequence(text):
    compact = re.sub(r"\s+", " ", text)
    match = re.search(
        r"\bPowerBall\b\s*:?[\s-]*((?:\d{1,2}[\s,]+){5}\d{1,2})(?=\s|$)",
        compact,
        re.I,
    )
    if not match:
        return []
    return [int(x) for x in re.findall(r"\d{1,2}", match.group(1))]


def parse_card_rows(game, soup, year):
    rows = {}
    selectors = "tr, article, section, li, [class*='result'], [class*='draw']"
    for container in soup.select(selectors):
        text = container.get_text(" ", strip=True)
        dates = set(
            match.group(0)
            for match in re.finditer(rf"\b\d{{1,2}}\s+({MONTHS})\s+20\d{{2}}\b", text, re.I)
        )
        if len(dates) != 1 or len(text) > 1200:
            continue
        date_str = extract_date(text)
        if not date_str or not date_str.startswith(str(year)):
            continue

        sequence = element_numbers(container)
        if game == "PowerBall":
            plain_sequence = powerball_sequence(text)
            if len(plain_sequence) >= 6:
                sequence = plain_sequence
        row = build_row(game, date_str, sequence)
        if row:
            rows[date_str] = row
    return rows


def parse_archive(game, html, year):
    soup = BeautifulSoup(html, "html.parser")
    rows = parse_table_rows(game, soup, year)
    if game == "PowerBall" or len(rows) < 10:
        rows.update(parse_card_rows(game, soup, year))
    return sorted(rows.values(), key=lambda row: row["date"], reverse=True)


def expected_draw_count(game, year):
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), date.today())
    if end < start:
        return 0
    weekdays = GAMES[game]["weekdays"]
    total = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() in weekdays:
            total += 1
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return total


def validate_dataset(game, year, rows):
    expected = expected_draw_count(game, year)
    lines = Counter(tuple(row["numbers"]) for row in rows)
    duplicate_max = max(lines.values(), default=0)
    unique_ratio = len(lines) / len(rows) if rows else 0.0
    bonus_complete = (
        sum(row.get("bonus") is not None for row in rows) / len(rows)
        if rows and game in ("Lotto", "PowerBall")
        else 1.0
    )
    minimum = max(1, int(expected * 0.65))
    valid = (
        len(rows) >= minimum
        and duplicate_max <= 2
        and unique_ratio >= 0.97
        and bonus_complete >= 0.90
    )
    return valid, {
        "expected": expected,
        "parsed": len(rows),
        "minimum": minimum,
        "unique_ratio": round(unique_ratio, 4),
        "largest_duplicate_group": duplicate_max,
        "bonus_completeness": round(bonus_complete, 4),
        "status": "accepted" if valid else "rejected",
    }


def previously_valid_rows(state, game, year):
    rows = [
        row
        for row in state.get("results", [])
        if row.get("game") == game and row.get("date", "").startswith(str(year))
    ]
    valid, _ = validate_dataset(game, year, rows)
    return rows if valid else []


def fetch_archive(game, year):
    url = GAMES[game]["archive"].format(year=year)
    response = SESSION.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return url, response.text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2024)
    parser.add_argument("--end-year", type=int, default=datetime.now().year)
    args = parser.parse_args()

    state = load_state()
    errors = []
    accepted_rows = []
    coverage = {}
    quality = {}

    outside_range = [
        row
        for row in state.get("results", [])
        if not (
            args.start_year <= int(row.get("date", "0000")[:4] or 0) <= args.end_year
        )
    ]
    accepted_rows.extend(outside_range)

    for game in GAMES:
        coverage[game] = {}
        quality[game] = {}
        for year in range(args.start_year, args.end_year + 1):
            try:
                archive_url, html = fetch_archive(game, year)
                rows = parse_archive(game, html, year)
                valid, report = validate_dataset(game, year, rows)
                report["archive"] = archive_url
                quality[game][str(year)] = report
                if valid:
                    accepted_rows.extend(rows)
                    coverage[game][str(year)] = len(rows)
                else:
                    previous = previously_valid_rows(state, game, year)
                    accepted_rows.extend(previous)
                    coverage[game][str(year)] = len(previous)
                    errors.append(
                        f"{game} {year}: rejected archive parse; parsed={len(rows)}, "
                        f"expected≈{report['expected']}, duplicates={report['largest_duplicate_group']}"
                    )
            except Exception as exc:
                previous = previously_valid_rows(state, game, year)
                accepted_rows.extend(previous)
                coverage[game][str(year)] = len(previous)
                quality[game][str(year)] = {
                    "status": "source-error",
                    "parsed": 0,
                    "preserved": len(previous),
                }
                errors.append(f"{game} {year}: {type(exc).__name__}: {exc}")

    dedup = {
        (row.get("date"), row.get("game")): row
        for row in accepted_rows
        if row.get("date") and row.get("game")
    }
    results = sorted(
        dedup.values(), key=lambda row: (row["date"], row["game"]), reverse=True
    )
    accepted_years = sum(
        1
        for game_reports in quality.values()
        for report in game_reports.values()
        if report.get("status") == "accepted"
    )
    state.update(
        {
            "schema_version": 2,
            "updated_at": datetime.now().astimezone().isoformat(),
            "status": "ok" if not errors else ("partial" if accepted_years else "unavailable"),
            "coverage": coverage,
            "quality": quality,
            "results": results,
            "errors": errors[:200],
        }
    )
    OUT.write_text(json.dumps(state, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": state["status"],
                "results": len(results),
                "coverage": coverage,
                "accepted_years": accepted_years,
                "errors": errors[:12],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
