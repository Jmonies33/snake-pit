#!/usr/bin/env python3
"""
Refresh both draft rooms with current data, rebuild, and (optionally) push.

    python3 tools/refresh.py [--no-push]

Data sources (both free; FFC explicitly allows commercial use, ESPN is a
personal-use read of their public fantasy projections endpoint):
  - Fantasy Football Calculator ADP, scraped daily (ppr for The Snakes' room,
    2qb for the Desert League room). ADP models the OPPONENTS, so each room
    gets the format its members actually draft off.
  - ESPN 2026 season stat-line projections (leaguedefaults endpoint, no auth).
    Stat lines are scored under each league's own rules — never rank-multiplied.
    ESPN keeps these current with injury news, which is the point of refreshing.

Sanity gates guard the push: if the fetched data looks broken (too few players,
elite anchors out of range), the script exits non-zero and leaves the site alone.
"""
import json, os, re, subprocess, sys, urllib.request, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PUSH = '--no-push' not in sys.argv

TEAM_ABBR = {1:'ATL',2:'BUF',3:'CHI',4:'CIN',5:'CLE',6:'DAL',7:'DEN',8:'DET',9:'GB',10:'TEN',
 11:'IND',12:'KC',13:'LV',14:'LAR',15:'MIA',16:'MIN',17:'NE',18:'NO',19:'NYG',20:'NYJ',
 21:'PHI',22:'ARI',23:'PIT',24:'LAC',25:'SF',26:'SEA',27:'TB',28:'WSH',29:'CAR',30:'JAX',33:'BAL',34:'HOU'}
POS = {1:'QB',2:'RB',3:'WR',4:'TE',5:'K',16:'DST'}
FFC_TEAM_FIX = {'JAC':'JAX','WAS':'WSH','LA':'LAR'}

def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def slug(s):
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', s.lower())
    return re.sub(r'[^a-z]', '', s)

def die(msg):
    print('SANITY FAIL: ' + msg); sys.exit(1)

# ---------------- fetch ----------------
today = str(datetime.date.today())
adp_ppr = fetch('https://fantasyfootballcalculator.com/api/v1/adp/ppr?teams=12&year=2026')
adp_2qb = fetch('https://fantasyfootballcalculator.com/api/v1/adp/2qb?teams=12&year=2026')
espn = fetch('https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leaguedefaults/3?view=kona_player_info',
             headers={'User-Agent':'Mozilla/5.0','Accept':'application/json',
                      'X-Fantasy-Filter':'{"players":{"limit":700,"sortDraftRanks":{"sortPriority":100,"sortAsc":true,"value":"PPR"}}}'})
if len(espn.get('players', [])) < 500: die(f"ESPN returned {len(espn.get('players',[]))} players")
for name, d in (('ppr', adp_ppr), ('2qb', adp_2qb)):
    if len(d.get('players', [])) < 150: die(f"FFC {name} returned {len(d.get('players',[]))} players")
adp_date = adp_ppr.get('meta', {}).get('end_date', today)

# bye map by team; FFC 'adp' is a round.pick float (e.g. 3.9) — convert each list
# to a clean 1..N overall ordering, which is all the market board needs.
byes, adp = {}, {'ppr': {}, '2qb': {}}
for d in (adp_ppr, adp_2qb):
    for p in d['players']:
        tm = FFC_TEAM_FIX.get(p.get('team'), p.get('team'))
        if p.get('bye'): byes[tm] = p['bye']
for kind, d in (('ppr', adp_ppr), ('2qb', adp_2qb)):
    ordered = sorted(d['players'], key=lambda p: float(p['adp']))
    m = {}
    for i, p in enumerate(ordered, 1):
        tm = FFC_TEAM_FIX.get(p.get('team'), p.get('team'))
        key = ('DST-' + tm) if p['position'] in ('DEF', 'DST') else slug(p['name'])
        m[key] = i
    adp[kind] = m

# ---------------- ESPN stat lines ----------------
def season_proj(pl):
    for s in pl.get('player', {}).get('stats', []):
        if s.get('statSourceId') == 1 and s.get('statSplitTypeId') == 0 and s.get('seasonId') == 2026:
            return s
    return None

rows = []
for pl in espn['players']:
    p = pl['player']
    pos = POS.get(p.get('defaultPositionId'))
    if not pos: continue
    s = season_proj(pl)
    if not s: continue
    st = {k: float(v) for k, v in (s.get('stats') or {}).items()}
    team = TEAM_ABBR.get(p.get('proTeamId'), 'FA')
    rows.append({'name': p['fullName'], 'pos': pos, 'team': team,
                 'bye': byes.get(team, 0), 'inj': p.get('injuryStatus', ''),
                 'passYd': st.get('3', 0), 'passTD': st.get('4', 0), 'int': st.get('20', 0),
                 'rushYd': st.get('24', 0), 'rushTD': st.get('25', 0),
                 'rec': st.get('53', 0), 'recYd': st.get('42', 0), 'recTD': st.get('43', 0),
                 'espnTotal': float(s.get('appliedTotal', 0))})

def compress(players, spread):
    """Scale a pool's totals so 1st-to-22nd spread matches a realistic preseason
    number — raw K/DST projections imply spreads no projection can support."""
    vals = sorted((p['base'] for p in players), reverse=True)
    if len(vals) < 23: return
    cur = vals[0] - vals[21]
    if cur <= 0: return
    mean = sum(vals) / len(vals)
    f = spread / cur
    for p in players:
        p['base'] = mean + (p['base'] - mean) * f

def build_pool(scoring):
    """scoring: 'desert' or 'snakes' -> players list with pts + adp."""
    out = []
    for r in rows:
        pos = r['pos']
        if pos in ('K', 'DST'):
            out.append({**r, 'base': r['espnTotal']})
            continue
        if scoring == 'desert':
            rec_by_pos = {'RB': 0.0, 'WR': 1.0, 'TE': 1.5}
            pts = (0.04 * r['passYd'] + 6 * r['passTD'] - 2 * r['int']
                   + 0.1 * r['rushYd'] + 6 * r['rushTD']
                   + 0.1 * r['recYd'] + 6 * r['recTD']
                   + rec_by_pos.get(pos, 0) * r['rec'])
        else:  # snakes: full PPR, 4-pt pass TD @ 0.05/yd, modeled game/long-TD bonuses
            pts = (0.05 * r['passYd'] + 4 * r['passTD'] - 2 * r['int']
                   + 0.1 * r['rushYd'] + 6 * r['rushTD']
                   + 0.1 * r['recYd'] + 6 * r['recTD'] + 1.0 * r['rec'])
            if pos == 'QB':
                pts += 26 * (r['passYd'] / 4400)                      # 40yd-TD + 300yd-game est.
            elif pos == 'RB':
                pts += 15 * (r['rushYd'] / 1400) ** 2 + 0.32 * (r['rushTD'] + r['recTD'])
            else:
                pts += 21 * (r['recYd'] / 1500) ** 2 + 0.6 * r['recTD']
        out.append({**r, 'base': pts})
    for pos, spread in (('K', 25), ('DST', 27 if scoring == 'desert' else 40)):
        compress([p for p in out if p['pos'] == pos], spread)
    kind = '2qb' if scoring == 'desert' else 'ppr'
    players = []
    for p in out:
        key = ('DST-' + p['team']) if p['pos'] == 'DST' else slug(p['name'])
        e = {'name': p['name'], 'pos': p['pos'], 'team': p['team'],
             'bye': p['bye'], 'pts': round(p['base'], 1),
             'adp': adp[kind].get(key, 9999)}
        # per-player stat line for the detail card (skill players only; K/DST
        # projections are single numbers, there is nothing to break out)
        if p['pos'] not in ('K', 'DST'):
            stt = {k: round(p[k]) for k in
                   ('passYd', 'passTD', 'int', 'rushYd', 'rushTD', 'rec', 'recYd', 'recTD')
                   if p.get(k, 0) >= 0.5}
            if stt: e['stats'] = stt
        if p.get('inj') and p['inj'] not in ('', 'ACTIVE'):
            e['inj'] = p['inj']
        players.append(e)
    players.sort(key=lambda p: (p['adp'], -p['pts']))
    return players

# ---------------- sanity ----------------
desert_pool = build_pool('desert')
snakes_pool = build_pool('snakes')
def anchor(pool, name):
    for p in pool:
        if slug(name) == slug(p['name']): return p['pts']
    return None
allen_d = anchor(desert_pool, 'Josh Allen')
chase_s = anchor(snakes_pool, "Ja'Marr Chase")
if not allen_d or not (330 <= allen_d <= 520): die(f'Josh Allen desert value {allen_d} out of range')
if not chase_s or not (250 <= chase_s <= 450): die(f'Chase snakes value {chase_s} out of range')
for pool, label in ((desert_pool, 'desert'), (snakes_pool, 'snakes')):
    from collections import Counter
    c = Counter(p['pos'] for p in pool)
    for pos, need in (('QB', 25), ('RB', 40), ('WR', 50), ('TE', 20), ('K', 24), ('DST', 30)):
        if c[pos] < need: die(f'{label}: only {c[pos]} {pos}')

# ---------------- build ----------------
def jw(path, obj): json.dump(obj, open(path, 'w'), separators=(',', ':'))
jw(os.path.join(HERE, 'desert-players.json'), {'players': desert_pool})
jw(os.path.join(HERE, 'snakes-players.json'), {'players': snakes_pool})
for lg in ('desert-league.json', 'snakes-league.json'):
    d = json.load(open(os.path.join(HERE, lg)))
    d['scrapeDate'] = f'ADP {adp_date} · projections ESPN {today}'
    json.dump(d, open(os.path.join(HERE, lg), 'w'), indent=1)

def run(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: die(' '.join(cmd[:3]) + ' failed: ' + (r.stderr or r.stdout)[-400:])
    return r.stdout

out1 = run(sys.executable, os.path.join(HERE, 'build_room.py'),
           os.path.join(HERE, 'desert-league.json'), os.path.join(HERE, 'desert-players.json'),
           os.path.join(REPO, 'index.html'),
           '--template', os.path.join(HERE, 'war-room.template.html'),
           '--logo', os.path.join(HERE, 'rts-logo.svg'), '--favicon', open(os.path.join(HERE, 'rts-favicon.txt')).read().strip())
out2 = run(sys.executable, os.path.join(HERE, 'build_room.py'),
           os.path.join(HERE, 'snakes-league.json'), os.path.join(HERE, 'snakes-players.json'),
           os.path.join(REPO, 'snakes', 'index.html'),
           '--template', os.path.join(HERE, 'war-room.template.html'),
           '--logo', os.path.join(HERE, 'snake-logo.svg'), '--favicon', open(os.path.join(HERE, 'snake-favicon.txt')).read().strip())
print(out1); print(out2)
for f in ('index.html', 'snakes/index.html'):
    if os.path.getsize(os.path.join(REPO, f)) < 120000: die(f'{f} suspiciously small')

# ---------------- push ----------------
if PUSH:
    os.chdir(REPO)
    if subprocess.run(['git', 'diff', '--quiet', 'index.html', 'snakes/index.html']).returncode == 0:
        print('no changes to publish')
    else:
        run('git', 'add', 'index.html', 'snakes/index.html', 'tools')
        run('git', '-c', 'user.name=Jerry Asencio', '-c', 'user.email=Jerryasencio@gmail.com',
            'commit', '-m', f'Rankings refresh {today} (ADP {adp_date}, ESPN projections)')
        run('git', 'push')
        print('pushed')
print(f'REFRESH OK · ADP {adp_date} · ESPN projections {today} · '
      f'Allen(desert)={allen_d} Chase(snakes)={chase_s}')
