import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NgxExtendedPdfViewerModule } from 'ngx-extended-pdf-viewer';

import { AnnotationsChange, BezierAnnotation, BezierPath, EraserChange, PDFViewerComponent } from './pdf-viewer.component';
import { NotificationService } from 'src/app/services/notification.service';
import { MATERIAL_MODULES, notificationSpy } from '../../testing/helpers';

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
