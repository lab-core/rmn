// Temporary fixes to ngx-extended-pdf-viewer 31.0.0-alpha.1, applied to
// node_modules after every install (package.json "postinstall"): local
// installs, the CI and both Dockerfiles get the same viewer.
//
// They are submitted upstream (stephanrauh/pdf.js for the bleeding-edge
// bundle, stephanrauh/ngx-extended-pdf-viewer for the undo/redo buttons);
// drop each one when a release ships it. A replacement whose original text
// is gone (another version) stops the install, so a bump cannot silently
// ship the viewer without them, or with them half applied.
//
// - eraser on a rotated page (/Rotate 90 or 270, our scanned pages): the
//   eraser area was shrunk and shifted, and its cursor drawn away from the
//   pointer;
// - eraser on a drawing saved with another rotation than its page (the
//   annotations of the previous viewer): the cut drawing was redrawn turned;
// - restored drawings were recorded twice in the undo history, so every
//   other undo did nothing;
// - undo/redo buttons only enabled while a tool is active, although pdf.js
//   undoes as well without one.
//
// The bleeding-edge viewer is patched in its readable build and copied over
// the minified one, which is the file the viewer loads by default. The -es5
// build, loaded by browsers too old for the modern one, is left as it is.

import { copyFileSync, existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = join(dirname(fileURLToPath(import.meta.url)), '..');
const root = join(app, 'node_modules', 'ngx-extended-pdf-viewer');
const VERSION = '31.0.0-alpha.1';
const VIEWER = 'bleeding-edge/viewer-6.3.1315.mjs';
const VIEWER_MIN = 'bleeding-edge/viewer-6.3.1315.min.mjs';
const FESM = 'fesm2022/ngx-extended-pdf-viewer.mjs';

const patches = {
  [VIEWER]: [
    {
      what: 'eraser area covers its layer, whatever the page rotation',
      from: `    if (this.div) {
      this.div.style.pointerEvents = "auto";
      this.div.style.zIndex = "1000";`,
      to: `    if (this.div) {
      this.div.removeAttribute("data-editor-rotation");
      for (const [k, v] of [["left", "0"], ["top", "0"], ["width", "100%"], ["height", "100%"], ["max-width", "none"], ["max-height", "none"]]) {
        this.div.style.setProperty(k, v, "important");
      }
      this.div.style.pointerEvents = "auto";
      this.div.style.zIndex = "1000";`,
    },
    {
      what: 'eraser cursor placed in the rotated layer frame',
      from: `  const radius = _EraserEditor._thickness / 2;
  const x = event.clientX - rect.left - radius;
  const y = event.clientY - rect.top - radius;`,
      to: `  const radius = _EraserEditor._thickness / 2;
  const sx = event.clientX - rect.left, sy = event.clientY - rect.top;
  let u = sx, v = sy;
  switch (this.parentRotation) {
    case 90: u = sy; v = rect.width - sx; break;
    case 180: u = rect.width - sx; v = rect.height - sy; break;
    case 270: u = rect.height - sy; v = sx; break;
  }
  const x = u - radius;
  const y = v - radius;`,
    },
    {
      what: 'an erased drawing keeps its rotation (undo)',
      from: `      ink_classPrivateFieldSet(_hasBeenErased, this, wasErased);
      this._addOutlines({
        drawOutlines: oldOutline,
        drawId: this._drawId,
        drawingOptions
      });
    };`,
      to: `      ink_classPrivateFieldSet(_hasBeenErased, this, wasErased);
      this._addOutlines({
        drawOutlines: oldOutline,
        drawId: this._drawId,
        drawingOptions
      });
      this.rotate();
    };`,
    },
    {
      what: 'an erased drawing keeps its rotation (erase)',
      from: `      ink_classPrivateFieldSet(_hasBeenErased, this, true);
      this._addOutlines({
        drawOutlines: newOutlines,
        drawId: this._drawId,
        drawingOptions
      });
    };`,
      to: `      ink_classPrivateFieldSet(_hasBeenErased, this, true);
      this._addOutlines({
        drawOutlines: newOutlines,
        drawId: this._drawId,
        drawingOptions
      });
      this.rotate();
    };`,
    },
    {
      what: 'a restored drawing or highlight is one undo step, not two',
      count: 2,
      from: `    if (!this.annotationElementId) {
      this.parent.addUndoableEditor(this);
    }`,
      to: `    if (!this.annotationElementId && !this._uiManager.isRestoringAnnotations) {
      this.parent.addUndoableEditor(this);
    }`,
    },
  ],
  [FESM]: [
    {
      what: 'undo button enabled without an active tool',
      from: 'this.canUndo = isEditing && !!details.hasSomethingToUndo;',
      to: 'this.canUndo = !!details.hasSomethingToUndo;',
    },
    {
      what: 'redo button enabled without an active tool',
      from: 'this.canRedo = isEditing && !!details.hasSomethingToRedo;',
      to: 'this.canRedo = !!details.hasSomethingToRedo;',
    },
  ],
};

function fail(message) {
  console.error(`patch-pdf-viewer: ${message}`);
  process.exit(1);
}

const count = (text, part) => text.split(part).length - 1;

if (!existsSync(root)) {
  fail(`${root} not found: install ngx-extended-pdf-viewer first`);
}
const installed = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version;
if (installed !== VERSION) {
  fail(`written for ngx-extended-pdf-viewer ${VERSION}, found ${installed}: ` +
       'drop the fixes the new version ships and port the others');
}

let patched = false;
for (const [file, fixes] of Object.entries(patches)) {
  const path = join(root, file);
  let text = readFileSync(path, 'utf8');
  for (const { what, from, to, count: expected = 1 } of fixes) {
    if (count(text, to) === expected) {
      continue;  // already applied (a second install over the same tree)
    }
    if (count(text, from) !== expected) {
      fail(`${file}: cannot apply "${what}", its original text is not there`);
    }
    text = text.split(from).join(to);
    patched = true;
    console.log(`patch-pdf-viewer: ${what}`);
  }
  writeFileSync(path, text);
}
copyFileSync(join(root, VIEWER), join(root, VIEWER_MIN));
// the Angular build cache keeps the library as compiled before the patch
if (patched) {
  rmSync(join(app, '.angular', 'cache'), { recursive: true, force: true });
}
