import { PDFDocument, PDFName } from 'pdf-lib';
import { annotationsByPage, annotationsByPageWithPdfjs, readingDifference } from './pdf-reading-check';

describe('pdf reading check', () => {
  afterEach(() => { delete (globalThis as { pdfjsLib?: unknown }).pdfjsLib; });

  it("lists each page's annotations as pdf-lib reads them, popups left out", async () => {
    const doc = await PDFDocument.create();
    const [page] = [doc.addPage(), doc.addPage()];
    const annot = (subtype: string) => doc.context.register(doc.context.obj({ Type: 'Annot', Subtype: subtype }));
    page.node.set(PDFName.of('Annots'), doc.context.obj([annot('Text'), annot('Popup'), annot('Ink')]));
    expect(annotationsByPage(doc)).toEqual(['Ink+Text', '']);
  });

  it('reads with the pdf.js of the viewer, on a copy of the bytes', async () => {
    const pages = [['Text', 'Popup', 'Stamp'], []];
    const destroy = jasmine.createSpy('destroy').and.resolveTo();
    let given: Uint8Array | undefined;
    (globalThis as { pdfjsLib?: unknown }).pdfjsLib = {
      getDocument: ({ data }: { data: Uint8Array }) => {
        given = data;
        return {
          promise: Promise.resolve({
            numPages: 2,
            getPage: async (n: number) => ({
              getAnnotations: async () => pages[n - 1].map((subtype) => ({ subtype })),
            }),
          }),
          destroy,
        };
      },
    };
    const bytes = new Uint8Array([1, 2, 3]);
    expect(await annotationsByPageWithPdfjs(bytes)).toEqual(['Stamp+Text', '']);
    expect(given).not.toBe(bytes);
    expect(destroy).toHaveBeenCalled();
  });

  it('reads nothing when the viewer has not loaded pdf.js', async () => {
    expect(await annotationsByPageWithPdfjs(new Uint8Array())).toBeNull();
  });

  it('says where the two readings part', () => {
    expect(readingDifference(['Text', 'Text+Ink'], ['Text', 'Text+Ink'])).toBeNull();
    expect(readingDifference(['Text', 'Text', 'Text'], Array(6).fill('Text')))
      .toBe('3 page(s) lue(s) au lieu de 6');
    expect(readingDifference(['Text', 'Text'], ['Text', 'Stamp+Text']))
      .toBe('les annotations de la page 2 ne sont pas celles du fichier');
  });
});
