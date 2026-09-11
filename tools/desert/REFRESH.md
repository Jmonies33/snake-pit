# Desert League edge pages — refresh runbook

Pages: `desert/trades.html`, `desert/waivers.html` (GitHub Pages, master-key gated).
Inputs: rtsports rosters (needs Jerry's logged-in Chrome), ESPN projections (public).

## Steps

1. Start the collector (waits for the rosters text, exits when it arrives):
   ```
   cd ~/snake-pit/tools/desert && python3 collect.py rosters --timeout=600
   ```
2. In Jerry's real Chrome (claude-in-chrome tools, NOT the in-app browser pane),
   open the rosters report — the `UID=` token in the URL is his session and is
   required, a bare LID URL bounces to login:
   `https://www.rtsports.com/football/report-rosters.php?LID=88775&UID=<session token from the address bar>&X=739503`
   If that shows a login page, open any Desert League page from his ESPN/RTS
   bookmarks and copy the current UID from the address bar.
3. On that page run (javascript_tool):
   ```
   await new Promise(r=>setTimeout(r,1500)); const t=document.querySelector('main').innerText;
   await fetch('http://127.0.0.1:8765/rosters',{method:'POST',mode:'no-cors',body:t}); 'posted '+t.length
   ```
   The collector prints `received rosters (~11 KB)` and exits.
3b. Also refresh the rtsports player-id map (new free agents need ids for the Speed Kit).
   Start `python3 collect.py rtsids --timeout=600`, open the Add/Drop page
   (`/football/add-drop.php?LID=88775&UID=<token>&X=0093121`) in Chrome, and run:
   ```
   await new Promise(r=>setTimeout(r,2000));
   const POS={Quarterback:'QB','Running Back':'RB','Wide Receiver':'WR','Tight End':'TE',Kicker:'K'};
   const L=[];
   document.querySelectorAll('a.p-name-link[id^="fa-player-"],a[id^="roster-player-"][id$="-name"]').forEach(a=>{const id=a.id.match(/\d+/)[0];const al=a.getAttribute('aria-label')||'';const m=al.match(/for (.+?), (.+?), NFL team ([A-Z]{2,4})/);L.push(m?[id,m[1],m[3],POS[m[2]]||m[2]].join('\t'):[id,a.textContent.trim(),'','?'].join('\t'));});
   await fetch('http://127.0.0.1:8765/rtsids',{method:'POST',mode:'no-cors',body:L.join('\n')}); 'posted '+L.length
   ```
4. Parse + project + build:
   ```
   cd ~/snake-pit/tools/desert && python3 parse_rosters.py && python3 projections.py && python3 build.py
   ```
   `parse_rosters.py` must report 11 teams and at most 1–2 unmatched names
   (unmatched = no ESPN projection; they fall back to rtsports' weekly number).
5. Publish:
   ```
   cd ~/snake-pit && git add desert tools/desert && git commit -m "Desert edge refresh $(date +%F)" && git push
   ```
6. Sanity: `https://jmonies33.github.io/snake-pit/desert/waivers.html` shows a
   blank "Desert League" shell without the key, and the full board with
   `?key=<master key>` (same key as the draft rooms; never paste it anywhere shared).

## Cadence
- Tuesday 7:00 AM: after Monday night, before the trade window (Tue 6 AM–Sun noon).
- Thursday 10:00 AM: one hour before the free-for-all add window (Thu 11:00 AM CT).
