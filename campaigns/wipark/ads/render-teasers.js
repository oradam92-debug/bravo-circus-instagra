// node campaigns/wipark/ads/render-teasers.js [n...]  ->  final/teaser/wipark-teaser-<n>-{feed,story}.png
const {chromium} = require('playwright'); const path = require('path'); const fs = require('fs');
const out = path.join(__dirname, 'final', 'teaser'); fs.mkdirSync(out, {recursive: true});
const ns = process.argv.slice(2).length ? process.argv.slice(2) : ['1', '2', '3', '4'];
const photos = {1: 'teaser-1.jpg', 2: 'teaser-2.jpg', 3: 'teaser-3.jpg', 4: '../pano-feed.jpg'};
(async () => {
  const b = await chromium.launch();
  for (const n of ns) {
    if (!fs.existsSync(path.join(__dirname, '..', 'brand', 'renders', 'teaser', photos[n]))) { console.log('skip', n, '(no photo yet)'); continue; }
    for (const [f, h] of [['feed', 1350], ['story', 1920]]) {
      const p = await b.newPage({viewport: {width: 1080, height: h}});
      await p.goto('file://' + path.join(__dirname, 'teaser-series.html') + `?n=${n}&f=${f}`);
      await p.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(i => i.decode().catch(() => {}))); });
      await p.waitForTimeout(400);
      await p.screenshot({path: path.join(out, `wipark-teaser-${n}-${f}.png`)});
      console.log(n, f);
    }
  }
  await b.close();
})();
