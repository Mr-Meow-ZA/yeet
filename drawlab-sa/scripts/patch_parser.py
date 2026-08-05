from pathlib import Path
import re

path = Path('drawlab-sa/scripts/update_cloud.py')
text = path.read_text()
replacement = '''def parse_payouts(game, html):
    soup = BeautifulSoup(html, "html.parser")
    payouts = {}
    for tr in soup.select("table tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.select("th,td")]
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

'''
text2, count = re.subn(r'def parse_payouts\(game, html\):.*?(?=def fetch_payouts)', replacement, text, flags=re.S)
if count != 1:
    raise SystemExit(f'Expected one parse_payouts function, found {count}')
path.write_text(text2)
print('Parser patched')
