import { EditorAnnotation } from 'ngx-extended-pdf-viewer';

/** One stroke as pdf.js 4.x serialised it, both arrays flat [x, y, ...] in pdf coordinates. */
export interface LegacyInkPath {
  bezier: number[];
  points: number[];
}

/** The four leading values of a pdf.js 6 line: the first point has no control points. */
const NO_CONTROLS = [NaN, NaN, NaN, NaN];

/**
 * The annotations stored before the move to pdf.js 6 (ngx-extended-pdf-viewer
 * 21, pdf.js 4.6) describe a drawing as `paths: [{bezier, points}]`; pdf.js 6
 * reads `paths: {lines, points}` and drops the old shape without a word. Both
 * use pdf coordinates, and a 4.x bezier is the start point followed by
 * (control, control, end) triplets, which is a pdf.js 6 line once its missing
 * first control points are added. Other annotations are returned unchanged,
 * and so is a drawing already in the new shape.
 */
export function upgradeLegacyInk(annotation: EditorAnnotation): EditorAnnotation {
  if (annotation?.annotationType !== 15 || !Array.isArray(annotation.paths)) {
    return annotation;
  }
  const legacy: LegacyInkPath[] = annotation.paths;
  return {
    ...annotation,
    paths: {
      lines: legacy.map(path => [...NO_CONTROLS, ...bezierOf(path)]),
      points: legacy.map(path => [...(path.points || [])]),
    },
  } as EditorAnnotation;
}

/** The stroke's bezier, rebuilt as straight segments when it was saved without one. */
function bezierOf(path: LegacyInkPath): number[] {
  if (path.bezier?.length >= 2) {
    return path.bezier;
  }
  const points = path.points || [];
  const bezier = points.slice(0, 2);
  for (let i = 2; i + 1 < points.length; i += 2) {
    // control points on the end points: a straight segment
    bezier.push(points[i - 2], points[i - 1], points[i], points[i + 1], points[i], points[i + 1]);
  }
  return bezier;
}
