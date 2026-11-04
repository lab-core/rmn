/**
 * A second reading of an imported pdf, to catch pdf-lib reading it wrong.
 *
 * pdf-lib reads a file from start to end rather than through its
 * cross-references, so objects an editor left behind can replace live ones:
 * pages lost, or a page's annotations swapped for those of the export
 * (dropUnreachableObjectStreams handles the case seen so far). pdf.js, which
 * the viewer already loads, follows the cross-references like every other
 * reader. The two are compared page by page on what the import relies on:
 * how many pages, and which annotations each one carries (the export's
 * markers and the grader's notes).
 */
import { PDFArray, PDFDict, PDFDocument, PDFName } from 'pdf-lib';

interface PdfjsAnnotation { subtype: string; }
interface PdfjsPage { getAnnotations(params: { intent: string }): Promise<PdfjsAnnotation[]>; }
interface PdfjsDocument { numPages: number; getPage(pageNumber: number): Promise<PdfjsPage>; }
interface PdfjsLib {
  getDocument(src: { data: Uint8Array }): { promise: Promise<PdfjsDocument>; destroy(): Promise<void> };
}

/** The subtypes of a page's annotations, sorted, joined with '+'. A popup
 *  is left out: it belongs to another annotation and readers differ on
 *  listing it. */
function signature(subtypes: string[]): string {
  return subtypes.filter((s) => s !== 'Popup').sort().join('+');
}

/** Each page's annotations as pdf-lib reads them. */
export function annotationsByPage(doc: PDFDocument): string[] {
  return doc.getPages().map((page) => {
    const annots = page.node.lookup(PDFName.of('Annots'));
    const subtypes: string[] = [];
    for (let i = 0; annots instanceof PDFArray && i < annots.size(); i++) {
      const annot = doc.context.lookup(annots.get(i));
      subtypes.push(annot instanceof PDFDict ? String(annot.get(PDFName.of('Subtype'))).replace(/^\//, '') : '?');
    }
    return signature(subtypes);
  });
}

/** Each page's annotations as pdf.js reads them, or null when the viewer
 *  has not loaded pdf.js. The bytes are copied: pdf.js hands its input to
 *  its worker. */
export async function annotationsByPageWithPdfjs(bytes: Uint8Array): Promise<string[] | null> {
  const pdfjsLib = (globalThis as { pdfjsLib?: PdfjsLib }).pdfjsLib;
  if (!pdfjsLib) {
    return null;
  }
  const task = pdfjsLib.getDocument({ data: bytes.slice() });
  try {
    const doc = await task.promise;
    const pages: string[] = [];
    for (let n = 1; n <= doc.numPages; n++) {
      const annotations = await (await doc.getPage(n)).getAnnotations({ intent: 'any' });
      pages.push(signature(annotations.map((a) => a.subtype)));
    }
    return pages;
  } finally {
    await task.destroy();
  }
}

/** Where the two readings part, said for the user, or null when they agree. */
export function readingDifference(pdfLib: string[], pdfjs: string[]): string | null {
  if (pdfLib.length !== pdfjs.length) {
    return `${pdfLib.length} page(s) lue(s) au lieu de ${pdfjs.length}`;
  }
  const page = pdfLib.findIndex((annotations, i) => annotations !== pdfjs[i]);
  return page < 0 ? null : `les annotations de la page ${page + 1} ne sont pas celles du fichier`;
}
