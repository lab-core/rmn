import { TestBed } from '@angular/core/testing';

import { RectangleService } from './rectangle.service';

const NULL_BOX = { x1: null, x2: null, y1: null, y2: null };

/** A 200x100 svg container like the template editor's. */
export function mountSvg(): SVGGraphicsElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg') as SVGGraphicsElement;
  svg.id = 'svg';
  Object.defineProperty(svg, 'clientWidth', { value: 200 });
  Object.defineProperty(svg, 'clientHeight', { value: 100 });
  document.body.appendChild(svg);
  return svg;
}

describe('RectangleService', () => {
  let service: RectangleService;
  let svg: SVGGraphicsElement;

  beforeEach(() => {
    service = TestBed.inject(RectangleService);
    service.resetRects();
    svg = mountSvg();
    spyOn(console, 'log');
  });

  afterEach(() => svg.remove());

  it('init switches the container to a crosshair cursor', () => {
    service.init();
    expect(svg.getAttribute('cursor')).toBe('crosshair');
  });

  it('draws a box and stores its coordinates in percent of the container', () => {
    service.init();
    service.mouseDown({ offsetX: 20, offsetY: 10 } as MouseEvent, true);
    service.mouseMove({ offsetX: 120, offsetY: 60 } as MouseEvent, true);

    const rect = svg.querySelector('#identification');
    expect(rect).not.toBeNull();
    expect(rect.getAttribute('x')).toBe('20');
    expect(rect.getAttribute('y')).toBe('10');
    expect(rect.getAttribute('width')).toBe('100');
    expect(rect.getAttribute('height')).toBe('50');
    expect(rect.getAttribute('stroke')).toBe('#006eff');

    service.mouseUp({} as MouseEvent, true);
    expect(service.isMouseDown).toBeFalse();
    expect(service.getIdentificationRectCoords()).toEqual({ x1: 10, x2: 60, y1: 10, y2: 60 });
    expect(service.getQuestionsRectCoords()).toEqual(NULL_BOX);
  });

  it('the questions box has its own colour, id and coordinates', () => {
    service.init();
    service.mouseDown({ offsetX: 0, offsetY: 50 } as MouseEvent, false);
    service.mouseMove({ offsetX: 200, offsetY: 100 } as MouseEvent, false);
    service.mouseLeave({} as MouseEvent, false); // leaving the container ends the drawing

    const rect = svg.querySelector('#questions');
    expect(rect.getAttribute('stroke')).toBe('#1eff00');
    expect(service.isMouseDown).toBeFalse();
    expect(service.getQuestionsRectCoords()).toEqual({ x1: 0, x2: 100, y1: 50, y2: 100 });
    expect(service.getIdentificationRectCoords()).toEqual(NULL_BOX);
  });

  it('a new drawing replaces the previous box of the same kind', () => {
    service.init();
    service.mouseDown({ offsetX: 0, offsetY: 0 } as MouseEvent, true);
    service.mouseMove({ offsetX: 10, offsetY: 10 } as MouseEvent, true);
    service.mouseUp({} as MouseEvent, true);
    service.mouseDown({ offsetX: 20, offsetY: 20 } as MouseEvent, true);
    service.mouseMove({ offsetX: 40, offsetY: 40 } as MouseEvent, true);
    service.mouseUp({} as MouseEvent, true);

    expect(svg.querySelectorAll('#identification').length).toBe(1);
    expect(service.getIdentificationRectCoords()).toEqual({ x1: 10, x2: 20, y1: 20, y2: 40 });
  });

  it('moving without a button down draws nothing', () => {
    service.init();
    service.mouseMove({ offsetX: 120, offsetY: 60 } as MouseEvent, true);
    expect(svg.querySelector('rect')).toBeNull();
  });

  it('initExistingRects redraws the stored boxes in pixels', () => {
    service.setIdentificationRectCoords({ x1: 10, x2: 60, y1: 10, y2: 60 });
    service.setquestionsRectCoords({ x1: 50, x2: 100, y1: 0, y2: 50 });

    service.initExistingRects();

    const identification = svg.querySelector('#identification');
    expect(identification.getAttribute('x')).toBe('20');
    expect(identification.getAttribute('y')).toBe('10');
    expect(identification.getAttribute('width')).toBe('100');
    expect(identification.getAttribute('height')).toBe('50');
    const questions = svg.querySelector('#questions');
    expect(questions.getAttribute('x')).toBe('100');
    expect(questions.getAttribute('width')).toBe('100');
    expect(questions.getAttribute('height')).toBe('50');
  });

  it('resetRects clears both boxes', () => {
    service.setIdentificationRectCoords({ x1: 1, x2: 2, y1: 3, y2: 4 });
    service.setquestionsRectCoords({ x1: 1, x2: 2, y1: 3, y2: 4 });
    service.resetRects();
    expect(service.getIdentificationRectCoords()).toEqual(NULL_BOX);
    expect(service.getQuestionsRectCoords()).toEqual(NULL_BOX);
  });
});
