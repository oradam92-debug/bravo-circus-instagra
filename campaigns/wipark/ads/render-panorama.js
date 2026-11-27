// node campaigns/wipark/ads/render-panorama.js  ->  final/wipark-oshiland-panorama-{feed,story}.png
const {chromium} = require('playwright'); const path = require('path');
(async () => {
  const b = await chromium.launch();
  for (const [f, h] of [['feed', 1350], ['story', 1920]]) {
    const p = await b.newPage({viewport: {width: 1080, height: h}});
    await p.goto('file://' + path.join(__dirname, 'panorama.html') + '?f=' + f);
    await p.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(i => i.decode().catch(() => {}))); });
    await p.waitForTimeout(300);
    await p.screenshot({path: path.join(__dirname, 'final', `wipark-oshiland-panorama-${f}.png`)});
    console.log(f);
  }
  await b.close();
})();
