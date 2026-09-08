#!/usr/bin/env python3
"""
Fetch ESPN 2026 projections and score them under Desert League rules.

Scoring is the league's ACTUAL rulebook (rtsports rules.php, read 2026-09-08),
which differs from what the draft room assumed:
  passing  1 pt per 15 yds, 5 per TD, NO interception penalty
  rushing  0.1 per yd, 6 per TD
  receiving 0.1 per yd, 6 per TD, receptions TE 1.5 / WR 1.0 / RB 0
  kicking  3 per FG (any distance), 1 per PAT
  D/ST     1 sack, 3 INT, 3 FR, 6 any TD, 2 safety, 1 blocked kick,
           3 for a game with 0-10 points allowed
Standings are TOTAL POINTS, 18 starters of a 20-man roster with only
positional caps (QB4 RB6 WR9 TE9 K3 DST3) — so raw points are the value.

Writes projections.json: {"date": ..., "players": [{name,pos,team,bye,pts,
  season,week,stats,inj}]}.  `season` = full-season projection, `week` = the
  current scoring period's projection (ESPN statSplitTypeId 1), `pts` = the
  rest-of-season estimate used for ranking = season * (weeks_left / 18).
"""
import json, os, re, sys, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TEAM_ABBR = {1:'ATL',2:'BUF',3:'CHI',4:'CIN',5:'CLE',6:'DAL',7:'DEN',8:'DET',9:'GB',10:'TEN',
 11:'IND',12:'KC',13:'LV',14:'LAR',15:'MIA',16:'MIN',17:'NE',18:'NO',19:'NYG',20:'NYJ',
 21:'PHI',22:'ARI',23:'PIT',24:'LAC',25:'SF',26:'SEA',27:'TB',28:'WSH',29:'CAR',30:'JAX',33:'BAL',34:'HOU'}
POS = {1:'QB',2:'RB',3:'WR',4:'TE',5:'K',16:'DST'}
REC_BY_POS = {'RB': 0.0, 'WR': 1.0, 'TE': 1.5}

def fetch(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def slug(s):
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', s.lower())
    return re.sub(r'[^a-z]', '', s)

def score(st, pos):
    if pos == 'K':
        return 3 * st.get('83', 0) + 1 * st.get('86', 0)
    if pos == 'DST':
        low_pa = st.get('89', 0) + st.get('90', 0) + 0.4 * st.get('91', 0)   # games 0-10 pts allowed
        return (1 * st.get('99', 0) + 3 * st.get('95', 0) + 3 * st.get('96', 0)
                + 6 * (st.get('94', 0) + st.get('103', 0) + st.get('104', 0))
                + 2 * st.get('98', 0) + 1 * st.get('97', 0) + 3 * low_pa)
    return (st.get('3', 0) / 15 + 5 * st.get('4', 0)
            + 0.1 * st.get('24', 0) + 6 * st.get('25', 0)
            + 0.1 * st.get('42', 0) + 6 * st.get('43', 0)
            + REC_BY_POS.get(pos, 0) * st.get('53', 0))

def compress(players, spread, key):
    vals = sorted((p[key] for p in players), reverse=True)
    if len(vals) < 23: return
    cur = vals[0] - vals[21]
    if cur <= 0: return
    mean = sum(vals) / len(vals); f = spread / cur
    for p in players: p[key] = mean + (p[key] - mean) * f

def main(out=os.path.join(HERE, 'projections.json')):
    hdr = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
           'X-Fantasy-Filter': '{"players":{"limit":900,"sortDraftRanks":{"sortPriority":100,"sortAsc":true,"value":"STANDARD"}}}'}
    base = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leaguedefaults/3?view=kona_player_info'
    data = fetch(base, hdr)
    players = data.get('players', [])
    if len(players) < 500:
        print(f'SANITY FAIL: ESPN returned {len(players)} players'); sys.exit(1)
    # current scoring period from the same payload when present
    week = None
    try:
        info = fetch('https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026?view=proTeamSchedules_wl', hdr)
        week = int(info.get('currentScoringPeriod', {}).get('id') or 1)
    except Exception:
        pass
    week = week or 1
    weeks_left = max(1, 18 - week + 1)
    byes = {}
    for pt in (info.get('settings', {}).get('proTeams', []) if week else []):
        if pt.get('byeWeek'): byes[TEAM_ABBR.get(pt['id'], '')] = pt['byeWeek']

    rows = []
    for pl in players:
        p = pl['player']; pos = POS.get(p.get('defaultPositionId'))
        if not pos: continue
        season = wk = None
        for s in p.get('stats', []):
            if s.get('seasonId') != 2026 or s.get('statSourceId') != 1: continue
            if s.get('statSplitTypeId') == 0: season = s
            elif s.get('statSplitTypeId') == 1 and s.get('scoringPeriodId') == week: wk = s
        if not season: continue
        team = TEAM_ABBR.get(p.get('proTeamId'), 'FA')
        st = {k: float(v) for k, v in (season.get('stats') or {}).items()}
        stw = {k: float(v) for k, v in ((wk or {}).get('stats') or {}).items()}
        sp = score(st, pos); wp = score(stw, pos)
        if pos in ('K', 'DST') and sp <= 0:      # no stat line: fall back to ESPN's own total
            sp = float(season.get('appliedTotal', 0)); wp = float((wk or {}).get('appliedTotal', 0))
        stats = {k: round(st.get(c, 0)) for k, c in
                 (('passYd','3'),('passTD','4'),('int','20'),('rushYd','24'),('rushTD','25'),
                  ('rec','53'),('recYd','42'),('recTD','43')) if st.get(c, 0) >= 0.5}
        rows.append({'name': p['fullName'], 'pos': pos, 'team': team, 'bye': byes.get(team, 0),
                     'season': sp, 'week': wp, 'stats': stats,
                     'inj': p.get('injuryStatus', '') if p.get('injuryStatus') not in (None, '', 'ACTIVE') else '',
                     'pctOwn': round(float(((pl.get('player') or {}).get('ownership') or {}).get('percentOwned', 0)), 1)})
    # D/ST projections are the flattest, least reliable line ESPN publishes;
    # pull the 1st-to-22nd spread in so a defense never outranks a real player.
    compress([r for r in rows if r['pos'] == 'DST'], 30, 'season')
    for r in rows:
        r['season'] = round(r['season'], 1); r['week'] = round(r['week'], 1)
        r['pts'] = round(r['season'] * weeks_left / 18, 1)
    rows = [r for r in rows if r['season'] > 0]
    json.dump({'date': str(datetime.date.today()), 'week': week, 'weeksLeft': weeks_left, 'players': rows},
              open(out, 'w'), separators=(',', ':'))
    print(f'projections: {len(rows)} players, week {week}, {weeks_left} weeks left')
    return rows

if __name__ == '__main__':
    main()
