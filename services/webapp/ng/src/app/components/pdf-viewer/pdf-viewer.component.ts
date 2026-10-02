import { Component, ElementRef, Input, Output, EventEmitter, OnChanges, OnDestroy, ChangeDetectionStrategy, ViewChild } from '@angular/core';
import { NgxExtendedPdfViewerService, EditorAnnotation, PdfTextEditorComponent, pdfDefaultOptions, AnnotationEditorEditorModeChangedEvent } from 'ngx-extended-pdf-viewer';
import { RemovedAnnotation, SavedAnnotation, isRemoved } from 'src/app/services/pdf-source';

/** pdf.js editor modes the viewer switches between itself. */
const MODE_NONE = 0;
const MODE_INK = 15;
const MODE_ERASER = 103;


/** A pdf.js editor (or a form value) in the document's annotation storage:
 *  the part of it the viewer uses, pdf.js types none of it. */
interface PdfJsStored {
  annotationElementId?: string | null;
  deleted?: boolean;
  pageIndex?: number;
  serialize?(isForCopying: boolean, context: null): Record<string, unknown> | null;
  remove?(): void;
}

/** pdf.js's record of the pointer type (mouse, pen, touch) that owns the editor mode. */
interface PdfJsPointers {
  claimFor(pointerType: string | null): void;
  isSamePointerType(pointerType: string): boolean;
}

const POINTER_TYPES = ['mouse', 'pen', 'touch'];

/** The pdf.js viewer application, as far as the viewer reaches into it. */
interface PdfJsApplication {
  pdfDocument?: { annotationStorage: Iterable<[string, PdfJsStored]> };
  pdfViewer?: {
    annotationEditorMode: number;
    _pages?: { annotationEditorLayer?: { annotationEditorLayer?: { commitOrRemove(): boolean } | null } | null }[];
    _layerProperties?: { annotationEditorUIManager?: { currentPointers?: PdfJsPointers } | null };
  };
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
export class PDFViewerComponent implements OnChanges, OnDestroy {

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
  /** The pointer type that owns that tool (the stylus that opened the pen...): kept with it. */
  private pointerOwner: string | null = null;
  /** A copy is being opened: the viewer's own mode changes and the events of
   *  the restored annotations are not the user's. */
  private loading = true;
  /** The annotations to save right after the copy was opened, to tell whether it changed. */
  private loadedAnnotations = '[]';
  /** Bumped at each copy: a restore still running for the previous one stops. */
  private generation = 0;

  constructor(private ngxService: NgxExtendedPdfViewerService, private host: ElementRef<HTMLElement>) {
      // the eraser and the undo/redo buttons only exist in the bleeding-edge
      // bundle (pdf.js 6.3), copied to /bleeding-edge/ by angular.json
      pdfDefaultOptions.assetsFolder = 'bleeding-edge';
      pdfDefaultOptions.doubleTapZoomsInHandMode = false;
      pdfDefaultOptions.doubleTapZoomsInTextSelectionMode = false;
      pdfDefaultOptions.doubleTapResetsZoomOnSecondDoubleTap = false;
      document.addEventListener('touchmove', this.stopPencilScroll, { capture: true, passive: false });
  }

  ngOnDestroy() {
    document.removeEventListener('touchmove', this.stopPencilScroll, { capture: true });
  }

  /**
   * The Apple Pencil on an iPad scrolled the page instead of writing (the
   * stroke cut short after a few points). pdf.js stops the scroll by
   * cancelling the touchmove whose timestamp is the one of the pointer move
   * it drew; Safari does not always send them in that order, and it decides
   * to scroll on the first one it is not stopped from. With the pen or the
   * eraser on and owned by the stylus (or by nothing yet), a stylus touch on
   * a page never scrolls: the finger still does.
   */
  private stopPencilScroll = (event: TouchEvent) => {
    const mode = this.pdfApp?.pdfViewer?.annotationEditorMode;
    if (mode !== MODE_INK && mode !== MODE_ERASER) {
      return;
    }
    const stylus = Array.from(event.touches).some(touch => (touch as Touch & { touchType?: string }).touchType === 'stylus');
    const target = event.target as Element;
    const onPage = this.host.nativeElement.contains(target) && target.closest?.('.page');
    const owner = this.ownerPointerType();
    if (stylus && onPage && (owner === 'pen' || owner === null) && event.cancelable) {
      event.preventDefault();
    }
  };

  async ngOnChanges() {
    if (!this.loading) {
      this.pointerOwner = this.ownerPointerType();
    }
    this.pdfModified = false;
    this.pdfRendered = false;
    this.loading = true;
    this.generation++;
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
      // the annotations of this copy: those of a copy left before they were
      // drawn are dropped, not added to it
      this.pdfAnnotations = readable;
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
   * (another tool, Escape, a click elsewhere): each page's editor layer ends
   * it as Escape does, without the mode switch, which threw on pages still
   * rendering when a copy changed.
   */
  private async commitDrawing() {
    for (const page of this.pdfApp?.pdfViewer?._pages ?? []) {
      page?.annotationEditorLayer?.annotationEditorLayer?.commitOrRemove();
    }
  }

  onEditorModeChanged(event: AnnotationEditorEditorModeChangedEvent) {
    if (!this.loading) {
      this.editorMode = event.mode;
    }
  }

  /** pdf.js's pointer manager of the document shown. */
  private get pointers(): PdfJsPointers | undefined {
    return this.pdfApp?.pdfViewer?._layerProperties?.annotationEditorUIManager?.currentPointers;
  }

  /** The pointer type that owns the editor mode, null while none does. */
  private ownerPointerType(): string | null {
    const pointers = this.pointers;
    return POINTER_TYPES.find(type => pointers?.isSamePointerType(type)) ?? null;
  }

  /**
   * Switches the editor mode and waits for the viewer to be in it. pdf.js
   * gives the tool to the pointer pressed in the last second and ignores the
   * others: on the next copy, that was the finger that tapped "next", and the
   * stylus that had opened the pen scrolled or selected an annotation. The
   * tool goes back to the pointer type that owned it on the previous copy.
   */
  private async setEditorMode(mode: number) {
    const viewer = this.pdfApp?.pdfViewer;
    if (!viewer || viewer.annotationEditorMode === mode) {
      return;
    }
    this.ngxService.switchAnnotationEdtorMode(mode);
    for (let i = 0; i < 40 && viewer.annotationEditorMode !== mode; i++) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    this.pointers?.claimFor(this.pointerOwner);
  }

  /**
   * Removes the annotations of the file the saved ones replaced or erased.
   * pdf.js turns them into editors only in an editor mode, where the caller
   * puts the viewer.
   */
  private async removeFileAnnotations(removed: RemovedAnnotation[]) {
    const ids = new Set(removed.map(a => a.id));
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
    const generation = this.generation;
    const current = () => generation === this.generation;
    setTimeout(async () => {
      // each page once, however many annotations it carries
      for (const pageIndex of new Set(this.pdfAnnotations.map(a => a.pageIndex))) {
        await this.ngxService?.renderPage(pageIndex);
      }
      await this.waitRender();
      if (!current()) {
        return;  // another copy: its own load restores its annotations
      }
      const annotations = this.pdfAnnotations;
      this.pdfAnnotations = [];
      if (annotations.length > 0) {
        // one editor mode for the whole restore: without one, pdf.js enters
        // and leaves a mode for each annotation added (slow, and it threw
        // on pages still rendering)
        await this.setEditorMode(MODE_INK);
        const removed = annotations.filter(isRemoved);
        if (removed.length > 0) {
          await this.removeFileAnnotations(removed);
        }
        const added = annotations.filter(a => !isRemoved(a)) as EditorAnnotation[];
        if (added.length > 0 && current()) {
          await this.addAnnotations(added);
        }
      }
      if (!current()) {
        return;
      }
      await this.setEditorMode(this.editorMode);
      this.loadedAnnotations = JSON.stringify(this.getAnnotations());
      this.loading = false;
      this.onAnnotationsLoaded.emit(true);
    });
  }
}
