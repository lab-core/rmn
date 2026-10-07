import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NgxExtendedPdfViewerModule, NgxExtendedPdfViewerService, pdfDefaultOptions } from 'ngx-extended-pdf-viewer';

import { PDFViewerComponent } from './pdf-viewer.component';
import { MATERIAL_MODULES, waitUntil } from '../../testing/helpers';

/** A drawing as pdf.js 6 serialises it. */
function stroke(pageIndex = 0): any {
  return { annotationType: 15, color: [255, 0, 0], thickness: 2, opacity: 1, pageIndex, rotation: 0,
           rect: [10, 40, 90, 60], paths: { lines: [[NaN, NaN, NaN, NaN, 10, 50]], points: [[10, 50]] } };
}

describe('PDFViewerComponent', () => {
  let fixture: ComponentFixture<PDFViewerComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [PDFViewerComponent],
      imports: [...MATERIAL_MODULES, NgxExtendedPdfViewerModule],
    });
    fixture = TestBed.createComponent(PDFViewerComponent);
    spyOn(console, 'log');
  });

  it('loads the bleeding-edge bundle, the one with the eraser and undo/redo', () => {
    expect(pdfDefaultOptions.assetsFolder).toBe('bleeding-edge');
  });

  it('tells the user when the copy has no pdf', () => {
    fixture.componentRef.setInput('pdfUrl', undefined);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain("Cette copie n'est pas disponible.");
    expect(fixture.nativeElement.querySelector('ngx-extended-pdf-viewer')).toBeNull();
  });

  it('resets its state when the pdf changes', () => {
    const component = fixture.componentInstance;
    component.pdfModified = true;
    component.pdfRendered = true;
    component.ngOnChanges();
    expect(component.pdfModified).toBeFalse();
    expect(component.pdfRendered).toBeFalse();
  });
});

/** A pdf.js editor in the annotation storage, as far as the component looks at it. */
class FakeEditor {
  deleted = false;
  constructor(public data: any, public annotationElementId: string = null, public changed = false) {}
  get pageIndex() { return this.data.pageIndex; }
  /** pdf.js: an annotation of the file serializes only once changed, unless copied. */
  serialize(isForCopying: boolean) {
    if (!isForCopying && this.annotationElementId && !this.changed && !this.deleted) {
      return null;
    }
    if (this.deleted) {
      return { id: this.annotationElementId, deleted: true, pageIndex: this.pageIndex };
    }
    return { ...structuredClone(this.data), id: this.annotationElementId || 'pdfjs_internal_editor_0', isCopy: isForCopying };
  }
  remove() { this.deleted = true; }
}

/** The part of ngx-extended-pdf-viewer's service the component talks to. */
class FakePdfViewerService {
  annotations: any[] = [];
  storage = new Map<string, FakeEditor>();
  modes: number[] = [];
  PDFViewerApplication = {
    pdfDocument: { annotationStorage: this.storage },
    pdfViewer: { annotationEditorMode: 0 },
  };
  editorInkColor: string;
  editorInkThickness: number;
  editorFontColor: string;
  editorFontSize: number;
  getCurrentDocumentAsBlob = jasmine.createSpy('getCurrentDocumentAsBlob')
    .and.resolveTo(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
  renderPage = jasmine.createSpy('renderPage').and.resolveTo(undefined);
  addEditorAnnotation = jasmine.createSpy('addEditorAnnotation').and.callFake((annotations: any[]) => {
    this.annotations.push(...annotations);
    annotations.forEach(a => this.storage.set(`editor_${this.storage.size}`, new FakeEditor(a)));
    return Promise.resolve();
  });
  switchAnnotationEdtorMode(mode: number) {
    this.modes.push(mode);
    this.PDFViewerApplication.pdfViewer.annotationEditorMode = mode;
  }
  isRenderQueueEmpty() { return true; }
}

/** A stroke in the pdf file itself, pdf object 14R. */
function fileStroke(changed = false) {
  return new FakeEditor({ ...stroke(), rect: [1.23456, 2, 3, 4] }, '14R', changed);
}

describe('PDFViewerComponent annotations', () => {
  let fixture: ComponentFixture<PDFViewerComponent>;
  let component: PDFViewerComponent;
  let ngx: FakePdfViewerService;

  beforeEach(() => {
    ngx = new FakePdfViewerService();
    TestBed.configureTestingModule({
      declarations: [PDFViewerComponent],
      imports: [...MATERIAL_MODULES, NgxExtendedPdfViewerModule],
      providers: [{ provide: NgxExtendedPdfViewerService, useValue: ngx }],
    });
    fixture = TestBed.createComponent(PDFViewerComponent);
    component = fixture.componentInstance;
    (component as any).timeout = 0;  // the viewer's settle delays, not needed here
    fixture.componentRef.setInput('pdfUrl', undefined);  // no real viewer
    fixture.detectChanges();
  });

  it('asks the text editor whether the user is typing, if there is one', () => {
    expect(component.isWriting()).toBeFalse();  // toolbar hidden: no text editor
    component.pdfTextEditor = { isSelected: true } as any;
    expect(component.isWriting()).toBeTrue();
  });

  it('returns the annotated pdf only when something was changed, if asked so', async () => {
    expect(await component.getRenderedPdfFile('a.pdf', true)).toBeUndefined();
    expect(ngx.getCurrentDocumentAsBlob).not.toHaveBeenCalled();

    const file = await component.getRenderedPdfFile('a.pdf');
    expect(file.name).toBe('a.pdf');
    expect(file.type).toBe('application/pdf');

    ngx.storage.set('pdf', fileStroke());  // the annotations of the file are not a change
    await component.onPageRendered();
    await waitUntil(() => !(component as any).loading);
    expect(component.isModified()).toBeFalse();
    expect(await component.getRenderedPdfFile('b.pdf', true)).toBeUndefined();

    ngx.storage.set('new', new FakeEditor(stroke()));  // a stroke, an erasing...
    expect(component.isModified()).toBeTrue();
    expect(await component.getRenderedPdfFile('b.pdf', true)).toBeDefined();
  });

  it('ends the pen session before saving, so the last strokes are in', async () => {
    await component.onPageRendered();
    await waitUntil(() => !(component as any).loading);
    const layer = { commitOrRemove: jasmine.createSpy('commitOrRemove') };
    (ngx.PDFViewerApplication.pdfViewer as any)._pages = [{ annotationEditorLayer: { annotationEditorLayer: layer } }, {}];
    await component.getRenderedPdfFile('a.pdf');
    expect(layer.commitOrRemove).toHaveBeenCalled();  // as Escape does, no tool switch
    expect(ngx.modes).toEqual([]);
  });

  it('saves what changed: its drawings, and the annotations of the file it replaced or erased', () => {
    expect(component.getAnnotations()).toEqual([]);
    ngx.storage.set('a', new FakeEditor({ ...stroke(), rect: [1.23456, 2, 3, 4] }));  // drawn in the app
    ngx.storage.set('b', fileStroke());                                               // in the file, untouched
    ngx.storage.set('c', fileStroke(true));                                           // in the file, erased in part
    const erased = fileStroke();
    erased.annotationElementId = '20R';
    erased.remove();                                                                  // in the file, erased
    ngx.storage.set('d', erased);
    ngx.storage.set('e', { value: 'a form field' } as any);

    const saved: any[] = component.getAnnotations();
    expect(saved.length).toBe(4);
    expect(saved[0].rect).toEqual([1.23, 2, 3, 4]);  // coordinates to 1/100 pt
    expect(saved[0].id).toBeUndefined();             // a new annotation on restore, not a copy of this one
    expect(saved[0].isCopy).toBeUndefined();
    expect(saved[1]).toEqual({ id: '14R', deleted: true, pageIndex: 0 });
    expect(saved[2].annotationType).toBe(15);        // its new drawing
    expect(saved[3]).toEqual({ id: '20R', deleted: true, pageIndex: 0 });
  });

  it('restores them: removes the annotations of the file they replaced, then draws theirs', async () => {
    const original = fileStroke();
    ngx.storage.set('pdf', original);  // pdf.js turns it into an editor in an editor mode
    await component.renderAnnotations([{ id: '14R', deleted: true, pageIndex: 0 }, stroke()]);
    await component.onPageRendered();
    await waitUntil(() => !(component as any).loading);

    expect(original.deleted).toBeTrue();
    expect(ngx.addEditorAnnotation).toHaveBeenCalledTimes(1);
    expect(ngx.modes).toEqual([15, 0]);  // through the pen to reach the editors, back to no tool
    expect(component.isModified()).toBeFalse();  // opening a copy is not changing it
  });

  it('says whether something is written on the copy: the file\'s, minus erased, plus drawn', async () => {
    const pages = [[{ id: '5R', annotationType: 15 }], [{ id: '9R', annotationType: 2 }]];  // ink; a link
    (ngx.PDFViewerApplication.pdfDocument as any).numPages = 2;
    (ngx.PDFViewerApplication.pdfDocument as any).getPage = (n: number) =>
      Promise.resolve({ getAnnotations: () => Promise.resolve(pages[n - 1]) });
    expect(await component.hasAnnotations()).toBeTrue();   // the file's ink

    const erased = fileStroke();
    erased.annotationElementId = '5R';
    erased.remove();
    ngx.storage.set('pdf', erased);
    expect(await component.hasAnnotations()).toBeFalse();  // erased; a link is not writing

    ngx.storage.set('new', new FakeEditor(stroke()));
    expect(await component.hasAnnotations()).toBeTrue();   // drawn in the app
  });

  it('restores only the annotations of the copy shown, even when the user moves on fast', async () => {
    await component.renderAnnotations([stroke()]);   // copy A, left before it was drawn
    await component.ngOnChanges();                   // copy B
    await component.renderAnnotations([{ annotationType: 3, pageIndex: 0 } as any]);
    await component.onPageRendered();
    await waitUntil(() => !(component as any).loading);
    expect(ngx.annotations.map(a => a.annotationType)).toEqual([3]);
  });

  it('keeps the tool the user chose from one copy to the next', async () => {
    await component.onPageRendered();
    await waitUntil(() => !(component as any).loading);
    component.onEditorModeChanged({ mode: 103 } as any);  // the eraser

    await component.ngOnChanges();                         // the next copy
    component.onEditorModeChanged({ mode: 0 } as any);     // the viewer resets it on a new document
    ngx.PDFViewerApplication.pdfViewer.annotationEditorMode = 0;
    await component.onPageRendered();
    await waitUntil(() => !(component as any).loading);
    expect(ngx.modes).toEqual([103]);
  });

  it('a pencil touch on a page does not scroll while the pen is on, a finger does', () => {
    const page = document.createElement('div');
    page.className = 'page';
    fixture.nativeElement.appendChild(page);
    // Safari's Touch.touchType ("stylus" for the Apple Pencil): Chrome has none to build
    const move = (touchType: string) => {
      const event = new Event('touchmove', { bubbles: true, cancelable: true });
      Object.defineProperty(event, 'touches', { value: [{ touchType }] });
      page.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(move('stylus')).toBeFalse();  // no tool: the pencil scrolls
    ngx.PDFViewerApplication.pdfViewer.annotationEditorMode = 15;
    expect(move('stylus')).toBeTrue();
    expect(move('direct')).toBeFalse();  // the finger
    page.remove();
  });

  it('the tool goes back to the pointer type that owned it on the previous copy', async () => {
    let owner = 'pen';  // the stylus opened the pen
    const pointers = { claimFor: jasmine.createSpy('claimFor').and.callFake((t: string) => owner = t),
                       isSamePointerType: (t: string) => t === owner };
    (ngx.PDFViewerApplication.pdfViewer as any)._layerProperties = { annotationEditorUIManager: { currentPointers: pointers } };
    await component.onPageRendered();
    await waitUntil(() => !(component as any).loading);
    component.onEditorModeChanged({ mode: 15 } as any);
    await component.ngOnChanges();  // the next copy, "next" tapped with a finger
    owner = 'touch';                // pdf.js would give the pen to that finger
    ngx.PDFViewerApplication.pdfViewer.annotationEditorMode = 0;
    await component.onPageRendered();
    await waitUntil(() => !(component as any).loading);
    expect(pointers.claimFor).toHaveBeenCalledWith('pen');
    expect(owner).toBe('pen');
  });

  it('draws the saved annotations one by one once the first page is rendered', async () => {
    const loaded = jasmine.createSpy('loaded');
    component.onAnnotationsLoaded.subscribe(loaded);
    const legacy = { ...stroke(), paths: [{ bezier: [10, 50], points: [10, 50] }] };
    await component.renderAnnotations([legacy, stroke(), { annotationType: 3, pageIndex: 1 } as any], true);
    await component.renderAnnotations(undefined);
    expect(component.pdfAnnotations.length).toBe(2);

    await component.onPageRendered();
    await component.onPageRendered();  // the next pages change nothing
    await waitUntil(() => loaded.calls.count() > 0);

    expect(loaded).toHaveBeenCalledOnceWith(true);
    expect(ngx.renderPage.calls.allArgs()).toEqual([[0], [1]]);
    // one call per annotation, in order: undo takes them back one by one
    expect(ngx.addEditorAnnotation.calls.allArgs().map(([a]) => a.map(x => x.annotationType))).toEqual([[15], [3]]);
    expect(ngx.annotations.length).toBe(2);
    // the pdf.js 4 drawing is left out, the rest is restored
    expect(ngx.annotations.map(a => Array.isArray(a.paths))).toEqual([false, false]);
    expect(component.pdfAnnotations).toEqual([]);
    expect(component.pdfModified).toBeTrue();
    await waitUntil(() => component.pdfViewerInitialized);
    expect([ngx.editorInkColor, ngx.editorInkThickness, ngx.editorFontColor, ngx.editorFontSize]).toEqual(['#FF0000', 2, '#FF0000', 14]);

    await component.ngOnChanges();
    expect(component.pdfRendered).toBeFalse();
  });

  it('annotations given after the first render are drawn right away, as copies', async () => {
    component.pdfRendered = true;
    const given = stroke();
    await component.renderAnnotations([given]);
    await waitUntil(() => ngx.annotations.length === 1);
    expect(ngx.annotations[0]).not.toBe(given);  // the viewer never shares objects with the caller
    expect(ngx.annotations[0].pageIndex).toBe(0);
  });

  it('a document without annotations calls nothing', async () => {
    const loaded = jasmine.createSpy('loaded');
    component.onAnnotationsLoaded.subscribe(loaded);
    await component.onPageRendered();
    await waitUntil(() => loaded.calls.count() > 0);
    expect(ngx.addEditorAnnotation).not.toHaveBeenCalled();
  });

  it('keeps setting the editor colours until the viewer accepts them', async () => {
    let refusals = 1;
    Object.defineProperty(ngx, 'editorInkColor', {
      set: () => { if (refusals-- > 0) { throw new Error('not ready'); } },
      configurable: true,
    });
    await component.initializePdfViewer();
    expect(component.pdfViewerInitialized).toBeFalse();
    await waitUntil(() => component.pdfViewerInitialized);
    await component.initializePdfViewer();  // once is enough
  });
});
