#!/usr/bin/env python3
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "cloud-state.json"
HISTORY_PATH = ROOT / "data" / "historical-results.json"
TZ = ZoneInfo("Africa/Johannesburg")
NOW = datetime.now(TZ)
TODAY = NOW.date().isoformat()
ENTRY_CUTOFF_HOUR = 20
HTTP_TIMEOUT = (5, 9)

RULES = {
    "Daily Lotto": {"count": 5, "max": 36, "days": set(range(7)), "cost": 3},
    "Lotto": {"count": 6, "max": 52, "days": {2, 5}, "cost": 5},
    "PowerBall": {"count": 5, "max": 50, "days": {1, 4}, "bonus_max": 16, "cost": 5},
}
SOURCES = {
    "Daily Lotto": [
        "https://za.national-lottery.com/daily-lotto/results",
        "https://www.lottery.co.za/daily-lotto/results",
    ],
    "Lotto": [
        "https://za.national-lottery.com/lotto/results",
        "https://www.lottery.co.za/lotto/results",
    ],
    "PowerBall": [
        "https://www.powerball.net/southafrica/results",
        "https://za.national-lottery.com/powerball/results",
    ],
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DrawLabSA/3.1; +https://mr-meow-za.github.io/yeet/drawlab-sa/)"
}

STRATEGIES = {
    "Hot 6M": {
        "version": "1.0",
        "hypothesis": "Recent high-frequency numbers persist.",
    },
    "Weighted Historical": {
        "version": "1.0",
        "hypothesis": "A fixed blend of long-term, six-month, momentum and gap signals performs best.",
    },
    "Cold 6M": {
        "version": "1.0",
        "hypothesis": "Recently underrepresented numbers revert toward expected frequency.",
    },
    "Diversified Coverage": {
        "version": "1.0",
        "hypothesis": "Structured range coverage with low overlap diversifies the portfolio.",
    },
}

FALLBACK = {
    "Daily Lotto": {"2": 5.00, "3": 19.00, "4": 330.00, "5": 400000.00},
    "Lotto": {
        "3": 20.00,
        "2+B": 30.00,
        "3+B": 200.00,
        "4": 200.00,
        "4+B": 4000.00,
        "5": 45000.00,
        "5+B": 500000.00,
        "6": 5000000.00,
    },
    "PowerBall": {
        "0+PB": 10.00,
        "1+PB": 20.00,
        "2+PB": 100.00,
        "3": 100.00,
        "3+PB": 500.00,
        "4": 2000.00,
        "4+PB": 25000.00,
        "5": 350000.00,
        "5+PB": 5000000.00,
    },
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
_HISTORY_CACHE = None
_HISTORY_QUALITY = None


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {
        "updated_at": None,
        "status": "initialising",
        "virtual": {"starting_bankroll": 1000, "costs": {}, "tickets": []},
        "results": [],
        "errors": [],
    }


def save_state(state):
    state["updated_at"] = NOW.isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=False) + "\n")


def games_for_date(dt):
    return [game for game, rule in RULES.items() if dt.weekday() in rule["days"]]


def valid_history_row(row, game):
    rule = RULES[game]
    numbers = row.get("numbers")
    if not isinstance(numbers, list) or len(numbers) != rule["count"]:
        return False
    if len(set(numbers)) != len(numbers):
        return False
    if any(not isinstance(n, int) or not 1 <= n <= rule["max"] for n in numbers):
        return False
    try:
        datetime.fromisoformat(row.get("date", ""))
    except (TypeError, ValueError):
        return False
    if game == "PowerBall":
        bonus = row.get("bonus")
        if not isinstance(bonus, int) or not 1 <= bonus <= rule["bonus_max"]:
            return False
    return True


def load_valid_history():
    global _HISTORY_CACHE, _HISTORY_QUALITY
    if _HISTORY_CACHE is not None:
        return _HISTORY_CACHE

    accepted = []
    quality = {}
    raw_rows = []
    if HISTORY_PATH.exists():
        try:
            raw_rows = json.loads(HISTORY_PATH.read_text()).get("results", [])
        except Exception:
            raw_rows = []

    for game in RULES:
        candidate = [row for row in raw_rows if row.get("game") == game and valid_history_row(row, game)]
        line_counts = Counter(tuple(row["numbers"]) for row in candidate)
        bad_lines = {line for line, count in line_counts.items() if count > 2}
        clean = [row for row in candidate if tuple(row["numbers"]) not in bad_lines]
        accepted.extend(clean)
        quality[game] = {
            "raw": sum(1 for row in raw_rows if row.get("game") == game),
            "accepted": len(clean),
            "rejected": sum(1 for row in raw_rows if row.get("game") == game) - len(clean),
            "status": "usable" if clean else "unavailable",
        }

    _HISTORY_CACHE = accepted
    _HISTORY_QUALITY = quality
    return accepted


def historical_results(state, game):
    rows = [
        row
        for row in state.get("results", [])
        if row.get("game") == game and valid_history_row(row, game)
    ]
    rows.extend(row for row in load_valid_history() if row.get("game") == game)
    dedup = {(row.get("date"), row.get("game")): row for row in rows}
    return sorted(dedup.values(), key=lambda row: row["date"], reverse=True)


def counts_for_window(rows, days=None, draw_limit=None):
    selected = rows
    if days is not None:
        cutoff = NOW.date() - timedelta(days=days)
        selected = [row for row in rows if datetime.fromisoformat(row["date"]).date() >= cutoff]
    if draw_limit is not None:
        selected = selected[:draw_limit]
    return Counter(n for row in selected for n in row.get("numbers", []))


def draw_gaps(rows, maximum):
    gaps = {n: len(rows) + 1 for n in range(1, maximum + 1)}
    for index, row in enumerate(rows):
        for n in row.get("numbers", []):
            if gaps[n] == len(rows) + 1:
                gaps[n] = index
    return gaps


def normalise(values):
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {key: 0.5 for key in values}
    return {key: (value - lo) / (hi - lo) for key, value in values.items()}


def valid_add(picked, number):
    trial = sorted(picked + [number])
    return not any(
        trial[i] + 1 == trial[i + 1] and trial[i + 1] + 1 == trial[i + 2]
        for i in range(len(trial) - 2)
    )


def select_spread(ranked, count, maximum, avoid=None):
    avoid = avoid or []
    zones = [
        (int(i * maximum / count) + 1, int((i + 1) * maximum / count))
        for i in range(count)
    ]
    picked = []
    rank_position = {number: index for index, number in enumerate(ranked)}
    for lo, hi in zones:
        options = [
            number
            for number in ranked
            if lo <= number <= hi and number not in picked and valid_add(picked, number)
        ]
        if avoid:
            options.sort(
                key=lambda number: (
                    sum(number in line for line in avoid),
                    rank_position[number],
                    number,
                )
            )
        if options:
            picked.append(options[0])
    for number in ranked:
        if len(picked) >= count:
            break
        if number not in picked and valid_add(picked, number):
            picked.append(number)
    return sorted(picked[:count])


def bonus_number(rows, strategy, maximum):
    counts = Counter(
        row.get("bonus")
        for row in rows
        if isinstance(row.get("bonus"), int) and 1 <= row["bonus"] <= maximum
    )
    gaps = {n: len(rows) + 1 for n in range(1, maximum + 1)}
    for index, row in enumerate(rows):
        bonus = row.get("bonus")
        if isinstance(bonus, int) and 1 <= bonus <= maximum and gaps[bonus] == len(rows) + 1:
            gaps[bonus] = index
    numbers = list(range(1, maximum + 1))
    if strategy == "Hot 6M":
        return min(numbers, key=lambda n: (-counts[n], n))
    if strategy == "Cold 6M":
        return min(numbers, key=lambda n: (counts[n], -gaps[n], n))
    if strategy == "Weighted Historical":
        return min(numbers, key=lambda n: (-(counts[n] * 2 + gaps[n] * 0.15), n))
    return min(numbers, key=lambda n: (counts[n], n))


def make_line(state, game, strategy, avoid=None):
    rule = RULES[game]
    rows = historical_results(state, game)
    all_numbers = list(range(1, rule["max"] + 1))
    long_counts = counts_for_window(rows)
    six_month_counts = counts_for_window(rows, days=183)
    three_month_counts = counts_for_window(rows, days=92)
    recent_counts = counts_for_window(rows, draw_limit=10)
    gaps = draw_gaps(rows, rule["max"])

    if strategy == "Hot 6M":
        ranked = sorted(
            all_numbers,
            key=lambda n: (-six_month_counts[n], -three_month_counts[n], -recent_counts[n], n),
        )
    elif strategy == "Cold 6M":
        ranked = sorted(
            all_numbers,
            key=lambda n: (six_month_counts[n], -gaps[n], three_month_counts[n], n),
        )
    elif strategy == "Weighted Historical":
        nl = normalise({n: long_counts[n] for n in all_numbers})
        n6 = normalise({n: six_month_counts[n] for n in all_numbers})
        nr = normalise({n: recent_counts[n] for n in all_numbers})
        ng = normalise(gaps)
        scores = {
            n: (
                0.30 * nl.get(n, 0)
                + 0.25 * n6.get(n, 0)
                + 0.15 * nr.get(n, 0)
                + 0.15 * ng.get(n, 0)
                + 0.15 * (1 - abs((n / (rule["max"] + 1)) - 0.5) * 2)
            )
            for n in all_numbers
        }
        ranked = sorted(all_numbers, key=lambda n: (-scores[n], -six_month_counts[n], n))
    else:
        popularity = {n: six_month_counts[n] + recent_counts[n] for n in all_numbers}
        ranked = sorted(
            all_numbers,
            key=lambda n: (sum(n in line for line in (avoid or [])), popularity[n], n),
        )

    picked = select_spread(
        ranked,
        rule["count"],
        rule["max"],
        avoid if strategy == "Diversified Coverage" else None,
    )
    bonus = (
        bonus_number(rows, strategy, rule["bonus_max"])
        if game == "PowerBall"
        else None
    )
    return picked, bonus


def ensure_virtual_entries(state):
    tickets = state.setdefault("virtual", {}).setdefault("tickets", [])
    costs = state["virtual"].setdefault("costs", {})
    state["strategy_catalog"] = STRATEGIES

    if NOW.hour >= ENTRY_CUTOFF_HOUR:
        return

    order = ("Hot 6M", "Weighted Historical", "Cold 6M", "Diversified Coverage")
    for game in games_for_date(NOW.date()):
        if any(
            row.get("date") == TODAY and row.get("game") == game
            for row in state.get("results", [])
        ):
            continue
        costs.setdefault(game, RULES[game]["cost"])
        generated = []
        for strategy in order:
            version = STRATEGIES[strategy]["version"]
            ticket_id = f"{TODAY}|{game}|{strategy}|v{version}"
            existing = next((ticket for ticket in tickets if ticket.get("id") == ticket_id), None)
            if existing:
                generated.append(existing.get("numbers", []))
                continue
            numbers, bonus = make_line(state, game, strategy, generated)
            generated.append(numbers)
            tickets.append(
                {
                    "id": ticket_id,
                    "date": TODAY,
                    "game": game,
                    "strategy": strategy,
                    "strategy_version": version,
                    "strategy_hypothesis": STRATEGIES[strategy]["hypothesis"],
                    "deterministic": True,
                    "numbers": numbers,
                    "bonus": bonus,
                    "cost": float(costs[game]),
                    "won": 0,
                    "payout_type": None,
                    "status": "Pending result",
                    "created_at": NOW.isoformat(),
                }
            )


def extract_date(text):
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso:
        return iso.group(1)
    months = (
        "January|February|March|April|May|June|July|August|September|October|"
        "November|December"
    )
    match = re.search(rf"\b(\d{{1,2}})\s+({months})\s+(20\d{{2}})\b", text, re.I)
    if match:
        return datetime.strptime(" ".join(match.groups()), "%d %B %Y").date().isoformat()
    return None


def money_value(text):
    if not text:
        return None
    match = re.search(r"R\s*([\d,]+(?:\.\d+)?)", text.replace("\xa0", " "), re.I)
    return float(match.group(1).replace(",", "")) if match else None


def number_sequence_from_dom(soup, count):
    for selector in ("[data-number]", '[class*="ball"]', '[class*="number"]'):
        sequence = []
        for element in soup.select(selector):
            text = element.get("data-number") or element.get_text(" ", strip=True)
            if re.fullmatch(r"\s*\d{1,2}\s*", text or ""):
                sequence.append(int(text))
        if len(sequence) >= count:
            return sequence
    return []


def parse_result_html(game, html, url):
    soup = BeautifulSoup(html, "html.parser")
    raw = soup.get_text(" ", strip=True)
    draw_date = extract_date(raw)
    candidates = []
    for pattern in (
        r'"(?:winningNumbers|mainNumbers|numbers)"\s*:\s*\[([^\]]+)\]',
        r'"balls"\s*:\s*\[([^\]]+)\]',
    ):
        for hit in re.findall(pattern, html, re.I):
            candidates.append([int(x) for x in re.findall(r"\b\d{1,2}\b", hit)])
    dom = number_sequence_from_dom(soup, RULES[game]["count"])
    if dom:
        candidates.insert(0, dom)

    rule = RULES[game]
    for candidate in candidates:
        unique = []
        for number in candidate:
            if 1 <= number <= rule["max"] and number not in unique:
                unique.append(number)
        if len(unique) < rule["count"]:
            continue
        main = sorted(unique[: rule["count"]])
        rest = candidate[rule["count"] :]
        bonus = None
        if game == "PowerBall":
            bonus = next((n for n in rest if 1 <= n <= rule["bonus_max"]), None)
        elif game == "Lotto":
            bonus = next((n for n in rest if 1 <= n <= rule["max"] and n not in main), None)
        if draw_date:
            return {
                "date": draw_date,
                "game": game,
                "numbers": main,
                "bonus": bonus,
                "source": url,
            }
    return None


def fetch_latest_result(game):
    errors = []
    for url in SOURCES[game]:
        try:
            response = SESSION.get(url, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            parsed = parse_result_html(game, response.text, url)
            if parsed and parsed.get("date"):
                return parsed, errors
            errors.append(f"{game}: could not parse {url}")
        except Exception as exc:
            errors.append(f"{game}: {url}: {type(exc).__name__}: {exc}")
    return None, errors


def date_slug(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.day:02d}-{dt.strftime('%B').lower()}-{dt.year}"


def payout_url(result):
    date = result["date"]
    if result["game"] == "Daily Lotto":
        return f"https://za.national-lottery.com/daily-lotto/results/{date_slug(date)}"
    if result["game"] == "Lotto":
        return f"https://za.national-lottery.com/lotto/results/{date_slug(date)}"
    return f"https://www.powerball.net/southafrica/results/{date}"


def canonical_match(game, label):
    text = (
        re.sub(r"\s+", " ", label.strip().lower())
        .replace("powerball", "pb")
        .replace("bonus ball", "bonus")
    )
    numbers = [int(x) for x in re.findall(r"\d+", text)]
    matched = numbers[0] if numbers else None
    if matched is None:
        return None
    if game == "Daily Lotto":
        return str(matched) if 2 <= matched <= 5 else None
    if game == "PowerBall":
        return f"{matched}+PB" if "pb" in text and 0 <= matched <= 5 else (str(matched) if 0 <= matched <= 5 else None)
    if game == "Lotto":
        return f"{matched}+B" if "bonus" in text and 2 <= matched <= 6 else (str(matched) if 2 <= matched <= 6 else None)
    return None


def parse_payouts(game, html):
    soup = BeautifulSoup(html, "html.parser")
    payouts = {}
    for row in soup.select("table tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        if game in ("Daily Lotto", "Lotto"):
            if len(cells) < 3:
                continue
            key = canonical_match(game, cells[1])
            amount = money_value(cells[2])
        else:
            if len(cells) < 2:
                continue
            key = canonical_match(game, cells[0])
            amount = money_value(cells[1])
        if key and amount is not None:
            payouts[key] = amount
    return payouts


def fetch_payouts(result):
    url = payout_url(result)
    try:
        response = SESSION.get(url, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        payouts = parse_payouts(result["game"], response.text)
        if payouts:
            return payouts, "exact", url, None
        return FALLBACK[result["game"]], "estimated", url, f"No payout table parsed at {url}"
    except Exception as exc:
        return FALLBACK[result["game"]], "estimated", url, f"{type(exc).__name__}: {exc}"


def merge_result(state, incoming):
    key = (incoming["date"], incoming["game"])
    for existing in state.setdefault("results", []):
        if (existing.get("date"), existing.get("game")) != key:
            continue
        if existing.get("payout_type") == "exact" and incoming.get("payout_type") != "exact":
            incoming["payouts"] = existing.get("payouts", {})
            incoming["payout_type"] = "exact"
            incoming["payout_source"] = existing.get("payout_source")
        existing.update(incoming)
        return existing
    state["results"].append(incoming)
    return incoming


def result_key(game, matches, powerball_match=False, bonus_match=False):
    if game == "Daily Lotto":
        return str(matches)
    if game == "PowerBall":
        return f"{matches}+PB" if powerball_match else str(matches)
    return f"{matches}+B" if bonus_match else str(matches)


def settle(state):
    result_map = {
        (result.get("date"), result.get("game")): result
        for result in state.get("results", [])
    }
    for ticket in state.get("virtual", {}).get("tickets", []):
        result = result_map.get((ticket.get("date"), ticket.get("game")))
        if not result:
            continue
        matches = len(set(ticket.get("numbers", [])) & set(result.get("numbers", [])))
        powerball_match = (
            ticket.get("game") == "PowerBall"
            and ticket.get("bonus") is not None
            and ticket.get("bonus") == result.get("bonus")
        )
        bonus_match = (
            ticket.get("game") == "Lotto"
            and result.get("bonus") is not None
            and result.get("bonus") in ticket.get("numbers", [])
        )
        key = result_key(ticket["game"], matches, powerball_match, bonus_match)
        payout = float(result.get("payouts", {}).get(key, 0))
        ticket.update(
            {
                "matches": matches,
                "pb_match": powerball_match,
                "bonus_match": bonus_match,
                "prize_key": key,
                "won": payout,
                "payout_type": result.get("payout_type", "estimated"),
                "payout_source": result.get("payout_source"),
                "status": "Settled",
                "settled_at": NOW.isoformat(),
            }
        )


def recent_enough(date_str, days=14):
    try:
        return datetime.fromisoformat(date_str).date() >= NOW.date() - timedelta(days=days)
    except (TypeError, ValueError):
        return False


def main():
    state = load_state()
    state["errors"] = []
    state["strategy_catalog"] = STRATEGIES
    load_valid_history()
    state["history_quality"] = _HISTORY_QUALITY

    ensure_virtual_entries(state)

    for game in RULES:
        result, errors = fetch_latest_result(game)
        state["errors"].extend(errors)
        if not result:
            continue
        existing = next(
            (
                row
                for row in state.get("results", [])
                if row.get("date") == result["date"] and row.get("game") == game
            ),
            None,
        )
        if existing and existing.get("payout_type") == "exact":
            result.update(
                {
                    "payouts": existing.get("payouts", {}),
                    "payout_type": "exact",
                    "payout_source": existing.get("payout_source"),
                }
            )
        else:
            payouts, payout_type, source, error = fetch_payouts(result)
            result.update(
                {"payouts": payouts, "payout_type": payout_type, "payout_source": source}
            )
            if error:
                state["errors"].append(f"{game} payout: {error}")
        merge_result(state, result)

    pending_exact = [
        result
        for result in state.get("results", [])
        if result.get("payout_type") != "exact" and recent_enough(result.get("date"))
    ][:3]
    for result in pending_exact:
        payouts, payout_type, source, error = fetch_payouts(result)
        if payout_type == "exact":
            result.update(
                {"payouts": payouts, "payout_type": payout_type, "payout_source": source}
            )
        elif error:
            state["errors"].append(
                f"{result.get('game')} {result.get('date')} payout: {error}"
            )

    settle(state)
    state["status"] = "ok" if not state["errors"] else "partial"
    state["results"] = sorted(
        state.get("results", []),
        key=lambda row: (row.get("date", ""), row.get("game", "")),
        reverse=True,
    )[:300]
    state["virtual"]["tickets"] = sorted(
        state["virtual"].get("tickets", []),
        key=lambda row: (row.get("date", ""), row.get("game", ""), row.get("strategy", "")),
        reverse=True,
    )[:3000]
    save_state(state)

    exact = sum(1 for row in state["results"] if row.get("payout_type") == "exact")
    estimated = sum(1 for row in state["results"] if row.get("payout_type") == "estimated")
    print(
        json.dumps(
            {
                "status": state["status"],
                "updated_at": state["updated_at"],
                "tickets": len(state["virtual"]["tickets"]),
                "results": len(state["results"]),
                "exact_payout_draws": exact,
                "estimated_payout_draws": estimated,
                "history_quality": state.get("history_quality"),
                "errors": state["errors"][:8],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
