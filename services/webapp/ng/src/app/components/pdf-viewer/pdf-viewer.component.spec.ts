import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NgxExtendedPdfViewerModule, NgxExtendedPdfViewerService } from 'ngx-extended-pdf-viewer';

import { AnnotationsChange, BezierAnnotation, BezierPath, EraserChange, PDFViewerComponent } from './pdf-viewer.component';
import { NotificationService } from 'src/app/services/notification.service';
import { MATERIAL_MODULES, notificationSpy, waitUntil } from '../../testing/helpers';

/** An ink annotation as pdf.js stores it: flat [y, x, y, x, ...] arrays. */
function ink(points: number[][], rect = [0, 0, 100, 100]): any {
  const flat = [];
  points.forEach(([x, y]) => flat.push(y, x));
  return { annotationType: 15, color: [0, 0, 0], thickness: 1, opacity: 1, pageIndex: 0,
           rect, paths: [{ points: flat, bezier: [] }] };
}

describe('BezierPath', () => {
  it('stores points as (x, y) and serialises them back as (y, x)', () => {
    const path = new BezierPath();
    path.pushPoint(1, 2);
    path.pushPoint(3, 4);
    path.pushBezierPoint(5, 6);
    expect(path.toObject()).toEqual({ points: [2, 1, 4, 3], bezier: [6, 5] });
  });

  it('a stroke of one or two points degenerates to its end points', () => {
    const path = new BezierPath();
    path.pushPoint(1, 1);
    path.pushPoint(5, 5);
    path.generateBezierPoints();
    expect(path.bezier).toEqual([[1, 1], [1, 1], [5, 5], [5, 5]]);
  });

  it('a longer stroke gets a control-point triplet per segment plus the end point', () => {
    const path = new BezierPath();
    [[0, 0], [2, 0], [4, 0], [6, 0], [8, 0]].forEach(([x, y]) => path.pushPoint(x, y));
    path.generateBezierPoints();
    // (n - 3) inner segments of (start + 2 controls), then start + 2 controls + end
    expect(path.bezier.length).toBe(2 * 3 + 4);
    expect(path.bezier[0]).toEqual([0, 0]);
    expect(path.bezier[path.bezier.length - 1]).toEqual([8, 0]);
    expect(path.bezier.every(([, y]) => y === 0)).toBeTrue();
  });
});

describe('BezierAnnotation', () => {
  it('round-trips an ink annotation without touching the original', () => {
    const original = ink([[10, 20], [30, 40], [50, 60]]);
    const annotation = new BezierAnnotation(original);

    expect(annotation.paths.length).toBe(1);
    expect(annotation.paths[0].points).toEqual([[10, 20], [30, 40], [50, 60]]);

    const back = annotation.getInkAnnotation();
    expect(back.paths[0].points).toEqual(original.paths[0].points);
    expect(back.paths[0].bezier.length).toBeGreaterThan(0);
    expect(original.paths[0].bezier).toEqual([]);  // structuredClone: no mutation
    expect(back.rect).toEqual([0, 0, 100, 100]);
  });

  it('computes a padded bounding rectangle from its points', () => {
    const annotation = new BezierAnnotation(ink([[10, 20], [30, 5]]));
    annotation.computeRectangle();
    // rect is [minY, minX, maxY, maxX] padded by [2, 2, 1, 1]
    expect(annotation.rect).toEqual([5 - 2, 10 - 2, 20 + 1, 30 + 1]);
  });

  it('keeps the previous rectangle when it has no points', () => {
    const annotation = new BezierAnnotation(ink([], [1, 2, 3, 4]));
    annotation.paths = [];
    annotation.computeRectangle();
    expect(annotation.rect).toEqual([1, 2, 3, 4]);
  });
});

describe('EraserChange and AnnotationsChange', () => {
  it('an eraser change starts from a snapshot and drops emptied annotations', () => {
    const change = new EraserChange([ink([[1, 1], [2, 2]]), ink([[3, 3], [4, 4]])]);
    expect(change.used).toBeFalse();
    expect(change.newAnnotations.length).toBe(2);
    change.newAnnotations[1].paths = [];  // fully erased
    expect(change.getInkAnnotations().length).toBe(1);
  });

  it('an annotations change is empty until something is recorded', () => {
    const change = new AnnotationsChange();
    expect(change.isEmpty()).toBeTrue();
    change.eraser = new EraserChange([]);
    expect(change.isEmpty()).toBeFalse();
  });
});

describe('PDFViewerComponent', () => {
  let fixture: ComponentFixture<PDFViewerComponent>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [PDFViewerComponent],
      imports: [...MATERIAL_MODULES, NgxExtendedPdfViewerModule],
      providers: [{ provide: NotificationService, useValue: notificationSpy() }],
    });
    fixture = TestBed.createComponent(PDFViewerComponent);
    spyOn(console, 'log');
  });

  it('reads the scale factor from the viewer element, integer zooms included', () => {
    const component = fixture.componentInstance;
    expect(component.getScaleFactor()).toBe(1);  // no viewer yet
    const viewer = document.createElement('div');
    viewer.id = 'viewer';
    document.body.appendChild(viewer);
    try {
      viewer.style.setProperty('--scale-factor', '1.5');
      expect(component.getScaleFactor()).toBe(1.5);
      // an integer zoom used to throw on every pointer move of the eraser
      viewer.style.setProperty('--scale-factor', '1');
      expect(component.getScaleFactor()).toBe(1);
      viewer.style.setProperty('--scale-factor', 'garbage');
      expect(component.getScaleFactor()).toBe(1);
    } finally {
      viewer.remove();
    }
  });

  it('tells the user when the copy has no pdf', () => {
    fixture.componentRef.setInput('pdfUrl', undefined);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain("Cette copie n'est pas disponible.");
    expect(fixture.nativeElement.querySelector('ngx-extended-pdf-viewer')).toBeNull();
  });

  it('resets its drawing state when the pdf changes', () => {
    const component = fixture.componentInstance;
    component.pdfModified = true;
    component.pdfRendered = true;
    component.ngOnChanges({});
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
  getSerializedAnnotations() { return structuredClone(this.annotations); }
  addEditorAnnotation(annotation: any) { this.annotations.push(annotation); return Promise.resolve(); }
  removeEditorAnnotations(filter: (a: any) => boolean) { this.annotations = this.annotations.filter(a => !filter(a)); }
  isRenderQueueEmpty() { return true; }
}

/** A stroke along y = 50 from x = 10 to x = 90, in pdf.js' flat [y, x] layout. */
function stroke(pageIndex = 0): any {
  return { ...ink([[10, 50], [30, 50], [50, 50], [70, 50], [90, 50]]), pageIndex };
}

describe('PDFViewerComponent annotations', () => {
  let fixture: ComponentFixture<PDFViewerComponent>;
  let component: PDFViewerComponent;
  let ngx: FakePdfViewerService;
  let notification: jasmine.SpyObj<NotificationService>;
  let page: HTMLElement;

  const el = (tag: string, attrs: Record<string, string> = {}, ...children: Element[]) => {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    children.forEach(c => node.appendChild(c));
    return node;
  };
  const square = 'position:fixed;left:0;top:0;width:100px;height:100px';

  beforeEach(() => {
    ngx = new FakePdfViewerService();
    notification = notificationSpy();
    TestBed.configureTestingModule({
      declarations: [PDFViewerComponent],
      imports: [...MATERIAL_MODULES, NgxExtendedPdfViewerModule],
      providers: [
        { provide: NotificationService, useValue: notification },
        { provide: NgxExtendedPdfViewerService, useValue: ngx },
      ],
    });
    fixture = TestBed.createComponent(PDFViewerComponent);
    component = fixture.componentInstance;
    (component as any).timeout = 0;  // the viewer's settle delays, not needed here
    fixture.componentRef.setInput('pdfUrl', undefined);  // no real viewer: the circular cursor only
    fixture.detectChanges();

    // what pdf.js renders for a one-page document with one ink drawing
    const inkEditor = el('div', { class: 'inkEditor selectedEditor draggable' },
      el('div'), el('canvas', { width: '100', height: '100', style: square }), el('div'));
    page = el('div', { id: 'fake-pdf' },
      el('div', { 'aria-label': 'Page 1' },
        el('div', { class: 'annotationEditorLayer' }, inkEditor),
        el('div', { class: 'inkAnnotation' }),
        el('div', { class: 'textLayer disabled', style: square })),
      el('div', { id: 'eraserParamsToolbar', class: 'hidden' }),
      el('button', { id: 'eraserTool' }),
      el('button', { id: 'primaryEditorInk', class: 'toolbarButton toggled' }),
      el('app-pdf-viewer', { style: 'position:fixed;left:0;top:0' }));
    document.body.appendChild(page);
  });

  afterEach(async () => {
    await component.ngOnDestroy();
    page.remove();
  });

  const q = (selector: string) => page.querySelector(selector) as HTMLElement;
  const pointer = (type: string, x = 50, y = 50, pointerType = 'mouse') =>
    q('.textLayer').dispatchEvent(new PointerEvent(type, { pointerType, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  const inkPaths = () => ngx.annotations.filter(a => a.annotationType === 15).map(a => a.paths.length);

  it('asks the text editor whether the user is typing', () => {
    component.pdfTextEditor = { isSelected: true } as any;
    expect(component.isWriting()).toBeTrue();
  });

  it('returns the annotated pdf only when something was changed, if asked so', async () => {
    expect(await component.getRenderedPdfFile('a.pdf', true)).toBeUndefined();
    expect(ngx.getCurrentDocumentAsBlob).not.toHaveBeenCalled();

    const file = await component.getRenderedPdfFile('a.pdf');
    expect(file.name).toBe('a.pdf');
    expect(file.type).toBe('application/pdf');

    component.pdfModified = true;
    expect(await component.getRenderedPdfFile('b.pdf', true)).toBeDefined();
    ngx.annotations = [{ annotationType: 3 }];
    expect(component.getAnnotations()).toEqual([{ annotationType: 3 } as any]);
  });

  it('draws the saved annotations once the first page is rendered, then styles the editors', async () => {
    const loaded = jasmine.createSpy('loaded');
    component.onAnnotationsLoaded.subscribe(loaded);
    await component.renderAnnotations([stroke(), { annotationType: 3, pageIndex: 1 } as any], true);
    await component.renderAnnotations(undefined);
    expect(component.pdfAnnotations.length).toBe(2);

    await component.onPdfLoaded({});
    await component.onPageRendered({});
    await component.onPageRendered({});  // the next pages change nothing
    await waitUntil(() => loaded.calls.count() > 0);

    expect(loaded).toHaveBeenCalledOnceWith(true);
    expect(ngx.renderPage.calls.allArgs()).toEqual([[0], [1]]);
    expect(ngx.annotations.length).toBe(2);
    expect(component.pdfAnnotations).toEqual([]);
    expect(component.pdfModified).toBeTrue();
    await waitUntil(() => component.pdfViewerInitialized);
    expect([ngx.editorInkColor, ngx.editorInkThickness, ngx.editorFontColor, ngx.editorFontSize]).toEqual(['#FF0000', 2, '#FF0000', 14]);

    // drawings already on the page cannot be dragged or selected
    const editor = q('.inkEditor');
    expect(editor.style.pointerEvents).toBe('none');
    expect(editor.classList.contains('selectedEditor')).toBeFalse();
    expect(editor.children[0].classList.contains('hidden')).toBeTrue();
    expect(q('.inkAnnotation').style.pointerEvents).toBe('none');
    expect(component.observers.length).toBe(1);

    // a drawing added later is styled the same way
    const added = el('div', { class: 'inkEditor' }, el('div'), el('canvas'), el('div'));
    q('.annotationEditorLayer').appendChild(added);
    await waitUntil(() => added.style.pointerEvents === 'none');

    await component.ngOnChanges({});
    expect(component.observers).toEqual([]);
    expect(component.pdfRendered).toBeFalse();
  });

  it('annotations given after the first render are drawn right away', async () => {
    component.pdfRendered = true;
    await component.renderAnnotations([stroke()]);
    await waitUntil(() => ngx.annotations.length === 1);
    // a deep copy: the viewer never shares objects with the caller
    expect(ngx.annotations[0]).toEqual(stroke());
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

  it('a new stroke clears the redo history, a text edit does not', async () => {
    component.pdfTextEditor = { isSelected: false } as any;
    component.nInkAnnotations = 0;
    component.annotationsHistory = [new AnnotationsChange()];
    await component.onAnnotationEdited({});  // same number of strokes
    expect(component.annotationsHistory.length).toBe(1);
    expect(component.pdfModified).toBeTrue();

    ngx.annotations = [stroke()];
    await component.onAnnotationEdited({});
    expect(component.annotationsHistory).toEqual([]);
  });

  it('undo removes the last stroke, one path at a time, and redo puts it back', () => {
    component.undoChange();
    expect(notification.showInfo).toHaveBeenCalledWith(jasmine.stringContaining('Aucune annotation à enlever'), 'Info');
    component.redoChange();
    expect(notification.showInfo).toHaveBeenCalledWith('Aucune annotation à rajouter.', 'Info');

    const twoPaths = stroke();
    twoPaths.paths.push({ points: [5, 5, 6, 6], bezier: [] });
    ngx.annotations = [stroke(), twoPaths, { annotationType: 3 }];

    component.undoChange();  // the second path of the last stroke
    expect(inkPaths()).toEqual([1, 1]);
    const shrunk = ngx.annotations.filter(a => a.annotationType === 15)[1];
    expect(shrunk.rect).toEqual([48, 8, 51, 91]);  // around y = 50, x in [10, 90], padded
    component.undoChange();  // the whole last stroke
    expect(inkPaths()).toEqual([1]);
    expect(component.nInkAnnotations).toBe(1);
    expect(ngx.annotations.some(a => a.annotationType === 3)).toBeTrue();  // text is left alone

    component.redoChange();
    expect(inkPaths()).toEqual([1, 1]);
    component.redoChange();
    expect(inkPaths()).toEqual([1, 2]);
    expect(ngx.annotations.filter(a => a.annotationType === 15)[1].rect).toEqual([0, 0, 100, 100]);
  });

  describe('eraser', () => {
    const openEraser = async () => {
      component.onPointerDown({ pointerType: 'mouse' } as PointerEvent);
      const click = spyOn(q('#primaryEditorInk'), 'click');
      component.erase({} as PointerEvent);
      expect(click).toHaveBeenCalled();  // the open ink editor is closed first
      await waitUntil(() => q('#eraserTool').classList.contains('toggled'));
    };

    it('toggles its toolbar and its listeners on the pages', async () => {
      await openEraser();
      expect(q('#eraserParamsToolbar').classList.contains('hidden')).toBeFalse();
      expect(q('.textLayer').classList.contains('inkErasing')).toBeTrue();
      expect(q('.textLayer').classList.contains('disabled')).toBeFalse();
      expect(q('.annotationEditorLayer').classList.contains('disabled')).toBeTrue();

      component.erase({} as PointerEvent);
      expect(q('#eraserParamsToolbar').classList.contains('hidden')).toBeTrue();
      expect(q('#eraserTool').classList.contains('toggled')).toBeFalse();
      expect(q('.textLayer').classList.contains('inkErasing')).toBeFalse();
      expect(component.samePointerType({ pointerType: 'mouse' })).toBeFalse();
    });

    it('cuts the strokes it passes over, and undo and redo the whole erasing', async () => {
      ngx.annotations = [stroke(), stroke(1)];  // the second is on another page
      await openEraser();

      pointer('pointerdown');
      expect(document.getElementById('circular-cursor').style.display).toBe('block');
      expect(document.getElementById('circular-cursor').style.transform).toBe('translate(30px, 30px)');
      const move = new PointerEvent('pointermove', { pointerType: 'mouse', clientX: 50, clientY: 50, cancelable: true });
      q('.textLayer').dispatchEvent(move);
      expect(move.defaultPrevented).toBeTrue();
      const touch = new TouchEvent('touchmove', { cancelable: true });
      q('.textLayer').dispatchEvent(touch);
      expect(touch.defaultPrevented).toBeTrue();
      pointer('pointerup');

      // the point under the eraser is gone: the stroke is split in two
      expect(document.getElementById('circular-cursor').style.display).toBe('none');
      expect(component.pdfModified).toBeTrue();
      expect(inkPaths()).toEqual([2, 1]);
      expect(component.eraserHistory.length).toBe(1);

      component.undoChange();
      expect(inkPaths()).toEqual([1, 1]);
      expect(component.eraserHistory).toEqual([]);
      component.redoChange();
      expect(inkPaths()).toEqual([2, 1]);
      expect(component.eraserHistory.length).toBe(1);
    });

    it('forgets an erasing that touched nothing, and ignores another pointer', async () => {
      ngx.annotations = [stroke()];
      await openEraser();

      pointer('pointerdown', 50, 50, 'pen');  // not the pointer that opened the eraser
      expect(component.eraserHistory).toEqual([]);

      pointer('pointerdown', 95, 5);
      pointer('pointermove', 95, 5);  // far from the stroke
      pointer('pointerleave', 95, 5);
      expect(component.eraserHistory).toEqual([]);
      expect(inkPaths()).toEqual([1]);
      expect(component.pdfModified).toBeFalse();

      // moves without a press do nothing
      const move = new PointerEvent('pointermove', { pointerType: 'mouse', clientX: 50, clientY: 50, cancelable: true });
      q('.textLayer').dispatchEvent(move);
      expect(move.defaultPrevented).toBeFalse();
    });

    it('stays on for the pages drawn while it is open', async () => {
      await openEraser();
      q('.textLayer').classList.remove('inkErasing');
      component.loadAnnotations();
      await waitUntil(() => q('.textLayer').classList.contains('inkErasing'));
    });
  });
});
