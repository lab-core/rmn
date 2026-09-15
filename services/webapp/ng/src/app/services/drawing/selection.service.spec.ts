import { TestBed } from '@angular/core/testing';

import { RectangleService } from './rectangle.service';
import { mountSvg } from './rectangle.service.spec';
import { SelectionService } from './selection.service';

/** An identification box already drawn on the container. */
function addBox(svg: SVGGraphicsElement, x: number, y: number, width: number, height: number): SVGGraphicsElement {
  const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect') as SVGGraphicsElement;
  rect.setAttribute('id', 'identification');
  rect.setAttribute('x', String(x));
  rect.setAttribute('y', String(y));
  rect.setAttribute('width', String(width));
  rect.setAttribute('height', String(height));
  svg.appendChild(rect);
  return rect;
}

describe('SelectionService', () => {
  let service: SelectionService;
  let svg: SVGGraphicsElement;

  beforeEach(() => {
    service = TestBed.inject(SelectionService);
    TestBed.inject(RectangleService).resetRects();
    svg = mountSvg();
  });

  afterEach(() => svg.remove());

  it('a click on the empty container selects nothing and does not throw on release', () => {
    service.init();
    service.mouseDown({ target: svg, offsetX: 5, offsetY: 5 } as any);
    expect(service.selectedRect).toBeNull();
    expect(() => service.mouseUp({} as MouseEvent)).not.toThrow();
  });

  it('a box dragged out of the container is pushed back inside', () => {
    const rect = addBox(svg, 150, 80, 100, 50);  // sticks out on the right and the bottom (200x100 container)
    service.init();
    service.mouseDown({ target: rect, offsetX: 160, offsetY: 90 } as any);
    service.mouseUp({} as MouseEvent);
    expect(rect.getAttribute('x')).toBe('100');
    expect(rect.getAttribute('y')).toBe('50');
    expect(rect.getAttribute('cursor')).toBe('grab');
    expect(TestBed.inject(RectangleService).getIdentificationRectCoords()).toEqual({ x1: 50, x2: 100, y1: 50, y2: 100 });
  });

  it('a box wider than the container is clamped to its origin instead of recursing forever', () => {
    const rect = addBox(svg, -20, -10, 300, 150);
    service.init();
    service.mouseDown({ target: rect, offsetX: 0, offsetY: 0 } as any);
    service.mouseUp({} as MouseEvent);
    expect(rect.getAttribute('x')).toBe('0');
    expect(rect.getAttribute('y')).toBe('0');
  });
});
