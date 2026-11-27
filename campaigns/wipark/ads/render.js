// מייצר את מודעות הטיזר כ-PNG:  node campaigns/wipark/ads/render.js
// אם קיים campaigns/wipark/brand/logo.png – הלוגו המקורי מחליף את ה-WIPARK המנופח.
// צבעים מקוריים: campaigns/wipark/brand/colors.json, למשל {"blue":"#...","pink":"#...","lime":"#..."}
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path');
const dir = __dirname, brand = path.join(dir, '..', 'brand');
const sizes = {feed: [1080, 1350], story: [1080, 1920], wide: [1920, 1080]};
(async () => {
  const b = await chromium.launch();
  for (const [f, [w, h]] of Object.entries(sizes)) {
    const p = await b.newPage({viewport: {width: w, height: h}});
    await p.goto('file://' + path.join(dir, 'teaser.html') + '?f=' + f);
    const colors = path.join(brand, 'colors.json');
    if (fs.existsSync(colors)) {
      const c = JSON.parse(fs.readFileSync(colors, 'utf8'));
      await p.evaluate(c => Object.entries(c).forEach(([k, v]) => document.documentElement.style.setProperty('--' + k, v)), c);
    }
    const logo = path.join(brand, 'logo.png');
    if (fs.existsSync(logo)) {
      const src = 'data:image/png;base64,' + fs.readFileSync(logo).toString('base64');
      await p.evaluate(src => { const wm = document.getElementById('wordmark');
        const img = document.createElement('img'); img.src = src; img.className = 'logoimg';
        wm.replaceWith(img); }, src);
    }
    await p.evaluate(() => document.fonts.ready);
    await p.waitForTimeout(300);
    await p.screenshot({path: path.join(dir, `teaser-${f}.png`)});
    console.log('teaser-' + f + '.png');
  }
  await b.close();
})();
