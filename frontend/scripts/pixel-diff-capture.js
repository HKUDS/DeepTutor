#!/usr/bin/env node
/**
 * Pixel Diff Capture & Compare Script
 * Uses puppeteer to capture screenshots of both MHTML references and replica pages,
 * then compares them pixel-by-pixel using pixelmatch.
 *
 * Usage: node scripts/pixel-diff-capture.js
 */

import puppeteer from 'puppeteer';
import pixelmatch from 'pixelmatch';
import { PNG } from 'pngjs';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..');
const SCREENSHOTS_DIR = path.join(ROOT, 'screenshots');
const DIFF_DIR = path.join(ROOT, 'diff-output');

const VIEWPORT = { width: 1440, height: 900, deviceScaleFactor: 1 };
const THRESHOLD = 5; // pixel diff threshold (0-255)
const WAIT = (ms) => new Promise(r => setTimeout(r, ms));

for (const dir of [SCREENSHOTS_DIR, DIFF_DIR]) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

const MHTML_FILES = {
  'new-task': '新建任务.mhtml',
  'automation': '自动化.mhtml',
  'marketplace': '插件市场.mhtml',
  'plugin-detail': '插件市场-插件详情.mhtml',
};

async function setDarkTheme(page) {
  // Click theme toggle to switch to dark mode
  const themeBtn = await page.$('button[aria-label="切换主题"]');
  if (themeBtn) {
    // Check current theme
    const currentTheme = await page.evaluate(() => 
      document.documentElement.getAttribute('data-theme')
    );
    if (currentTheme !== 'dark') {
      await themeBtn.click();
      await WAIT(300);
    }
  } else {
    // Fallback: directly set attribute
    await page.evaluate(() => {
      document.documentElement.setAttribute('data-theme', 'dark');
    });
  }
}

async function clickNavItemByText(page, text) {
  const items = await page.$$('.navItem-r4wswG');
  for (const item of items) {
    const label = await item.evaluate(el => el.textContent?.trim() || '');
    if (label.includes(text)) {
      await item.click();
      return true;
    }
  }
  return false;
}

async function captureReplica(browser, key) {
  const configs = {
    'new-task': {
      name: '新建任务',
      navigate: async (page) => {
        await setDarkTheme(page);
        // Click "新建任务" nav item
        const clicked = await clickNavItemByText(page, '新建任务');
        if (!clicked) throw new Error('Could not find 新建任务 nav item');
        await WAIT(800);
      },
      waitSelector: '.workspace-sBvxKr',
    },
    'automation': {
      name: '学习空间',
      navigate: async (page) => {
        await setDarkTheme(page);
        const clicked = await clickNavItemByText(page, '学习空间');
        if (!clicked) throw new Error('Could not find 学习空间 nav item');
        await WAIT(800);
      },
      waitSelector: '.container-YgYmSM',
    },
    'marketplace': {
      name: '插件市场',
      navigate: async (page) => {
        await setDarkTheme(page);
        const clicked = await clickNavItemByText(page, '插件市场');
        if (!clicked) throw new Error('Could not find 插件市场 nav item');
        await WAIT(800);
      },
      waitSelector: '.marketplacePage-U60AB4',
    },
    'plugin-detail': {
      name: '插件详情',
      navigate: async (page) => {
        await setDarkTheme(page);
        const clicked = await clickNavItemByText(page, '插件市场');
        if (!clicked) throw new Error('Could not find 插件市场 nav item');
        await WAIT(800);
        // Click first plugin card
        await page.waitForSelector('.pluginCard-cq4jH5');
        const cards = await page.$$('.pluginCard-cq4jH5');
        if (cards.length > 0) {
          await cards[0].click();
          await WAIT(600);
        } else {
          throw new Error('No plugin cards found');
        }
      },
      waitSelector: '.detailPanel-NZOW7g',
    },
  };
  
  const config = configs[key];
  if (!config) {
    console.log(`\n⚠️  No replica config for: ${key}`);
    return null;
  }
  
  console.log(`\n🎨 Capturing Replica: ${config.name}`);
  
  const page = await browser.newPage({ viewport: VIEWPORT });
  
  try {
    await page.goto('http://localhost:5174/', { waitUntil: 'domcontentloaded', timeout: 15000 });
    await WAIT(1000);
    
    // Accept the cookie banner / initial state
    try {
      await page.waitForSelector('main', { timeout: 5000 });
    } catch (e) {
      console.log('   ⚠️  Main element not found, continuing...');
    }
    
    await config.navigate(page);
    
    // Wait for target element
    if (config.waitSelector) {
      try {
        await page.waitForSelector(config.waitSelector, { timeout: 5000 });
      } catch (e) {
        console.log(`   ⚠️  Target selector "${config.waitSelector}" not found`);
      }
    }
    await WAIT(500);
    
    const screenshotPath = path.join(SCREENSHOTS_DIR, `replica-${key}.png`);
    await page.screenshot({ path: screenshotPath, clip: { x: 0, y: 0, width: VIEWPORT.width, height: VIEWPORT.height } });
    
    const stats = fs.statSync(screenshotPath);
    console.log(`   ✅ Saved: ${path.basename(screenshotPath)} (${(stats.size / 1024).toFixed(1)}KB)`);
    
    await page.close();
    return screenshotPath;
  } catch (err) {
    console.error(`   ❌ Error capturing replica: ${err.message}`);
    await page.close().catch(() => {});
    return null;
  }
}

async function captureMHTML(browser, key) {
  const file = MHTML_FILES[key];
  const filePath = path.join(ROOT, file);
  const url = `file://${filePath}`;
  
  console.log(`\n📸 Capturing MHTML: ${file}`);
  
  const page = await browser.newPage({ viewport: VIEWPORT });
  
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
    
    if (!response || !response.ok()) {
      console.warn(`   ⚠️  MHTML load returned status: ${response?.status()}`);
    }
    
    await WAIT(2000);
    
    const hasContent = await page.evaluate(() => {
      return document.body && document.body.innerHTML.length > 100;
    });
    
    if (!hasContent) {
      console.warn(`   ⚠️  MHTML page appears empty, retrying...`);
      await page.reload({ waitUntil: 'load', timeout: 10000 });
      await WAIT(2000);
    }
    
    const screenshotPath = path.join(SCREENSHOTS_DIR, `mhtml-${key}.png`);
    await page.screenshot({ path: screenshotPath, clip: { x: 0, y: 0, width: VIEWPORT.width, height: VIEWPORT.height } });
    
    const stats = fs.statSync(screenshotPath);
    console.log(`   ✅ Saved: ${path.basename(screenshotPath)} (${(stats.size / 1024).toFixed(1)}KB)`);
    
    await page.close();
    return screenshotPath;
  } catch (err) {
    console.error(`   ❌ Error capturing MHTML: ${err.message}`);
    await page.close().catch(() => {});
    return null;
  }
}

function compareImages(img1Path, img2Path, outputDiffPath) {
  const img1 = PNG.sync.read(fs.readFileSync(img1Path));
  const img2 = PNG.sync.read(fs.readFileSync(img2Path));
  
  const width = Math.min(img1.width, img2.width);
  const height = Math.min(img1.height, img2.height);
  
  if (img1.width !== img2.width || img1.height !== img2.height) {
    console.log(`   ⚠️  Dimension mismatch: ${img1.width}x${img1.height} vs ${img2.width}x${img2.height}, using ${width}x${height}`);
  }
  
  const diff = new PNG({ width, height });
  const data1 = img1.data;
  const data2 = img2.data;
  const diffData = diff.data;
  
  let diffPixels = 0;
  const totalPixels = width * height;
  const diffLocations = [];
  
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = (y * width + x) * 4;
      const r = Math.abs(data1[idx] - data2[idx]);
      const g = Math.abs(data1[idx + 1] - data2[idx + 1]);
      const b = Math.abs(data1[idx + 2] - data2[idx + 2]);
      const a = Math.abs(data1[idx + 3] - data2[idx + 3]);
      
      const maxDiff = Math.max(r, g, b, a);
      
      if (maxDiff > THRESHOLD) {
        diffPixels++;
        diffData[idx] = Math.min(255, r * 3);
        diffData[idx + 1] = Math.min(255, g * 3);
        diffData[idx + 2] = Math.min(255, b * 3);
        diffData[idx + 3] = 255;
        
        if (diffLocations.length < 20) {
          diffLocations.push({ x, y, r, g, b, a: maxDiff });
        }
      } else {
        diffData[idx] = data1[idx];
        diffData[idx + 1] = data1[idx + 1];
        diffData[idx + 2] = data1[idx + 2];
        diffData[idx + 3] = Math.min(255, data1[idx + 3] + 80);
      }
    }
  }
  
  const diffPercent = ((diffPixels / totalPixels) * 100).toFixed(2);
  const pass = parseFloat(diffPercent) <= 1.1;
  
  fs.writeFileSync(outputDiffPath, PNG.sync.write(diff));
  
  return { diffPixels, totalPixels, diffPercent, pass, width, height, diffLocations };
}

async function main() {
  console.log('🔍 TraeWork Pixel Diff Capture & Compare');
  console.log(`   Viewport: ${VIEWPORT.width}x${VIEWPORT.height} DPR=${VIEWPORT.deviceScaleFactor}`);
  console.log(`   Diff Threshold: ${THRESHOLD} (per-channel pixel difference)`);
  console.log(`   Acceptance: ≤ 1.1% different pixels`);
  
  const browser = await puppeteer.launch({
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
    ],
  });
  
  console.log(`\n🚀 Launched Chrome`);
  
  const results = [];
  
  for (const key of Object.keys(MHTML_FILES)) {
    console.log(`\n${'='.repeat(60)}`);
    console.log(`Processing: ${MHTML_FILES[key]}`);
    console.log('='.repeat(60));
    
    const mhtmlPath = await captureMHTML(browser, key);
    const replicaPath = await captureReplica(browser, key);
    
    if (!mhtmlPath || !replicaPath) {
      results.push({ key, name: MHTML_FILES[key], error: 'Capture failed' });
      continue;
    }
    
    console.log(`\n🔬 Comparing...`);
    const diffPath = path.join(DIFF_DIR, `diff-${key}.png`);
    const comparison = compareImages(mhtmlPath, replicaPath, diffPath);
    
    console.log(`   Diff Pixels: ${comparison.diffPixels.toLocaleString()} / ${comparison.totalPixels.toLocaleString()}`);
    console.log(`   Diff %: ${comparison.diffPercent}%`);
    console.log(`   Result: ${comparison.pass ? '✅ PASS' : '❌ FAIL'}`);
    console.log(`   Resolution: ${comparison.width}x${comparison.height}`);
    if (comparison.diffLocations.length > 0) {
      console.log(`   Sample diff locations: ${comparison.diffLocations.slice(0, 5).map(d => `(${d.x},${d.y}) Δ=${d.a.toFixed(0)}`).join(', ')}`);
    }
    
    results.push({
      key,
      name: MHTML_FILES[key],
      mhtmlPath,
      replicaPath,
      diffPath,
      ...comparison,
    });
  }
  
  await browser.close();
  
  console.log(`\n${'='.repeat(60)}`);
  console.log('📊 PIXEL DIFF SUMMARY');
  console.log('='.repeat(60));
  
  const passed = results.filter(r => r.pass).length;
  const failed = results.filter(r => !r.pass && !r.error).length;
  const errors = results.filter(r => r.error).length;
  
  for (const r of results) {
    const status = r.error ? '⚠️  ERROR' : (r.pass ? '✅ PASS' : '❌ FAIL');
    const pct = r.diffPercent ?? 'N/A';
    console.log(`  ${status}  ${r.name.padEnd(20)}  Diff: ${pct}%`);
  }
  
  console.log(`\n  Passed: ${passed} | Failed: ${failed} | Errors: ${errors}`);
  console.log(`\n📁 Screenshots: ${SCREENSHOTS_DIR}`);
  console.log(`📁 Diff Maps: ${DIFF_DIR}`);
  
  if (failed > 0 || errors > 0) {
    process.exit(1);
  }
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
