// node campaigns/wipark/ads/render-teasers.js [--launch] [n...]  ->  final/<series>/wipark-<series>-<n>-{feed,story}.png
const {chromium} = require('playwright'); const path = require('path'); const fs = require('fs');
const args = process.argv.slice(2); const series = args.includes('--launch') ? 'launch' : 'teaser';
const out = path.join(__dirname, 'final', series); fs.mkdirSync(out, {recursive: true});
const given = args.filter(a => !a.startsWith('--')); const ns = given.length ? given : ['1', '2', '3', '4'];
const photos = {1: `${series}-1.jpg`, 2: `${series}-2.jpg`, 3: `${series}-3.jpg`, 4: '../pano-feed.jpg'};
(async () => {
  const b = await chromium.launch();
  for (const n of ns) {
    if (!fs.existsSync(path.join(__dirname, '..', 'brand', 'renders', series, photos[n]))) { console.log('skip', n, '(no photo yet)'); continue; }
    for (const [f, h] of [['feed', 1350], ['story', 1920]]) {
      const p = await b.newPage({viewport: {width: 1080, height: h}});
      await p.goto('file://' + path.join(__dirname, 'teaser-series.html') + `?s=${series}&n=${n}&f=${f}`);
      await p.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(i => i.decode().catch(() => {}))); });
      await p.waitForTimeout(400);
      await p.screenshot({path: path.join(out, `wipark-${series}-${n}-${f}.png`)});
      console.log(n, f);
    }
  }
  await b.close();
})();
