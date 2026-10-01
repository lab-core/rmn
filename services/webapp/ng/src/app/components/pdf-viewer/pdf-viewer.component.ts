import { Component, Input, Output, EventEmitter, OnChanges, ChangeDetectionStrategy, ViewChild } from '@angular/core';
import { NgxExtendedPdfViewerService, EditorAnnotation, PdfTextEditorComponent, pdfDefaultOptions } from 'ngx-extended-pdf-viewer';


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

  pdfAnnotations: EditorAnnotation[] = [];
  pdfViewerInitialized: boolean = false;
  pdfModified: boolean = false;
  pdfRendered: boolean = false;

  @Output() onAnnotationsLoaded = new EventEmitter<boolean>();

  @ViewChild(PdfTextEditorComponent)
  pdfTextEditor: PdfTextEditorComponent;

  private timeout: number = 80;

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
  }

  public isWriting() {
    return this.pdfTextEditor?.isSelected ?? false;
  }

  public async renderAnnotations(annotations: EditorAnnotation[], pdfModified: boolean=false) {
    if (annotations) {
      // a drawing saved by pdf.js 4 (`paths` an array) makes pdf.js 6 throw,
      // which drops every annotation restored with it: leave those out
      const readable = annotations.filter(a => a?.annotationType !== 15 || !Array.isArray(a.paths));
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
    // check if pdf has been modified
    if (onlyIfModified && !this.pdfModified) {
      return undefined;
    } else {
      const editedPdfData = await this.ngxService?.getCurrentDocumentAsBlob();
      return new File([editedPdfData], filename, { type: editedPdfData.type });
    }
  }

  public getAnnotations() {
    return this.ngxService?.getSerializedAnnotations();
  }

  /** Adds the annotations in one call: one undo step, and no object shared with the caller. */
  async addAnnotations(annotations: EditorAnnotation[]) {
    const deepClones: EditorAnnotation[] = JSON.parse(JSON.stringify(annotations));
    await this.ngxService?.addEditorAnnotation(deepClones);
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

  async onAnnotationEdited() {
    this.pdfModified = true;
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
      if (annotations.length > 0) {
        await this.addAnnotations(annotations);
      }
      this.onAnnotationsLoaded.emit(true);
    });
  }
}
