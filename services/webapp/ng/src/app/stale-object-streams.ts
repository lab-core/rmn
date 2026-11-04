/**
 * Object streams a pdf editor left behind, which pdf-lib reads anyway.
 *
 * Preview, among others, rewrites a pdf exported by pdf-lib with a classic
 * cross-reference table but keeps the export's object stream (and its
 * cross-reference stream) in the file. A classic table cannot point into an
 * object stream, so readers that follow the cross-references (MuPDF, pdf.js,
 * Preview) never see it. pdf-lib reads the file from start to end instead,
 * and the stale objects of that stream replace the live ones of the same
 * number: the page tree of the export wins and a question of six annotated
 * copies loads as three pages (#244 was the same file throwing instead).
 */

const OBJECT_STREAM = /\/Type\s*\/ObjStm\b/g;
// the sections of a chain longer than this are not followed: the file is
// left as it is rather than guessed at
const MAX_SECTIONS = 100;

/** Whether the cross-reference sections the file is read through, from its
 *  last `startxref` back along `/Prev`, can point into an object stream:
 *  one of them is a cross-reference stream, or a classic trailer names one
 *  with `/XRefStm`. True as well when the chain cannot be followed. */
function objectStreamsReachable(text: string): boolean {
  const last = text.lastIndexOf('startxref');
  let offset = last < 0 ? NaN : parseInt(text.slice(last + 'startxref'.length).trim(), 10);
  for (let n = 0; n < MAX_SECTIONS; n++) {
    if (!(offset >= 0 && offset < text.length)) {
      return true;
    }
    const section = text.slice(offset).trimStart();
    if (!section.startsWith('xref')) {
      return true;  // a cross-reference stream (or something unreadable)
    }
    const trailer = text.indexOf('trailer', offset);
    const end = text.indexOf('startxref', trailer);
    if (trailer < 0 || end < 0) {
      return true;
    }
    const dict = text.slice(trailer, end);
    if (/\/XRefStm\b/.test(dict)) {
      return true;
    }
    const prev = /\/Prev\s+(\d+)/.exec(dict);
    if (!prev) {
      return false;
    }
    offset = parseInt(prev[1], 10);
  }
  return true;
}

/** The bytes with every unreachable object stream renamed out of pdf-lib's
 *  way (`/ObjStm` becomes `/XbjStm`, same length, so every offset holds),
 *  and how many there were. The object streams are unreachable when only
 *  classic tables lead to the file's objects; otherwise the bytes are
 *  returned untouched. */
export function dropUnreachableObjectStreams(pdf: ArrayBuffer | Uint8Array): { bytes: Uint8Array; dropped: number } {
  // a copy: the zip's own buffer stays as it was read
  const bytes = pdf instanceof Uint8Array ? pdf.slice() : new Uint8Array(pdf.slice(0));
  // one character per byte, so a match index is a byte offset
  const text = new TextDecoder('latin1').decode(bytes);
  if (objectStreamsReachable(text)) {
    return { bytes, dropped: 0 };
  }
  let dropped = 0;
  for (const match of text.matchAll(OBJECT_STREAM)) {
    bytes[match.index + match[0].lastIndexOf('ObjStm')] = 'X'.charCodeAt(0);
    dropped++;
  }
  return { bytes, dropped };
}
