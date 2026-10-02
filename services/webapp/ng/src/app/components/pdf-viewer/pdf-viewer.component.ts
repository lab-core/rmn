import { Component, Input, Output, EventEmitter, OnChanges, ChangeDetectionStrategy, ViewChild } from '@angular/core';
import { NgxExtendedPdfViewerService, EditorAnnotation, PdfTextEditorComponent, pdfDefaultOptions, AnnotationEditorEditorModeChangedEvent } from 'ngx-extended-pdf-viewer';
import { RemovedAnnotation, SavedAnnotation, isRemoved } from 'src/app/services/pdf-source';

/** pdf.js editor modes the viewer switches between itself. */
const MODE_NONE = 0;
const MODE_INK = 15;


/** A pdf.js editor (or a form value) in the document's annotation storage:
 *  the part of it the viewer uses, pdf.js types none of it. */
interface PdfJsStored {
  annotationElementId?: string | null;
  deleted?: boolean;
  pageIndex?: number;
  serialize?(isForCopying: boolean, context: null): Record<string, unknown> | null;
  remove?(): void;
}

/** The pdf.js viewer application, as far as the viewer reaches into it. */
interface PdfJsApplication {
  pdfDocument?: { annotationStorage: Iterable<[string, PdfJsStored]> };
  pdfViewer?: { annotationEditorMode: number };
}

/** Coordinates to 1/100 pt: pdf.js 6 writes them with full float precision,
 *  which made a single drawing weigh hundreds of kB in the saved JSON. */
function rounded<T>(value: T): T {
  if (typeof value === 'number') {
    return (Math.round(value * 100) / 100) as T;
  }
  if (Array.isArray(value)) {
    return value.map(rounded) as T;
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, rounded(v)])) as T;
  }
  return value;
}


@Component({
    selector: 'app-pdf-viewer',
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './pdf-viewer.component.html',
    styleUrls: ['./pdf-viewer.component.css'],
    standalone: false
})
export class PDFViewerComponent implements OnChanges {

  @Input({required: true}) pdfUrl: string;
  @Input() hideToolbar: boolean = false;

  pdfAnnotations: SavedAnnotation[] = [];
  pdfViewerInitialized: boolean = false;
  pdfModified: boolean = false;
  pdfRendered: boolean = false;

  @Output() onAnnotationsLoaded = new EventEmitter<boolean>();

  @ViewChild(PdfTextEditorComponent)
  pdfTextEditor: PdfTextEditorComponent;

  private timeout: number = 80;
  /** The tool (pen, eraser, ...) the user last chose: kept from one copy to the next. */
  private editorMode = MODE_NONE;
  /** A copy is being opened: the viewer's own mode changes and the events of
   *  the restored annotations are not the user's. */
  private loading = true;
  /** The annotations to save right after the copy was opened, to tell whether it changed. */
  private loadedAnnotations = '[]';

  constructor(private ngxService: NgxExtendedPdfViewerService) {
      // the eraser and the undo/redo buttons only exist in the bleeding-edge
      // bundle (pdf.js 6.3), copied to /bleeding-edge/ by angular.json
      pdfDefaultOptions.assetsFolder = 'bleeding-edge';
      pdfDefaultOptions.doubleTapZoomsInHandMode = false;
      pdfDefaultOptions.doubleTapZoomsInTextSelectionMode = false;
      pdfDefaultOptions.doubleTapResetsZoomOnSecondDoubleTap = false;
  }

  async ngOnChanges() {
    this.pdfModified = false;
    this.pdfRendered = false;
    this.loading = true;
  }

  /** The pdf.js viewer application, for what ngx-extended-pdf-viewer does not
   *  expose: the annotation storage and the editor mode. */
  private get pdfApp(): PdfJsApplication | undefined {
    return (this.ngxService as unknown as { PDFViewerApplication?: PdfJsApplication })?.PDFViewerApplication;
  }

  public isWriting() {
    return this.pdfTextEditor?.isSelected ?? false;
  }

  public async renderAnnotations(annotations: SavedAnnotation[], pdfModified: boolean=false) {
    if (annotations) {
      // a drawing saved by pdf.js 4 (`paths` an array) makes pdf.js 6 throw,
      // which drops every annotation restored with it: leave those out
      const readable = annotations.filter(a => isRemoved(a) || a?.annotationType !== 15 || !Array.isArray(a.paths));
      this.pdfAnnotations = [ ...this.pdfAnnotations, ...readable];
      // if pdf already rendered, call loadAnnotations(). Otherwise, it will be called naturlaly
      if (this.pdfRendered) {
        setTimeout(() => { this.loadAnnotations(); }, this.timeout);
      }
      if (pdfModified) {
        setTimeout(() => { this.pdfModified = pdfModified; });
      }
    }
  }

  public async getRenderedPdfFile(filename: string, onlyIfModified: boolean=false): Promise<File> {
    await this.commitDrawing();
    // check if pdf has been modified
    if (onlyIfModified && !this.isModified()) {
      return undefined;
    } else {
      const editedPdfData = await this.ngxService?.getCurrentDocumentAsBlob();
      return new File([editedPdfData], filename, { type: editedPdfData.type });
    }
  }

  /**
   * What to save with the copy: what changed since the pdf was opened, the way
   * pdf.js itself decides it when it writes a pdf. The annotations already in
   * the pdf file are left out unless they were changed; one that was erased or
   * replaced is recorded as removed (its pdf id), and its new drawing, if any,
   * as an annotation of ours. ngx's getSerializedAnnotations() returns every
   * annotation, those of the file included: saved and restored on top of the
   * file, they doubled at each save.
   */
  public getAnnotations(): SavedAnnotation[] {
    const storage = this.pdfApp?.pdfDocument?.annotationStorage;
    if (!storage) {
      return [];
    }
    const saved: SavedAnnotation[] = [];
    for (const [, editor] of storage) {
      if (typeof editor?.serialize !== 'function' || !editor.serialize(false, null)) {
        continue;  // a form value, or an annotation of the file left as it was
      }
      if (editor.annotationElementId) {
        saved.push({ id: editor.annotationElementId, deleted: true, pageIndex: editor.pageIndex });
        if (editor.deleted) {
          continue;
        }
      }
      const drawing = editor.serialize(true, null);
      if (drawing) {
        delete drawing.id;
        delete drawing.isCopy;
        saved.push(rounded(drawing) as unknown as EditorAnnotation);
      }
    }
    return saved;
  }

  /** Adds the annotations one call each, in their saved order: one undo step
   *  per annotation, so undo takes them back one by one, the last added first.
   *  The viewer gets copies, never the caller's objects. */
  async addAnnotations(annotations: EditorAnnotation[]) {
    const deepClones: EditorAnnotation[] = JSON.parse(JSON.stringify(annotations));
    for (const annotation of deepClones) {
      await this.ngxService?.addEditorAnnotation([annotation]);
    }
  }

  async waitRender() {
    let first = true;
    while (first || !this.ngxService?.isRenderQueueEmpty()) {
      first = false;
      await (new Promise((resolve) => setTimeout(resolve, this.timeout)));
    }
  }

  async onPageRendered() {
    if (!this.pdfRendered) {
      this.pdfRendered = true;
      setTimeout(() => { this.initializePdfViewer() }, this.timeout);
      setTimeout(() => { this.loadAnnotations() }, this.timeout);
    }
  }

  /** Changed since it was opened: other annotations to save, or a local draft
   *  restored (pdfModified). The viewer's editor events are no measure: it
   *  fires them while opening a copy and switching tools too. */
  isModified(): boolean {
    return this.pdfModified || JSON.stringify(this.getAnnotations()) !== this.loadedAnnotations;
  }

  /**
   * Ends the pen's drawing session. pdf.js gathers the strokes drawn with the
   * pen into one drawing that exists, to be saved, only once the session ends
   * (another tool, or none): leaving and re-entering the mode ends it.
   */
  private async commitDrawing() {
    const mode = this.pdfApp?.pdfViewer?.annotationEditorMode;
    if (mode && mode !== MODE_NONE) {
      const loading = this.loading;
      this.loading = true;  // the events of the mode switch are not the user's
      await this.setEditorMode(MODE_NONE);
      await this.setEditorMode(mode);
      this.loading = loading;
    }
  }

  onEditorModeChanged(event: AnnotationEditorEditorModeChangedEvent) {
    if (!this.loading) {
      this.editorMode = event.mode;
    }
  }

  /** Switches the editor mode and waits for the viewer to be in it. */
  private async setEditorMode(mode: number) {
    const viewer = this.pdfApp?.pdfViewer;
    if (!viewer || viewer.annotationEditorMode === mode) {
      return;
    }
    this.ngxService.switchAnnotationEdtorMode(mode);
    for (let i = 0; i < 40 && viewer.annotationEditorMode !== mode; i++) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
  }

  /**
   * Removes the annotations of the file the saved ones replaced or erased.
   * pdf.js turns them into editors only in an editor mode, so the viewer goes
   * through the pen for that, the time to find and remove them.
   */
  private async removeFileAnnotations(removed: RemovedAnnotation[]) {
    const ids = new Set(removed.map(a => a.id));
    await this.setEditorMode(MODE_INK);
    const storage = this.pdfApp?.pdfDocument?.annotationStorage;
    const editors = () => storage ? Array.from(storage, ([, editor]) => editor)
      .filter(editor => ids.has(editor?.annotationElementId) && !editor.deleted) : [];
    // the pages turn their annotations into editors asynchronously
    for (let i = 0; i < 40 && editors().length < ids.size; i++) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    editors().forEach(editor => editor.remove?.());
  }

  async initializePdfViewer(): Promise<void> {
    if (!this.pdfViewerInitialized) {
      await this.waitRender();
      try {
        this.ngxService.editorInkColor = '#FF0000';
        this.ngxService.editorInkThickness = 2;
        this.ngxService.editorFontColor = '#FF0000';
        this.ngxService.editorFontSize = 14;
        this.pdfViewerInitialized = true;
      } catch {
        setTimeout(() => { this.initializePdfViewer() }, this.timeout);
      }
    }
  }

  loadAnnotations() {
    setTimeout(async () => {
      for (const a of this.pdfAnnotations) {
        await this.ngxService?.renderPage(a.pageIndex);
      }
      await this.waitRender();
      const annotations = this.pdfAnnotations;
      this.pdfAnnotations = [];
      const removed = annotations.filter(isRemoved);
      if (removed.length > 0) {
        await this.removeFileAnnotations(removed);
      }
      const added = annotations.filter(a => !isRemoved(a)) as EditorAnnotation[];
      if (added.length > 0) {
        await this.addAnnotations(added);
      }
      await this.setEditorMode(this.editorMode);
      this.loadedAnnotations = JSON.stringify(this.getAnnotations());
      this.loading = false;
      this.onAnnotationsLoaded.emit(true);
    });
  }
}
