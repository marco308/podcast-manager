#!/usr/bin/env node
// Capture the README screenshots of every main screen, in light and dark themes.
//
// The app sits behind Spotify OAuth, so a real session is needed. Authenticate
// once in a headed browser and the session is saved to a gitignored file:
//
//   npx playwright install chromium        # one-off, downloads the browser
//   npm run screenshots -- --login         # complete the Spotify login in the window
//
// Then capture (headless, repeatable — rerun whenever the UI changes):
//
//   npm run screenshots
//
// Environment overrides:
//   BASE_URL          app origin (default https://127.0.0.1:3000, the Vite dev server)
//   SCREENSHOTS_DIR   output folder (default ../docs/screenshots, relative to frontend/)
//   SCREENSHOT_SCALE  device scale factor, 2 for retina-crisp images (default 1)
//   SCREENSHOT_MASK   extra comma-separated CSS selectors to black out on every page
//
// Account details on the Settings page are masked by default so the images can
// be committed without leaking the maintainer's Spotify profile. Review the
// output before committing regardless.

import { chromium } from 'playwright';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(here, '..');

const BASE_URL = (process.env.BASE_URL ?? 'https://127.0.0.1:3000').replace(/\/$/, '');
const OUT_DIR = path.resolve(frontendDir, process.env.SCREENSHOTS_DIR ?? '../docs/screenshots');
const SCALE = Number(process.env.SCREENSHOT_SCALE ?? '1');
const AUTH_FILE = path.join(frontendDir, '.screenshots-auth.json');
const VIEWPORT = { width: 1440, height: 900 };
const LOGIN_TIMEOUT_MS = 5 * 60 * 1000;

const extraMask = (process.env.SCREENSHOT_MASK ?? '')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

// One entry per screen. `mask` selectors are blacked out in the image.
const PAGES = [
  { slug: 'dashboard', route: '/', mask: [] },
  { slug: 'podcasts', route: '/podcasts', mask: [] },
  { slug: 'playlists', route: '/playlists', mask: [] },
  { slug: 'settings', route: '/settings', mask: ['.ant-descriptions-item-content'] },
];

const THEMES = ['light', 'dark'];

async function launch({ headless }) {
  try {
    return await chromium.launch({ headless });
  } catch (err) {
    if (/Executable doesn't exist|browserType.launch/.test(String(err))) {
      console.error(
        'Chromium is not installed for Playwright. Run: npx playwright install chromium'
      );
      process.exit(1);
    }
    throw err;
  }
}

async function isAuthenticated(context) {
  const res = await context.request.get(`${BASE_URL}/api/auth/me`, { failOnStatusCode: false });
  return res.ok();
}

async function login() {
  const browser = await launch({ headless: false });
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: VIEWPORT });
  const page = await context.newPage();
  await page.goto(`${BASE_URL}/login`);

  console.log(`Complete the Spotify login in the browser window (waiting up to 5 minutes)...`);
  const deadline = Date.now() + LOGIN_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await isAuthenticated(context)) {
      await context.storageState({ path: AUTH_FILE });
      console.log(`Session saved to ${path.relative(process.cwd(), AUTH_FILE)} (gitignored).`);
      await browser.close();
      return;
    }
    await page.waitForTimeout(1000);
  }
  await browser.close();
  console.error('Timed out waiting for login.');
  process.exit(1);
}

async function capture() {
  if (!existsSync(AUTH_FILE)) {
    console.error(`No saved session at ${AUTH_FILE}. Run: npm run screenshots -- --login`);
    process.exit(1);
  }
  mkdirSync(OUT_DIR, { recursive: true });

  const browser = await launch({ headless: true });
  try {
    for (const theme of THEMES) {
      const context = await browser.newContext({
        storageState: AUTH_FILE,
        ignoreHTTPSErrors: true,
        viewport: VIEWPORT,
        deviceScaleFactor: SCALE,
        colorScheme: theme,
      });
      // ThemeContext reads this key on load; set it before any page script runs.
      await context.addInitScript((value) => {
        localStorage.setItem('theme-preference', value);
      }, theme);

      if (!(await isAuthenticated(context))) {
        console.error('Saved session is no longer valid. Run: npm run screenshots -- --login');
        process.exit(1);
      }

      const page = await context.newPage();
      for (const { slug, route, mask } of PAGES) {
        await page.goto(`${BASE_URL}${route}`, { waitUntil: 'networkidle' });
        if (new URL(page.url()).pathname === '/login') {
          console.error(`Redirected to /login while opening ${route}; session expired?`);
          process.exit(1);
        }
        // Let React Query settle and Ant Design transitions finish.
        await page.waitForTimeout(500);

        const file = path.join(OUT_DIR, `${slug}-${theme}.png`);
        await page.screenshot({
          path: file,
          fullPage: false,
          animations: 'disabled',
          mask: [...mask, ...extraMask].map((selector) => page.locator(selector)),
          maskColor: theme === 'dark' ? '#303030' : '#d9d9d9',
        });
        console.log(`wrote ${path.relative(process.cwd(), file)}`);
      }
      await context.close();
    }
  } finally {
    await browser.close();
  }
}

const mode = process.argv.includes('--login') ? 'login' : 'capture';
(mode === 'login' ? login() : capture()).catch((err) => {
  console.error(err);
  process.exit(1);
});
