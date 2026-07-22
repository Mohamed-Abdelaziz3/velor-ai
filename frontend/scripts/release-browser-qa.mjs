import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const baseUrl = (process.env.QA_BASE_URL || 'http://127.0.0.1:5173').replace(/\/+$/, '');
const apiUrl = (process.env.QA_API_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
const accessToken = process.env.QA_ACCESS_TOKEN || '';
const artifactDir = fileURLToPath(new URL('../artifacts/release-qa/', import.meta.url));
const checks = [];
const failures = [];
const runtimeErrors = [];
const expectedDegradations = [];

function check(condition, label, details = '') {
  checks.push({ label, passed: Boolean(condition) });
  if (!condition) failures.push(details ? `${label}: ${details}` : label);
}

function observe(page, label) {
  page.on('pageerror', (error) => runtimeErrors.push(`${label}:pageerror:${error.message}`));
  page.on('response', (response) => {
    const request = response.request();
    const responsePath = new URL(response.url()).pathname;
    if (response.status() === 502 && responsePath === '/whatsapp/status') {
      expectedDegradations.push(`${label}:whatsapp_status_disconnected`);
      return;
    }
    if (
      response.status() >= 500
      && ['document', 'xhr', 'fetch'].includes(request.resourceType())
    ) {
      runtimeErrors.push(`${label}:http_${response.status()}:${response.url()}`);
    }
  });
}

async function goto(page, path) {
  const response = await page.goto(`${baseUrl}${path}`, {
    waitUntil: 'domcontentloaded',
    timeout: 30_000,
  });
  await page.waitForTimeout(450);
  return response;
}

async function assertNoHorizontalOverflow(page, label) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  check(overflow <= 1, `${label} has no horizontal overflow`, `overflow=${overflow}px`);
}

await mkdir(artifactDir, { recursive: true });
const browser = await chromium.launch({ headless: true });

try {
  const desktop = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: 'ar-EG',
    timezoneId: 'Africa/Cairo',
  });
  let page = await desktop.newPage();
  observe(page, 'desktop');

  let response = await goto(page, '/');
  check(response?.ok(), 'Landing document loads');
  check((await page.locator('h1').first().innerText()).trim().length > 12, 'Landing has a substantive hero');
  check(await page.locator('a[href="/signup"]').count() > 0, 'Landing exposes a signup CTA');
  check(
    await page.locator('[dir="rtl"]').count() > 0,
    'Landing exposes an RTL document region',
  );
  await assertNoHorizontalOverflow(page, 'Desktop landing');
  await page.screenshot({ path: join(artifactDir, 'landing-desktop.png'), fullPage: true });

  for (const [path, label] of [
    ['/signup', 'Signup'],
    ['/terms', 'Terms'],
    ['/privacy', 'Privacy'],
  ]) {
    response = await goto(page, path);
    check(response?.ok(), `${label} document loads`);
    check(await page.locator('h1').count() === 1, `${label} has one primary heading`);
    await assertNoHorizontalOverflow(page, label);
  }
  await goto(page, '/signup');
  check(await page.locator('input[type="checkbox"]').count() === 1, 'Signup requires one legal consent control');
  await page.screenshot({ path: join(artifactDir, 'signup-desktop.png'), fullPage: true });

  await goto(page, '/inbox');
  check(new URL(page.url()).pathname === '/login', 'Unauthenticated inbox redirects to login');

  if (accessToken) {
    await desktop.addCookies(
      [...new Set([baseUrl, apiUrl])].map((url) => ({
        name: 'access_token',
        value: accessToken,
        url,
        httpOnly: true,
        sameSite: 'Lax',
      })),
    );
    await page.close();
    page = await desktop.newPage();
    observe(page, 'authenticated-desktop');

    await goto(page, '/dashboard');
    check(
      new URL(page.url()).pathname === '/dashboard',
      'Authenticated dashboard opens',
      `final_url=${page.url()}`,
    );
    check(await page.locator('h1').count() === 1, 'Dashboard has one primary heading');
    await page.screenshot({ path: join(artifactDir, 'dashboard-desktop.png'), fullPage: true });

    const recoveryAction = page.getByRole('button').filter({ hasText: 'Evidence-bound customer' }).first();
    check(await recoveryAction.count() === 1, 'Dashboard renders the evidence-bound recovery item');
    if (await recoveryAction.count()) {
      await Promise.all([
        page.waitForURL(/\/inbox\/[^/]+$/, { timeout: 10_000 }),
        recoveryAction.click(),
      ]);
      check(
        /\/inbox\/[^/]+$/.test(new URL(page.url()).pathname),
        'Recovery item opens the canonical customer workspace',
      );
      await page.locator('textarea[aria-label="محرر الرد اليدوي"]').waitFor({
        state: 'visible',
        timeout: 10_000,
      }).catch(() => {});
      check(await page.locator('textarea[aria-label="محرر الرد اليدوي"]').count() === 1, 'Recovery workspace exposes the manual composer');
      check(await page.locator('section[aria-label="المتابعات النشطة"]').count() === 1, 'Recovery workspace renders the durable follow-up');
      check(await page.getByRole('button', { name: 'اكتملت' }).count() === 1, 'Follow-up exposes complete action');
      check(await page.getByRole('button', { name: 'تأجيل 24 ساعة' }).count() === 1, 'Follow-up exposes snooze action');
      check(await page.getByRole('button', { name: 'تجاهل' }).count() >= 1, 'Follow-up exposes dismiss action');
      check(await page.getByText('اقتراحات VELOR (لن يتم إرسالها تلقائيًا)').count() === 1, 'Workspace renders a source-linked suggestion');
      const insertSuggestion = page.getByRole('button', { name: 'إدراج' }).first();
      check(await insertSuggestion.count() === 1, 'Suggestion exposes insert without implying send');
      if (await insertSuggestion.count()) {
        await insertSuggestion.click();
        check(
          (await page.locator('textarea[aria-label="محرر الرد اليدوي"]').inputValue()).trim().length > 0,
          'Suggestion insertion preserves an editable draft',
        );
      }
      await page.waitForTimeout(500);
      const impactProbe = await page.evaluate(async () => {
        const result = await fetch('/api/v1/operations/recovery-impact?days=30&channel=web');
        return result.ok ? (await result.json()).data : null;
      });
      check(impactProbe?.metrics?.unique_active_opportunities_shown?.value >= 1, 'Rendered opportunity is measured once');
      check(impactProbe?.metrics?.unique_opportunities_opened?.value >= 1, 'Opened opportunity is measured');
      check(impactProbe?.metrics?.owner_actions_started?.value >= 1, 'Workspace owner action is measured');
      check(impactProbe?.metrics?.suggestion_insertions?.value >= 1, 'Suggestion insertion is measured separately from send');
      check(
        Object.values(impactProbe?.financial_outcomes || {}).every((item) => item?.value === null),
        'Browser-visible impact keeps disconnected financial outcomes null',
      );
      await page.screenshot({ path: join(artifactDir, 'recovery-workspace-desktop.png'), fullPage: true });
    }

    await goto(page, '/analytics');
    check(new URL(page.url()).pathname === '/analytics', 'Authenticated Analytics opens');
    check(await page.getByText('Recovery Impact').count() >= 1, 'Analytics renders Recovery Impact in the existing surface');
    check(await page.getByText(/النتائج المالية: غير متصلة/).count() >= 1, 'Analytics labels financial outcomes as disconnected');
    await page.screenshot({ path: join(artifactDir, 'recovery-impact-desktop.png'), fullPage: true });

    await goto(page, '/inbox');
    check(
      new URL(page.url()).pathname === '/inbox',
      'Canonical inbox route opens',
      `final_url=${page.url()}`,
    );
    check(await page.locator('textarea').count() === 0, 'Inbox list is read-only');
    await page.screenshot({ path: join(artifactDir, 'inbox-desktop.png'), fullPage: true });

    const openWorkspace = page.getByRole('button', { name: /فتح مساحة العميل/ }).first();
    if (await openWorkspace.count()) {
      await Promise.all([
        page.waitForURL(/\/inbox\/[^/]+$/, { timeout: 10_000 }),
        openWorkspace.click(),
      ]);
      check(
        /\/inbox\/[^/]+$/.test(new URL(page.url()).pathname),
        'Conversation opens on canonical detail route',
      );
      await page.locator('textarea[aria-label="محرر الرد اليدوي"]').waitFor({
        state: 'visible',
        timeout: 10_000,
      }).catch(() => {});
      check(
        await page.locator('textarea').count() >= 1,
        'Conversation detail exposes the customer composer',
      );
      await page.screenshot({
        path: join(artifactDir, 'conversation-desktop.png'),
        fullPage: true,
      });
    }
  }

  await desktop.close();

  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    isMobile: true,
    locale: 'ar-EG',
    timezoneId: 'Africa/Cairo',
  });
  const mobilePage = await mobile.newPage();
  observe(mobilePage, 'mobile');
  response = await goto(mobilePage, '/');
  check(response?.ok(), 'Mobile landing document loads');
  check(await mobilePage.locator('h1').count() === 1, 'Mobile landing has one primary heading');
  await assertNoHorizontalOverflow(mobilePage, 'Mobile landing');
  await mobilePage.screenshot({ path: join(artifactDir, 'landing-mobile.png'), fullPage: true });
  await mobile.close();
} finally {
  await browser.close();
}

for (const runtimeError of runtimeErrors) {
  failures.push(runtimeError);
}

const summary = {
  status: failures.length ? 'failed' : 'passed',
  checks: checks.length,
  passed: checks.filter((item) => item.passed).length,
  failed: failures.length,
  authenticated_workspace_checked: Boolean(accessToken),
  expected_degradations: [...new Set(expectedDegradations)],
  failures,
};
console.log(JSON.stringify(summary));
if (failures.length) process.exitCode = 1;
