// Capture all slides from presentation HTML using Puppeteer.
// Usage: node capture.mjs <input.html> <output_dir>
import puppeteer from 'puppeteer';
import { resolve, join } from 'path';
import { mkdirSync, readdirSync, rmSync } from 'fs';


const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const [,, htmlPath, outputDir] = process.argv;
if (!htmlPath || !outputDir) {
    console.error('Usage: node capture.mjs <input.html> <output_dir>');
    process.exit(1);
}

mkdirSync(outputDir, { recursive: true });
for (const file of readdirSync(outputDir)) {
    if (/^slide-\d+\.png$/.test(file)) {
        rmSync(join(outputDir, file));
    }
}

const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.setViewport({ width: 1920, height: 1080 });

await page.goto('file://' + resolve(htmlPath));
await page.addStyleTag({ content: '.nav-hint, .page-counter { display: none !important; }' });
await sleep(2000);

const total = await page.evaluate(() => document.querySelectorAll('.slide').length);
console.log(`Capturing ${total} slides from ${htmlPath}`);

for (let i = 0; i < total; i++) {
    await page.evaluate((idx) => {
        const slides = Array.from(document.querySelectorAll('.slide'));
        slides.forEach(s => s.classList.remove('active', 'visible'));
        slides[idx].classList.add('active', 'visible');
    }, i);

    // Wait for CSS transitions/animations
    await sleep(800);

    const outPath = join(resolve(outputDir), `slide-${String(i + 1).padStart(2, '0')}.png`);
    await page.screenshot({ path: outPath });
    console.log(`  [${i + 1}/${total}] ${outPath}`);
}

await browser.close();
console.log(`Done. ${total} slides saved to ${outputDir}`);
