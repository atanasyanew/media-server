const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');

(async () => {
  const fixture = spawn('python3', ['tests/ui_fixture.py'], { stdio: 'inherit' });
  let browser;
  try {
    for (let attempt = 0; attempt < 100; attempt++) {
      try {
        const response = await fetch('http://127.0.0.1:8099/healthz');
        if (response.ok) break;
      } catch {}
      if (attempt === 99) throw Error('Browser fixture did not start');
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
    const page = await browser.newPage({ viewport: { width: 1200, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8099');
    await page.getByRole('heading', { name: 'Across the mountains (2024)' }).waitFor();
    await page.getByRole('button', { name: 'Check languages' }).nth(0).click();
    await page.getByText('Available in your library.', { exact: true }).waitFor();
    await page.selectOption('#audio', 'ja');
    assert.equal(await page.inputValue('#subtitle'), 'en');
    await page.getByRole('button', { name: 'Check languages' }).nth(0).click();
    await page.getByText('Japanese audio is not available in your library.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Check languages' }).nth(1).click();
    await page.getByRole('button', { name: 'Use these languages' }).click();
    await page.getByRole('link', { name: 'Open in Jellyfin' }).waitFor();
    await page.getByRole('button', { name: 'Check languages' }).nth(2).click();
    await page.getByText(/Language availability is unknown/).waitFor();
    await page.screenshot({ path: 'browser-desktop.png', fullPage: true });
    await page.reload();
    await page.getByRole('heading', { name: 'Across the mountains (2024)' }).waitFor();
    assert.equal(await page.inputValue('#audio'), 'ja');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok((await page.locator('#search').boundingBox()).width > 180, 'Mobile search field must remain usable');
    await page.screenshot({ path: 'browser-mobile.png', fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log('Browser checks passed: language states, Japanese subtitles, saving languages, Jellyfin link, remembered choice, mobile layout.');
  } finally {
    if (browser) await browser.close();
    fixture.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
