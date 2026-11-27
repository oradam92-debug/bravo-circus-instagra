// node campaigns/wipark/ads/render-overlay.js -> final/video/overlay-story.png (transparent, 1080x1920)
const {chromium} = require('playwright'); const path = require('path'); const fs = require('fs');
const out = path.join(__dirname, 'final', 'video'); fs.mkdirSync(out, {recursive: true});
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({viewport: {width: 1080, height: 1920}});
  await p.goto('file://' + path.join(__dirname, 'panorama.html') + '?f=story&overlay=1');
  await p.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(i => i.decode().catch(() => {}))); });
  await p.waitForTimeout(300);
  await p.screenshot({path: path.join(out, 'overlay-story.png'), omitBackground: true});
  await b.close(); console.log('overlay ok');
})();
