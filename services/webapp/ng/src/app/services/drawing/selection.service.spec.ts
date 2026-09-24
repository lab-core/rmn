import { TestBed } from '@angular/core/testing';

import { RectangleService } from './rectangle.service';
import { mountSvg } from './rectangle.service.spec';
import { SelectionService } from './selection.service';

/** An identification box already drawn on the container. */
function addBox(svg: SVGGraphicsElement, x: number, y: number, width: number, height: number,
                id = 'identification'): SVGGraphicsElement {
  const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect') as SVGGraphicsElement;
  rect.setAttribute('id', id);
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

  const circle = (id: string) => document.getElementById(id);
  const at = (id: string) => [circle(id).getAttribute('cx'), circle(id).getAttribute('cy')];
  const box = (rect: Element) => ['x', 'y', 'width', 'height'].map(a => Number(rect.getAttribute(a)));

  it('puts a handle in the middle of each side of both boxes', () => {
    addBox(svg, 20, 10, 100, 40);
    const questions = addBox(svg, 40, 60, 60, 20, 'questions');
    service.init();

    expect(svg.getAttribute('cursor')).toBe('default');
    expect(questions.getAttribute('cursor')).toBe('grab');
    expect(at('identification-circleX1')).toEqual(['70', '10']);
    expect(at('identification-circleX2')).toEqual(['70', '50']);
    expect(at('identification-circleY1')).toEqual(['20', '30']);
    expect(at('identification-circleY2')).toEqual(['120', '30']);
    expect(at('questions-circleY2')).toEqual(['100', '70']);
    expect(circle('questions-circleX1').getAttribute('cursor')).toBe('ns-resize');
    expect(circle('questions-circleY1').getAttribute('cursor')).toBe('ew-resize');
    expect(svg.querySelectorAll('circle').length).toBe(8);

    service.deleteControlPoints();
    expect(svg.querySelectorAll('circle').length).toBe(0);
    expect(() => service.deleteControlPoints()).not.toThrow();  // nothing left to remove
  });

  it('drags a box with its handles and stores its new place in percent', () => {
    const rect = addBox(svg, 20, 10, 100, 40, 'questions');
    service.init();
    service.mouseDown({ target: rect, offsetX: 30, offsetY: 20 } as any);
    expect(rect.getAttribute('cursor')).toBe('grabbing');

    const move = { offsetX: 50, offsetY: 30, preventDefault: jasmine.createSpy('preventDefault') } as any;
    service.mouseMove(move);
    expect(move.preventDefault).toHaveBeenCalled();
    expect(box(rect)).toEqual([40, 20, 100, 40]);
    expect(at('questions-circleX1')).toEqual(['90', '20']);
    expect(at('questions-circleY2')).toEqual(['140', '40']);

    service.mouseUp({} as MouseEvent);
    expect(service.selectedRect).toBeNull();
    expect(TestBed.inject(RectangleService).getQuestionsRectCoords()).toEqual({ x1: 20, x2: 70, y1: 20, y2: 60 });
    // moving without a selection changes nothing
    service.mouseMove({ offsetX: 0, offsetY: 0, preventDefault: () => {} } as any);
    expect(box(rect)).toEqual([40, 20, 100, 40]);
  });

  it('resizes a box from each handle, never below 18 px', () => {
    const rect = addBox(svg, 50, 20, 100, 60);
    service.init();
    const drag = (handle: string, offsetX: number, offsetY: number) => {
      service.mouseDown({ target: circle('identification-' + handle), offsetX, offsetY } as any);
      service.mouseMove({ offsetX, offsetY } as any);
      service.mouseUp({} as MouseEvent);
    };

    drag('circleX1', 60, 30);   // top edge down by 10
    expect(box(rect)).toEqual([50, 30, 100, 50]);
    drag('circleX1', 60, 75);   // would leave 5 px: refused
    expect(box(rect)).toEqual([50, 30, 100, 50]);

    drag('circleX2', 60, 70);   // bottom edge up
    expect(box(rect)).toEqual([50, 30, 100, 40]);
    drag('circleX2', 60, 35);   // too small: 18 px
    expect(box(rect)).toEqual([50, 30, 100, 18]);

    drag('circleY1', 70, 40);   // left edge right by 20
    expect(box(rect)).toEqual([70, 30, 80, 18]);
    drag('circleY1', 145, 40);  // would leave 5 px: refused
    expect(box(rect)).toEqual([70, 30, 80, 18]);

    drag('circleY2', 130, 40);  // right edge left
    expect(box(rect)).toEqual([70, 30, 60, 18]);
    drag('circleY2', 75, 40);   // too small: 18 px
    expect(box(rect)).toEqual([70, 30, 18, 18]);

    expect(at('identification-circleY2')).toEqual(['88', '39']);
    expect(TestBed.inject(RectangleService).getIdentificationRectCoords()).toEqual({ x1: 35, x2: 44, y1: 30, y2: 48 });
  });

  it('leaving the container drops the box where it is, inside the bounds', () => {
    const rect = addBox(svg, 20, 10, 100, 40);
    service.init();
    service.mouseDown({ target: rect, offsetX: 30, offsetY: 20 } as any);
    service.mouseMove({ offsetX: 190, offsetY: 20, preventDefault: () => {} } as any);  // x = 180
    service.mouseLeave({} as MouseEvent);
    expect(box(rect)).toEqual([100, 10, 100, 40]);
    expect(rect.getAttribute('cursor')).toBe('grab');
    expect(service.selectedRect).toBeNull();
    expect(() => service.mouseLeave({} as MouseEvent)).not.toThrow();
  });
});
