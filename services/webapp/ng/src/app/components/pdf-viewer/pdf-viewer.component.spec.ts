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

/** The part of ngx-extended-pdf-viewer's service the component talks to. */
class FakePdfViewerService {
  annotations: any[] = [];
  editorInkColor: string;
  editorInkThickness: number;
  editorFontColor: string;
  editorFontSize: number;
  getCurrentDocumentAsBlob = jasmine.createSpy('getCurrentDocumentAsBlob')
    .and.resolveTo(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
  renderPage = jasmine.createSpy('renderPage').and.resolveTo(undefined);
  addEditorAnnotation = jasmine.createSpy('addEditorAnnotation').and.callFake((annotations: any[]) => {
    this.annotations.push(...annotations);
    return Promise.resolve();
  });
  getSerializedAnnotations() { return structuredClone(this.annotations); }
  isRenderQueueEmpty() { return true; }
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

    await component.onAnnotationEdited();  // a stroke, an erasing, an undo...
    expect(component.pdfModified).toBeTrue();
    expect(await component.getRenderedPdfFile('b.pdf', true)).toBeDefined();
    ngx.annotations = [{ annotationType: 3 }];
    expect(component.getAnnotations()).toEqual([{ annotationType: 3 } as any]);
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
