// Takes the screenshots and the animations of the user guide
// (services/webapp/ng/src/assets/guide/img) by going through a whole task on
// a local stack: template, new task, matricules, grading, finalisation.
//
// The copies are the fictitious ones of make_demo_data.py; nothing here may
// ever point at real student data. See README.md for the full procedure.
//
//   RMN_URL=http://127.0.0.1:8090 RMN_USER=... RMN_PASSWORD=... node capture.mjs
//
// Each animation is written as numbered frames plus a manifest of their
// durations; frames_to_gif.py turns them into GIFs.

import { chromium } from 'playwright';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..', '..');
const URL = (process.env.RMN_URL || 'http://127.0.0.1:8090').replace(/\/$/, '');
const USER = process.env.RMN_USER || 'prof.demo@exemple.invalid';
const PASSWORD = process.env.RMN_PASSWORD;
const DEMO = resolve(process.env.DEMO_DIR || join(HERE, 'demo'));
const IMG = resolve(process.env.IMG_DIR || join(REPO, 'services/webapp/ng/src/assets/guide/img'));
const FRAMES = join(HERE, 'frames');
const TASK = 'Démo MTH1102 Final';
const COVER_TEMPLATE = 'Example: Page de couverture';
const INNER_TEMPLATE = 'Example: Page intérieure';
const POINTS = [9, 8, 9, 10, 9];
const VIEWPORT = {width: 1440, height: 900};

if (!PASSWORD) {
  console.error('RMN_PASSWORD is required (the password of RMN_USER)');
  process.exit(2);
}

const grades = JSON.parse(readFileSync(join(DEMO, 'grades.json'), 'utf8'));

/** Frames of one animation, each shown for its own duration. */
class Animation {
  constructor(page, name) {
    this.page = page;
    this.name = name;
    this.frames = [];
    this.dir = join(FRAMES, name);
    rmSync(this.dir, {recursive: true, force: true});
    mkdirSync(this.dir, {recursive: true});
  }

  async frame(ms = 1200) {
    const file = join(this.dir, `${String(this.frames.length).padStart(3, '0')}.png`);
    await this.page.screenshot({path: file});
    this.frames.push({file, ms});
  }

  save() {
    writeFileSync(join(this.dir, 'manifest.json'), JSON.stringify(this.frames, null, 1));
    return this.frames;
  }
}

/** A red ring where the next click lands, so a GIF shows what was clicked. */
async function pointAt(page, locator) {
  const box = await locator.boundingBox();
  if (!box) {
    return;
  }
  await page.evaluate(({x, y}) => {
    let ring = document.getElementById('docs-capture-pointer');
    if (!ring) {
      ring = document.createElement('div');
      ring.id = 'docs-capture-pointer';
      Object.assign(ring.style, {
        position: 'fixed', width: '34px', height: '34px', marginLeft: '-17px', marginTop: '-17px',
        border: '4px solid #e53935', borderRadius: '50%', zIndex: 100000, pointerEvents: 'none',
        boxShadow: '0 0 0 4px rgba(229, 57, 53, 0.25)',
      });
      document.body.appendChild(ring);
    }
    ring.style.left = `${x}px`;
    ring.style.top = `${y}px`;
    ring.style.display = 'block';
  }, {x: box.x + box.width / 2, y: box.y + box.height / 2});
}

async function hidePointer(page) {
  await page.evaluate(() => {
    const ring = document.getElementById('docs-capture-pointer');
    if (ring) {
      ring.style.display = 'none';
    }
  });
}

/** Point at `locator`, record a frame if asked, then click it. */
async function click(page, locator, animation = null, ms = 900) {
  await locator.scrollIntoViewIfNeeded();
  await pointAt(page, locator);
  if (animation) {
    await animation.frame(ms);
  }
  await locator.click();
  await hidePointer(page);
}

async function shot(page, name, options = {}) {
  await hidePointer(page);
  await page.screenshot({path: join(IMG, name), ...options});
  console.log('  ', name);
}

async function settle(page, ms = 800) {
  await page.waitForLoadState('networkidle').catch(() => undefined);
  await page.waitForTimeout(ms);
}

async function login(page) {
  // one login only: nginx rate-limits /api/users/login
  const form = new FormData();
  form.append('username', USER);
  form.append('password', PASSWORD);
  const response = await fetch(`${URL}/api/users/login`, {method: 'POST', body: form});
  if (!response.ok) {
    throw new Error(`login failed: ${response.status} ${await response.text()}`);
  }
  const user = (await response.json()).response;
  await page.goto(`${URL}/login`);
  // what UserService.login stores
  await page.evaluate((user) => {
    localStorage.setItem('user_id', user.username);
    localStorage.setItem('role', user.role);
    localStorage.setItem('token', user.token);
    localStorage.setItem('saveVerifiedImages', JSON.stringify(user.saveVerifiedImages));
    localStorage.setItem('moodleStructureInd', JSON.stringify(user.moodleStructureInd));
  }, user);
}

async function selectOption(page, label, option) {
  await page.locator('mat-form-field').filter({hasText: label}).locator('mat-select').click();
  await page.locator('mat-option').filter({hasText: option}).first().click();
}

/** The template editor: a template drawn on the default cover page. */
async function templateEditor(page) {
  console.log('template editor');
  await page.goto(`${URL}/templates`);
  await settle(page);
  await shot(page, 'templates.png');

  const gif = new Animation(page, 'template-editor');
  await click(page, page.getByRole('button', {name: 'Créer un nouveau template'}), gif);
  await page.locator('#file-input').setInputFiles(
    join(REPO, 'services/server/default_templates/couverture/page_couverture_exam.pdf'));
  await settle(page, 500);
  await gif.frame(1500);
  await click(page, page.getByRole('button', {name: 'Confirmer'}), gif);
  await page.locator('#cv').waitFor();
  await settle(page, 2000);
  await page.locator('#template_name').fill('Ma page de garde');
  await gif.frame(1200);

  // the page is drawn in #cv: PDF points to screen pixels
  const canvas = await page.locator('#cv').boundingBox();
  const at = (x, y) => [canvas.x + x / 612 * canvas.width, canvas.y + y / 792 * canvas.height];
  const drag = async (from, to) => {
    await page.mouse.move(...at(...from));
    await page.mouse.down();
    for (let i = 1; i <= 6; i++) {
      const x = from[0] + (to[0] - from[0]) * i / 6;
      const y = from[1] + (to[1] - from[1]) * i / 6;
      await page.mouse.move(...at(x, y));
      if (i % 3 === 0) {
        await gif.frame(250);
      }
    }
    await page.mouse.up();
  };

  await click(page, page.locator('mat-button-toggle').filter({hasText: 'Rectangles'}), gif);
  await click(page, page.getByRole('button', {name: 'Identification'}), gif);
  await drag([234, 199], [387, 225]);
  await gif.frame(1200);
  await click(page, page.getByRole('button', {name: 'Questions'}), gif);
  await drag([484, 180], [606, 352]);
  await settle(page, 2500);  // the server counts the boxes of the rectangle
  await gif.frame(2500);
  gif.save();
  // the demo task uses the default templates: this one is not kept
  await page.goto(`${URL}/templates`);
}

/** The new task wizard, with the Moodle zip and worksheet of the demo. */
async function newTask(page) {
  console.log('new task');
  const gif = new Animation(page, 'nouvelle-tache');
  await page.goto(`${URL}/new-exam-correction`);
  await settle(page);
  await page.locator('#name-field input').fill(TASK);
  await gif.frame(1500);
  // only the buttons of the open step are visible, hence found by role
  await click(page, page.getByRole('button', {name: 'Suivant'}), gif);

  await selectOption(page, 'Template pour la page de garde', COVER_TEMPLATE);
  await selectOption(page, 'Template pour les pages suivantes', INNER_TEMPLATE);
  await settle(page, 500);
  await gif.frame(1800);
  await shot(page, 'assistant-2.png');
  await click(page, page.getByRole('button', {name: 'Suivant'}), gif);

  await page.locator('input[type=file][accept=".zip"]').setInputFiles(join(DEMO, 'copies-moodle.zip'));
  // every matricule to confirm, so that the guide can show how
  await page.locator('label').filter({hasText: 'Valider tous les matricules'}).locator('input').check();
  const rows = page.locator('.questions-table tbody tr');
  for (let i = 0; i < POINTS.length; i++) {
    const inputs = rows.nth(i).locator('input[type=number]');
    await inputs.nth(0).fill('1');
    await inputs.nth(0).dispatchEvent('change');
    await inputs.nth(1).fill(String(POINTS[i]));
    await inputs.nth(1).dispatchEvent('change');
  }
  await settle(page, 500);
  await gif.frame(2500);
  await shot(page, 'assistant-3.png');
  await click(page, page.getByRole('button', {name: 'Suivant'}), gif);

  await page.locator('input[type=file][accept=".csv"]').setInputFiles(join(DEMO, 'formulaire-evaluation.csv'));
  await settle(page, 800);
  await gif.frame(1800);
  await shot(page, 'assistant-4.png');
  await click(page, page.getByRole('button', {name: 'Commencer'}), gif, 1200);
  await page.waitForURL(/tasks-history|\/$/, {timeout: 120000});
  await settle(page, 1500);
  await gif.frame(2000);
  gif.save();
}

/** Wait until the row of the demo task shows `status`. */
async function waitForStatus(page, status, timeout = 15 * 60000) {
  const row = page.locator('tr').filter({hasText: TASK}).first();
  await row.filter({hasText: status}).waitFor({timeout});
}

/** The pdf of the current copy is on screen and the page takes keys again. */
async function copyLoaded(page) {
  await page.locator('#overlay').waitFor({state: 'detached', timeout: 60000}).catch(() => undefined);
  await settle(page, 600);
}

async function openDashboard(page) {
  await page.goto(`${URL}/tasks-history`);
  await settle(page);
  await page.locator('tr').filter({hasText: TASK}).first().getByText(TASK).click();
  await page.waitForURL(/dashboard/);
  await settle(page, 1500);
}

/** Confirm every matricule; they are all in the worksheet of the demo. */
async function matricules(page) {
  console.log('matricules');
  await openDashboard(page);
  const gif = new Animation(page, 'matricules');
  await click(page, page.getByRole('button', {name: 'Verifier'}), gif);
  await page.waitForURL(/matricule-validation/);
  await settle(page, 2500);
  const tiles = page.locator('.files-list-container .file-container');
  const count = await tiles.count();
  for (let i = 0; i < count; i++) {
    await tiles.nth(i).click();
    await copyLoaded(page);
    if (i < 3) {
      await gif.frame(1400);
    }
    await page.keyboard.press('Enter');
    // saved once its tile turns green
    await tiles.nth(i).locator('.validated-copy').waitFor({timeout: 30000});
  }
  await settle(page, 1500);
  await gif.frame(2000);
  gif.save();
}

/** Grade every question of every copy, as a teacher typing the grades. */
async function grading(page) {
  console.log('grading');
  await openDashboard(page);
  // the reader works in the background: wait until every question is read
  await page.waitForFunction(() => !document.body.innerText.includes('Lecture en cours')
    && !document.body.innerText.includes('Lecture à faire'), null, {timeout: 10 * 60000}).catch(() => undefined);
  await openDashboard(page);

  for (let q = 0; q < POINTS.length; q++) {
    await openDashboard(page);
    const gif = q === 0 ? new Animation(page, 'correction') : null;
    const row = page.locator('tbody tr').filter({hasText: `Q${q + 1}`}).first();
    await click(page, row.getByRole('button', {name: 'Corriger'}), gif);
    await page.waitForURL(/task-validation/);
    await settle(page, 3000);
    const tiles = page.locator('.files-list-container .file-container');
    const count = await tiles.count();
    for (let i = 0; i < count; i++) {
      // each copy by its tile: the page reopens on the copy seen last
      await tiles.nth(i).click();
      await copyLoaded(page);
      const score = page.locator('#score');
      // the demo grades are invented: which copy gets which does not matter
      const key = Object.values(grades);
      await score.fill(String(key[i % key.length][q]));
      if (gif && i < 3) {
        await score.hover();
        await gif.frame(1600);
      }
      await score.focus();
      await page.keyboard.press('Enter');
      // saved once its tile turns green
      await tiles.nth(i).locator('.validated-copy').waitFor({timeout: 30000});
    }
    await copyLoaded(page);
    if (gif) {
      await settle(page, 1500);
      await gif.frame(2000);
      gif.save();
    }
  }
}

async function finalize(page) {
  console.log('finalize');
  await openDashboard(page);
  await shot(page, 'tableau-de-bord.png');
  await page.getByRole('button', {name: 'Finaliser'}).click();
  await page.goto(`${URL}/tasks-history`);
  await waitForStatus(page, 'Archivée');
  await settle(page, 1000);
  await shot(page, 'taches.png');
  await openDashboard(page);
  await page.getByRole('button', {name: 'Télécharger copies'}).click();
  await settle(page, 1500);
  await shot(page, 'fichiers.png');
}

async function main() {
  mkdirSync(IMG, {recursive: true});
  const browser = await chromium.launch();
  const context = await browser.newContext({viewport: VIEWPORT, deviceScaleFactor: 1, locale: 'fr-CA'});
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  try {
    await login(page);
    const steps = (process.env.STEPS || 'template,task,matricules,grading,finalize').split(',');
    if (steps.includes('template')) {
      await templateEditor(page);
    }
    if (steps.includes('task')) {
      await newTask(page);
    }
    if (steps.includes('matricules') || steps.includes('grading')) {
      await page.goto(`${URL}/tasks-history`);
      console.log('waiting for the copies to be ready');
      await waitForStatus(page, 'Prêt à la correction');
    }
    if (steps.includes('matricules')) {
      await matricules(page);
    }
    if (steps.includes('grading')) {
      await grading(page);
    }
    if (steps.includes('finalize')) {
      await finalize(page);
    }
  } catch (error) {
    await page.screenshot({path: join(FRAMES, 'error.png')});
    throw error;
  } finally {
    await browser.close();
  }
}

await main();
