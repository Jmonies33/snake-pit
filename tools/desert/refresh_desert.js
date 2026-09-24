#!/usr/bin/env node
/**
 * Desert League edge refresh — standalone, no AI in the loop.
 *
 *   node refresh_desert.js            # refresh: rosters + ids from rtsports, ESPN projections, build, push
 *   node refresh_desert.js --login    # one-time: opens a window so Jerry can sign in to rtsports
 *   node refresh_desert.js --no-push  # build only
 *
 * Uses a persistent Chromium profile (~/.snake-pit-browser) so the rtsports
 * login survives between runs. rtsports pages need BOTH the cookies and the
 * UID token in the URL; the token is read from ~/.snake-pit-browser/rts-uid.txt
 * (written by --login from the address bar) and never committed.
 */
const path = require('path');
const fs = require('fs');
const os = require('os');
const { execSync } = require('child_process');

const NM = '/Users/jerryasencio/.npm/_npx/e41f203b7505f1fb/node_modules';
const { chromium } = require(path.join(NM, 'playwright'));

const HERE = __dirname;
const REPO = path.resolve(HERE, '..', '..');
const PROFILE = path.join(os.homedir(), '.snake-pit-browser');
const UID_FILE = path.join(PROFILE, 'rts-uid.txt');
const LID = '88775';
const LOGIN = process.argv.includes('--login');
const PUSH = !process.argv.includes('--no-push');
const log = (m) => console.log(new Date().toLocaleTimeString() + '  ' + m);

function sh(cmd, opts = {}) { return execSync(cmd, { stdio: 'pipe', encoding: 'utf8', cwd: opts.cwd || HERE }).trim(); }

(async () => {
  fs.mkdirSync(PROFILE, { recursive: true });
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    channel: 'chrome', headless: !LOGIN, viewport: { width: 1300, height: 900 },
  });
  const page = ctx.pages()[0] || await ctx.newPage();

  if (LOGIN) {
    await page.goto('https://www.rtsports.com/login');
    console.log('\nSign in to rtsports in the window that opened, then open the Desert League.');
    console.log('This script will save the session and close on its own once it sees a league page.\n');
    for (let i = 0; i < 600; i++) {            // up to 10 minutes
      await page.waitForTimeout(1000);
      const u = page.url();
      const m = u.match(/[?&]UID=([^&]+)/);
      if (m && /LID=88775/.test(u)) { fs.writeFileSync(UID_FILE, m[1]); log('saved session token'); break; }
    }
    await ctx.close();
    if (!fs.existsSync(UID_FILE)) { console.error('No Desert League page was opened — run --login again.'); process.exit(1); }
    console.log('Logged in. Future runs are headless.');
    return;
  }

  if (!fs.existsSync(UID_FILE)) { console.error('Not logged in yet: run  node refresh_desert.js --login'); process.exit(2); }
  const UID = fs.readFileSync(UID_FILE, 'utf8').trim();
  const base = `https://www.rtsports.com/football`;

  // 1. rosters
  await page.goto(`${base}/report-rosters.php?LID=${LID}&UID=${UID}&X=739503`, { waitUntil: 'networkidle' });
  if (!/Rosters - Desert League/.test(await page.title())) {
    console.error('rtsports session expired (got "' + (await page.title()) + '"). Run  node refresh_desert.js --login');
    await ctx.close(); process.exit(3);
  }
  const rosters = await page.evaluate(() => document.querySelector('main').innerText);
  fs.writeFileSync(path.join(HERE, 'rosters.txt'), rosters);
  log(`rosters: ${rosters.length} chars`);

  // 2. player ids (free agents + my roster) from the Add/Drop page
  await page.goto(`${base}/add-drop.php?LID=${LID}&UID=${UID}&X=0093121`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  const ids = await page.evaluate(() => {
    const POS = { Quarterback: 'QB', 'Running Back': 'RB', 'Wide Receiver': 'WR', 'Tight End': 'TE', Kicker: 'K' };
    const L = [];
    document.querySelectorAll('a.p-name-link[id^="fa-player-"],a[id^="roster-player-"][id$="-name"]').forEach(a => {
      const id = a.id.match(/\d+/)[0]; const al = a.getAttribute('aria-label') || '';
      const m = al.match(/for (.+?), (.+?), NFL team ([A-Z]{2,4})/);
      L.push(m ? [id, m[1], m[3], POS[m[2]] || m[2]].join('\t') : [id, a.textContent.trim(), '', '?'].join('\t'));
    });
    return L.join('\n');
  });
  fs.writeFileSync(path.join(HERE, 'rtsids.txt'), ids);
  log(`player ids: ${ids.split('\n').length} lines`);
  await ctx.close();

  // 3. parse + projections + build
  log(sh('python3 parse_rosters.py').split('\n')[0]);
  log(sh('python3 projections.py'));
  log(sh('python3 build.py').split('\n').pop());

  // 4. publish
  if (PUSH) {
    const changed = sh('git status --porcelain desert tools/desert', { cwd: REPO });
    if (!changed) { log('nothing changed — not pushing'); return; }
    sh('git add desert tools/desert', { cwd: REPO });
    sh(`git -c user.name="Jerry Asencio" -c user.email="Jerryasencio@gmail.com" commit -q -m "Desert edge refresh $(date +%F\\ %H:%M)"`, { cwd: REPO });
    sh('git push -q', { cwd: REPO });
    log('pushed');
  }
})().catch(e => { console.error('REFRESH FAILED:', e.message); process.exit(1); });
