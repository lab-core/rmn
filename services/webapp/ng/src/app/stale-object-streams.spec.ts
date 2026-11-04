import { dropUnreachableObjectStreams } from './stale-object-streams';

const bytes = (text: string) => Uint8Array.from(text, (c) => c.charCodeAt(0));
const text = (b: Uint8Array) => String.fromCharCode(...b);

const OBJECT_STREAM = '1 0 obj\n<< /Type /ObjStm /N 1 >>\nendobj\n';
const XREF_STREAM = '2 0 obj\n<< /Type /XRef /Root 3 0 R >>\nendobj\n';

/** `body` closed by a classic table whose trailer holds `trailer`, with
 *  `startxref` pointing at it. */
function classic(body: string, trailer = ''): string {
  return `${body}xref\n0 1\ntrailer\n<< /Root 3 0 R ${trailer}>>\nstartxref\n${body.length}\n%%EOF\n`;
}

describe('dropUnreachableObjectStreams', () => {
  it('renames the object streams only classic tables lead past, stale cross-reference stream included', () => {
    // what Preview writes over an export of pdf-lib
    const pdf = bytes(classic(OBJECT_STREAM + XREF_STREAM));
    const { bytes: out, dropped } = dropUnreachableObjectStreams(pdf);
    expect(dropped).toBe(1);
    expect(text(out)).toBe(text(pdf).replace('/ObjStm', '/XbjStm'));
    expect(text(pdf)).toContain('/ObjStm');  // the input is left as it was
  });

  it('leaves a file read through a cross-reference stream alone', () => {
    const body = OBJECT_STREAM;
    const pdf = bytes(`${body}${XREF_STREAM}startxref\n${body.length}\n%%EOF\n`);
    expect(dropUnreachableObjectStreams(pdf.buffer).dropped).toBe(0);
  });

  it('leaves a hybrid file alone: its trailer names a cross-reference stream', () => {
    const pdf = bytes(classic(OBJECT_STREAM + XREF_STREAM, `/XRefStm ${OBJECT_STREAM.length} `));
    expect(dropUnreachableObjectStreams(pdf).dropped).toBe(0);
  });

  it('follows /Prev back to an earlier cross-reference stream and leaves the file alone', () => {
    const pdf = bytes(classic(OBJECT_STREAM + XREF_STREAM, `/Prev ${OBJECT_STREAM.length} `));
    expect(dropUnreachableObjectStreams(pdf).dropped).toBe(0);
  });

  it('leaves a file whose startxref leads nowhere alone', () => {
    expect(dropUnreachableObjectStreams(bytes(`${OBJECT_STREAM}startxref\n99999\n%%EOF\n`)).dropped).toBe(0);
    expect(dropUnreachableObjectStreams(bytes(OBJECT_STREAM)).dropped).toBe(0);
  });
});
