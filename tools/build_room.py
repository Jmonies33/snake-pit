#!/usr/bin/env python3
"""
Build a draft war room from a league config + a player pool.

    python3 build_room.py league.json players.json out.html [--logo logo.svg]

What it does, in order:
  1. Derives pool membership from league.pools and validates every position maps
     somewhere. An unmapped position silently vanishing from the board is the
     single most damaging config bug, so it is a hard error here.
  2. Computes each player's points under THIS league's scoring, from stat lines
     when present. Custom scoring reshuffles players *within* a position (a
     90-catch TE and a 40-catch TE move in opposite directions under TE premium),
     which is why points must be recomputed rather than a rank being multiplied.
  3. Computes replacement level per pool: the (teams x starting slots + 1)-th
     best player in that pool. Flex pools merge before ranking.
  4. Emits the self-contained HTML.

league.json shape (see references/valuation.md for the full contract):
{
  "brandName": "Desert League", "brandTag": "Live Draft HQ",
  "teams": 11, "bench": 0,
  "slots":  {"QB":2,"RB":3,"WRTE":5,"DST":2,"K":2},
  "pools":  {"QB":["QB"],"RB":["RB"],"WRTE":["WR","TE"],"DST":["DST"],"K":["K"]},
  "groups": [["QB","Quarterback"],["RB","Running Back"],["WRTE","WR / TE Flex"],
             ["DST","Defense"],["K","Kicker"]],
  "scoring": {"pass_yd":0.04,"pass_td":6,"int":-2,"rush_yd":0.1,"rush_td":6,
              "rec_yd":0.1,"rec_td":6,"fumble":-2,
              "rec_by_pos":{"RB":0,"WR":1.0,"TE":1.5}},
  "concentration": {"pos":"TE","from":3,"step":15},
  "source":"FantasyPros consensus","scrapeDate":"2026-08-14",
  "leagueLine":"11 teams · no bench · 14 rounds · QB2/RB3/WR-TE5/DST2/K2",
  "scoringLine":"RB 0 PPR, WR 1.0, TE 1.5, 6-pt passing TD",
  "draftDate":"Sept 23"
}

players.json: {"players":[{...}]} or a bare list. Each player needs
name, pos, team, and either `pts` (already scored for this league) or a `stats`
object the scoring block can price. `adp` (or `mkt`) drives the market board.
"""
import json, sys, os, re, argparse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, '..', 'assets', 'war-room.template.html')

DEFAULT_LOGO = ('<svg class="mark" viewBox="0 0 64 64" aria-hidden="true">'
  '<defs><linearGradient id="dlg" x1="0" y1="0" x2="0" y2="1">'
  '<stop offset="0" stop-color="#ff3b57"/><stop offset="1" stop-color="#b30b24"/></linearGradient></defs>'
  '<path d="M32 3 58 12v20c0 15-11 25-26 29C17 57 6 47 6 32V12z" fill="url(#dlg)"/>'
  '<path d="M20 24h24M20 32h24M20 40h16" stroke="#fff" stroke-width="4" stroke-linecap="round"/></svg>')
DEFAULT_FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
  "%3Cpath d='M32 3 58 12v20c0 15-11 25-26 29C17 57 6 47 6 32V12z' fill='%23d81f33'/%3E%3C/svg%3E")


def die(msg):
    print('ERROR: ' + msg, file=sys.stderr)
    sys.exit(1)


def score_player(p, scoring):
    """Points under this league's rules. Returns None if the player carries no
    stat line — the caller then requires a precomputed `pts`."""
    st = p.get('stats')
    if not st:
        return None
    pts = 0.0
    for key, per in scoring.items():
        if key == 'rec_by_pos':
            continue
        if key in st:
            pts += (st[key] or 0) * per
    # receptions are priced per position: this is what TE-premium and
    # zero-RB-PPR actually mean, and it reorders players inside a position.
    rbp = scoring.get('rec_by_pos')
    if rbp is not None and 'rec' in st:
        pts += (st['rec'] or 0) * rbp.get(p['pos'], scoring.get('rec', 0))
    elif 'rec' in st and 'rec' in scoring:
        pts += (st['rec'] or 0) * scoring['rec']
    return round(pts, 1)


def slugify(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('league'); ap.add_argument('players'); ap.add_argument('out')
    ap.add_argument('--logo', help='file containing an <svg class="mark">...</svg>')
    ap.add_argument('--favicon', help='favicon href (data: URI or path)')
    ap.add_argument('--template', default=TEMPLATE)
    a = ap.parse_args()

    lg = json.load(open(a.league))
    raw = json.load(open(a.players))
    players = raw['players'] if isinstance(raw, dict) else raw

    teams = int(lg['teams'])
    slots = lg['slots']
    pools = lg['pools']
    bench = int(lg.get('bench', 0))
    scoring = lg.get('scoring', {})

    # ---- 1. pool mapping, validated -------------------------------------
    pos2pool = {}
    for pool, positions in pools.items():
        if pool not in slots:
            die(f'pool "{pool}" has no entry in slots')
        for pos in positions:
            if pos in pos2pool:
                die(f'position {pos} appears in two pools ({pos2pool[pos]}, {pool})')
            pos2pool[pos] = pool
    for pool in slots:
        if pool not in pools:
            die(f'slots has "{pool}" but pools does not define which positions fill it')

    seen_pos = sorted({p['pos'] for p in players})
    unmapped = [p for p in seen_pos if p not in pos2pool]
    if unmapped:
        die(f'positions in the player pool with no slot to fill: {unmapped}. '
            f'Either add them to `pools` or filter them out of the player file.')

    # ---- 2. score under this league -------------------------------------
    # Ids must be unique AND stable across rebuilds — picks and the sync layer
    # reference them, so an id that shifts between builds silently corrupts a
    # draft already in progress. Same-name players at the same position are real
    # (there are routinely two of them in a season), so team is part of the key.
    out, used = [], {}
    for p in players:
        pos = p['pos']
        pts = p.get('pts')
        computed = score_player(p, scoring) if scoring else None
        if computed is not None:
            pts = computed
        if pts is None:
            die(f'{p.get("name","?")} has neither `pts` nor a `stats` line the '
                f'scoring block can price')
        team = p.get('team', 'FA')
        pid = p.get('id')
        if not pid:
            base = f"{pos}-{slugify(p['name'])}-{slugify(team)}"
            n = used.get(base, 0)
            used[base] = n + 1
            pid = base if n == 0 else f'{base}-{n + 1}'
        out.append({
            'id': pid, 'name': p['name'], 'pos': pos, 'team': team,
            'bye': int(p.get('bye') or 0),
            'pts': float(pts),
            'adp': float(p.get('adp') or p.get('mkt') or 9999),
        })

    if len({p['id'] for p in out}) != len(out):
        seen, dupes = set(), set()
        for p in out:
            (dupes if p['id'] in seen else seen).add(p['id'])
        die(f'duplicate player ids supplied in the input file: {sorted(dupes)[:5]}')

    # market board = ADP order; ties and missing ADP fall back to points so the
    # board-walk never stalls on a block of 9999s.
    out.sort(key=lambda p: (p['adp'], -p['pts']))
    for i, p in enumerate(out, 1):
        p['mkt'] = i

    # positional ranks come from points under THIS scoring, not from the source's
    # ranks — that is the whole point of recomputing.
    by_pos = {}
    for p in sorted(out, key=lambda p: -p['pts']):
        by_pos.setdefault(p['pos'], []).append(p)
    for pos, lst in by_pos.items():
        for i, p in enumerate(lst, 1):
            p['posRank'] = i

    # ---- 3. replacement level per pool ----------------------------------
    # A shared flex (dedicated RB/WR/TE slots PLUS one slot any of them can fill)
    # cannot be expressed as pool membership, because the flex belongs to several
    # pools at once. Model it the way it actually resolves: fill dedicated slots
    # first, then hand each flex slot to whichever eligible position has the best
    # player still on the board. Replacement is whoever is left after that.
    flex = lg.get('flex')
    ranked = {pool: sorted([p for p in out if pos2pool[p['pos']] == pool],
                           key=lambda p: -p['pts']) for pool in slots}
    idx, pool_slots = {}, {}
    for pool in slots:
        n = teams * int(slots[pool])
        idx[pool] = n
        pool_slots[pool] = n

    flex_absorbed = {}
    if flex:
        bad = [p for p in flex['eligible'] if p not in pos2pool]
        if bad:
            die(f'flex eligible positions not present in any pool: {bad}')
        elig = sorted({pos2pool[p] for p in flex['eligible']})
        for _ in range(teams * int(flex['slots'])):
            best_pool, best_pts = None, None
            for pool in elig:
                lst = ranked[pool]
                if idx[pool] < len(lst) and (best_pts is None or lst[idx[pool]]['pts'] > best_pts):
                    best_pts, best_pool = lst[idx[pool]]['pts'], pool
            if best_pool is None:
                die('not enough flex-eligible players to fill the league\'s flex slots')
            idx[best_pool] += 1
            flex_absorbed[best_pool] = flex_absorbed.get(best_pool, 0) + 1

    replacement = {}
    for pool in slots:
        if len(ranked[pool]) <= idx[pool]:
            die(f'pool "{pool}" needs {idx[pool]} starters league-wide (including flex) '
                f'but the player file only has {len(ranked[pool])}. '
                f'The draft cannot legally complete.')
        replacement[pool] = ranked[pool][idx[pool]]['pts']
    for p in out:
        p['vor'] = round(p['pts'] - replacement[pos2pool[p['pos']]], 1)

    rounds = (sum(int(v) for v in slots.values())
              + (int(flex['slots']) if flex else 0) + bench)
    meta = {
        'source': lg.get('source', 'unspecified'),
        'scrapeDate': lg.get('scrapeDate', str(datetime.date.today())),
        'built': str(datetime.date.today()),
        'teams': teams, 'rounds': rounds, 'totalPicks': teams * rounds,
        'slots': slots, 'pools': pools, 'bench': bench, 'flex': flex,
        'groups': lg.get('groups') or [[k, k] for k in slots],
        'poolSlots': pool_slots, 'flexAbsorbed': flex_absorbed,
        'replacement': replacement,
        'concentration': lg.get('concentration'),
        'teamNames': lg.get('teamNames'),
        'coachKeyHash': lg.get('coachKeyHash'),
        'byeWeight': lg.get('byeWeight'),
        'leagueLine': lg.get('leagueLine',
            f"{teams} teams · {rounds} rounds · " + ' / '.join(f'{k}{v}' for k, v in slots.items())),
        'scoringLine': lg.get('scoringLine', 'league scoring'),
        'draftDate': lg.get('draftDate'),
    }

    tpl = open(a.template).read()
    logo = open(a.logo).read().strip() if a.logo else DEFAULT_LOGO
    if 'class="mark"' not in logo:
        logo = logo.replace('<svg ', '<svg class="mark" ', 1)
    payload = json.dumps({'meta': meta, 'players': out},
                         separators=(',', ':')).replace('</', '<\\/')
    html = (tpl.replace('__PLAYERDATA__', payload)
               .replace('__BRAND_LOGO__', logo)
               .replace('__FAVICON__', a.favicon or DEFAULT_FAVICON)
               .replace('__BRAND_NAME__', lg.get('brandName', 'Draft Room'))
               .replace('__BRAND_TAG__', lg.get('brandTag', 'Live Draft HQ')))
    left = re.findall(r'__[A-Z_]+__', html)
    if left:
        die(f'template placeholders left unfilled: {sorted(set(left))}')
    open(a.out, 'w').write(html)

    print(f'built {a.out}  ({len(html)//1024} KB)')
    print(f'  {len(out)} players · {teams} teams x {rounds} rounds = {teams*rounds} picks')
    if flex:
        print(f'  flex: {teams*int(flex["slots"])} slots over {"/".join(flex["eligible"])} '
              f'-> absorbed ' + ', '.join(f'{k} {v}' for k, v in sorted(flex_absorbed.items())))
    for pool in slots:
        extra = flex_absorbed.get(pool, 0)
        tag = f' (+{extra} flex)' if extra else ''
        print(f'  {pool:<6} {pool_slots[pool]:>3} starters league-wide{tag} · '
              f'replacement {replacement[pool]:.0f} pts')


if __name__ == '__main__':
    main()
