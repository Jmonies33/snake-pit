#!/usr/bin/env python3
"""rosters.txt (innerText of rtsports report-rosters.php) -> rosters.json"""
import json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
lines = [l.strip() for l in open(os.path.join(HERE, 'rosters.txt')) if l.strip()]
POS = {'QB', 'RB', 'WR', 'TE', 'K', 'D/ST'}
teams, cur = [], None
for i, l in enumerate(lines):
    if re.search(r' \d+-\d+$', l) and i > 0 and lines[i-1] not in POS and not re.match(r'^Bye', lines[i-1]):
        cur = {'team': lines[i-1], 'owner': re.sub(r' \d+-\d+$', '', l), 'players': []}; teams.append(cur); continue
    if cur and l in POS and i + 3 < len(lines) and re.match(r'^Bye \d+$', lines[i+3]):
        st = lines[i+5] if i + 5 < len(lines) else ''
        m = re.match(r'^(?:Starter|Bench|Reserve)\s+(\S+) .* ([\d.]+)$', st)
        cur['players'].append({'pos': 'DST' if l == 'D/ST' else l, 'name': lines[i+1], 'team': lines[i+2],
                               'bye': int(lines[i+3][4:]), 'inj': (m.group(1) if m and m.group(1) != '-' else ''),
                               'wk1': float(m.group(2)) if m else None})
teams = [t for t in teams if t['players']]
json.dump({'teams': teams}, open(os.path.join(HERE, 'rosters.json'), 'w'), indent=0)
print(f"{len(teams)} teams, {sum(len(t['players']) for t in teams)} players")
for t in teams: print(f"  {t['team']:28} {t['owner']:22} {len(t['players'])}")
assert len(teams) >= 10, 'roster parse looks broken'
