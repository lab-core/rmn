import { TestBed } from '@angular/core/testing';

import { EraserService } from './eraser.service';
import { RectangleService } from './rectangle.service';
import { mountSvg } from './rectangle.service.spec';

const NULL_BOX = { x1: null, x2: null, y1: null, y2: null };

describe('EraserService', () => {
  let service: EraserService;
  let rectangles: RectangleService;
  let svg: SVGGraphicsElement;

  const addRect = (id: string) => {
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.id = id;
    svg.appendChild(rect);
    return rect;
  };

  beforeEach(() => {
    service = TestBed.inject(EraserService);
    rectangles = TestBed.inject(RectangleService);
    rectangles.resetRects();
    svg = mountSvg();
    spyOn(console, 'log');
  });

  afterEach(() => svg.remove());

  it('init makes the existing boxes clickable', () => {
    const identification = addRect('identification');
    service.init();
    expect(svg.getAttribute('cursor')).toBe('default');
    expect(identification.getAttribute('cursor')).toBe('pointer');
  });

  it('removes the clicked box and clears its coordinates', () => {
    const identification = addRect('identification');
    const questions = addRect('questions');
    rectangles.setIdentificationRectCoords({ x1: 1, x2: 2, y1: 3, y2: 4 });
    rectangles.setquestionsRectCoords({ x1: 5, x2: 6, y1: 7, y2: 8 });
    service.init();

    service.mouseDown({ target: identification } as any);

    expect(document.getElementById('identification')).toBeNull();
    expect(svg.contains(questions)).toBeTrue();
    expect(rectangles.getIdentificationRectCoords()).toEqual(NULL_BOX);
    expect(rectangles.getQuestionsRectCoords()).toEqual({ x1: 5, x2: 6, y1: 7, y2: 8 });

    service.mouseDown({ target: questions } as any);
    expect(document.getElementById('questions')).toBeNull();
    expect(rectangles.getQuestionsRectCoords()).toEqual(NULL_BOX);
  });

  it('ignores clicks on anything else', () => {
    const identification = addRect('identification');
    rectangles.setIdentificationRectCoords({ x1: 1, x2: 2, y1: 3, y2: 4 });
    service.init();

    service.mouseDown({ target: svg } as any);
    service.mouseMove({} as MouseEvent);
    service.mouseUp({} as MouseEvent);
    service.mouseLeave({} as MouseEvent);

    expect(svg.contains(identification)).toBeTrue();
    expect(rectangles.getIdentificationRectCoords()).toEqual({ x1: 1, x2: 2, y1: 3, y2: 4 });
  });
});
