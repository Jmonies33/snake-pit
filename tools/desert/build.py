#!/usr/bin/env python3
"""
Build the Desert League edge pages (trades + waivers) from:
  rosters.json      every team's roster, scraped from rtsports (collect.py)
  projections.json  ESPN projections scored under the league's real rules
  ../desert-players.json   pre-draft pool (for ADP = what the league THINKS a player is worth)
  ../desert-league.json    coachKeyHash (same master key as the draft room)

    python3 build.py            -> ../../desert/trades.html, ../../desert/waivers.html
"""
import json, os, re, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
OUT = os.path.join(REPO, 'desert')
ME = 'Jerry Asencio'
ALIASES = {'andresborregales': 'andyborregales', 'devonachane': 'devonachane', 'djmoore': 'djmoore',
           'dkmetcalf': 'dkmetcalf'}

def slug(s):
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', s.lower())
    return re.sub(r'[^a-z]', '', s)

def key(pos, name, team):
    k = ('DST-' + team) if pos == 'DST' else slug(name)
    return ALIASES.get(k, k)

proj = json.load(open(os.path.join(HERE, 'projections.json')))
rost = json.load(open(os.path.join(HERE, 'rosters.json')))
adp_pool = json.load(open(os.path.join(TOOLS, 'desert-players.json')))['players']
league = json.load(open(os.path.join(TOOLS, 'desert-league.json')))

adp = {}
for p in adp_pool:
    adp.setdefault(key(p['pos'], p['name'], p['team']), p['adp'])

# ---- player table: everyone with a projection, plus rostered players ESPN lacks
players, byKey = [], {}
def add_player(p):
    k = key(p['pos'], p['name'], p['team'])
    if k in byKey: return byKey[k]
    e = {'id': f"{p['pos']}-{k}", 'k': k, 'name': p['name'], 'pos': p['pos'], 'team': p['team'],
         'bye': p.get('bye', 0), 'pts': p.get('pts', 0), 'season': p.get('season', 0),
         'week': p.get('week', 0), 'inj': p.get('inj', ''), 'own': p.get('pctOwn', 0),
         'adp': adp.get(k, 9999), 'stats': p.get('stats', {})}
    byKey[k] = e; players.append(e); return e
for p in proj['players']:
    add_player(p)

teams = []
weeks_left = proj['weeksLeft']
for t in rost['teams']:
    ids = []
    for p in t['players']:
        k = key(p['pos'], p['name'], p['team'])
        if k in byKey:
            e = byKey[k]
            if not e['bye'] and p.get('bye'): e['bye'] = p['bye']
            if p.get('inj') and not e['inj']: e['inj'] = p['inj']
            e['rts'] = p.get('wk1')     # what the other owners see on rtsports (this week's projection)
        else:
            # no ESPN line — estimate rest-of-season from RTS's own week projection
            wk = p.get('wk1') or 0
            e = add_player({'name': p['name'], 'pos': p['pos'], 'team': p['team'], 'bye': p.get('bye', 0),
                            'pts': round(wk * weeks_left, 1), 'season': round(wk * 18, 1), 'week': wk,
                            'inj': p.get('inj', ''), 'noproj': True})
            e['noproj'] = True; e['rts'] = wk
        ids.append(e['id'])
    teams.append({'name': t['team'], 'owner': t['owner'], 'me': t['owner'] == ME, 'roster': ids})
assert sum(t['me'] for t in teams) == 1, 'could not find my team'

data = {'built': datetime.datetime.now().strftime('%b %-d, %Y %-I:%M %p'),
        'projDate': proj['date'], 'week': proj['week'], 'weeksLeft': weeks_left,
        'rules': {'roster': 20, 'start': 18, 'caps': {'QB': 4, 'RB': 6, 'WR': 9, 'TE': 9, 'K': 3, 'DST': 3}},
        'coachKeyHash': league.get('coachKeyHash', ''),
        'warRoom': 'https://jmonies33.github.io/snake-pit/?room=jerry-2026&team=10',
        'players': players, 'teams': teams}

tpl = open(os.path.join(HERE, 'edge.template.html')).read()
logo = open(os.path.join(TOOLS, 'rts-logo.svg')).read() if os.path.exists(os.path.join(TOOLS, 'rts-logo.svg')) else ''
os.makedirs(OUT, exist_ok=True)
for page in ('trades', 'waivers'):
    html = (tpl.replace('__PAGE__', page)
               .replace('__DATA__', json.dumps(data, separators=(',', ':')).replace('</', '<\\/'))
               .replace('__LOGO__', logo))
    with open(os.path.join(OUT, page + '.html'), 'w') as f:
        f.write(html)
    print(f'wrote desert/{page}.html ({len(html)//1024} KB)')
sp = open(os.path.join(HERE, 'speed.template.html')).read()
with open(os.path.join(OUT, 'speed.html'), 'w') as f:
    f.write(sp.replace('__HASH__', data['coachKeyHash']).replace('__LOGO__', logo))
print('wrote desert/speed.html')
print(f"{len(players)} players, {len(teams)} teams, week {proj['week']}, {weeks_left} weeks left")
