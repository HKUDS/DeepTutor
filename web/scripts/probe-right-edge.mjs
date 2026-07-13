import { chromium } from "playwright";

const URL = "http://localhost:3784/home";
const VW = 1440;
const VH = 900;

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: VW, height: VH },
  deviceScaleFactor: 2,
});
await page.goto(URL, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);

// Rightmost 70 CSS px, full height — any right-edge shadow shows as a
// darkening gradient in this narrow strip.
await page.screenshot({
  path: "/tmp/right-strip.png",
  clip: { x: VW - 70, y: 0, width: 70, height: VH },
});
console.log("saved /tmp/right-strip.png");
await browser.close();
