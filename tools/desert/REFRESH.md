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
