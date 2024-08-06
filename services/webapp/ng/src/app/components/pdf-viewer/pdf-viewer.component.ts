import { Component, ElementRef, Input, Output, EventEmitter, OnInit, OnChanges, SimpleChanges } from '@angular/core';
import { NgxExtendedPdfViewerService, EditorAnnotation, FreeTextEditorAnnotation, InkEditorAnnotation,  pdfDefaultOptions } from 'ngx-extended-pdf-viewer';
import { NotificationService } from 'src/app/services/notification.service';
import { PDFSource } from 'src/app/services/documents.service';


@Component({
  selector: 'app-pdf-viewer',
  templateUrl: './pdf-viewer.component.html',
  styleUrls: ['./pdf-viewer.component.css']
})
export class PDFViewerComponent implements OnInit, OnChanges {

  @Input({required: true}) pdfUrl: string;
  @Input() hideToolbar: boolean = false;

  pdfAnnotations: EditorAnnotation[] = [];
  pdfViewerInitialized: boolean = false;
  pdfModified: boolean = false;
  pdfRendered: boolean = false;

  timeout: number = 50;

  @Output() onAnnotationsLoaded = new EventEmitter<boolean>();

  constructor(private notificationService: NotificationService,
    private ngxService: NgxExtendedPdfViewerService) {
      pdfDefaultOptions.doubleTapZoomsInHandMode = false;
      pdfDefaultOptions.doubleTapZoomsInTextSelectionMode = false;
      pdfDefaultOptions.doubleTapResetsZoomOnSecondDoubleTap = false;
  }

  async ngOnInit(): Promise<void> {
    console.log("Init pdf viewer");
  }

  async ngOnChanges(changes: SimpleChanges) {
    this.pdfModified = false;
    this.pdfRendered = false;
  }

  public async renderAnnotations(annotations: EditorAnnotation[]) {
    if (annotations) {
      this.pdfAnnotations = [ ...this.pdfAnnotations, ...annotations];
      // if pdf already rendered, call loadAnnotations(). Otherwise, it will be called naturlaly
      setTimeout(() => {
        if (this.pdfRendered) {
          setTimeout(() => { this.loadAnnotations(); }, this.timeout);
        }
      });
    }
  }

  public async getRenderedPdfFile(filename: string, onlyIfModified: boolean=false) {
    if (onlyIfModified && !this.pdfModified) {
      return undefined;
    } else {
      const editedPdfData = await this.ngxService?.getCurrentDocumentAsBlob();
      return new File([editedPdfData], filename, { type: editedPdfData.type });
    }
  }

  public getAnnotations() {
    return this.ngxService.getSerializedAnnotations();
  }

  async onPdfLoaded(e) {}

  async onPageRendered(e) {
    if (!this.pdfRendered) {
      this.pdfRendered = true;
      setTimeout(() => { this.initializePdfViewer() }, this.timeout);
      setTimeout(() => { this.loadAnnotations() }, this.timeout);
    }
  }

  async onAnnotationEdited(e) {
    this.pdfModified = true;
  }

  initializePdfViewer(): void {
    if (!this.pdfViewerInitialized) {
      try {
        this.ngxService.editorInkColor = '#FF0000';
        this.ngxService.editorInkThickness = 2;
        this.ngxService.editorFontColor = '#FF0000';
        this.ngxService.editorFontSize = 14;
        this.pdfViewerInitialized = true;
      } catch (e) {
        setTimeout(() => { this.initializePdfViewer() }, this.timeout);
      }
    }
  }

  loadAnnotations() {
    setTimeout(() => {
      this.pdfAnnotations.forEach(a => {
        this.ngxService.addEditorAnnotation(a);
      });
      this.pdfAnnotations = [];
      this.onAnnotationsLoaded.emit(true);
    });
  }

  undoChange() {
    let annotations: EditorAnnotation[] = this.ngxService.getSerializedAnnotations() || [];
    // search for all InkEditorAnnotation (annotationType = 15)
    const inkAnnotations: EditorAnnotation[] = annotations.filter(a => a.annotationType == 15);

    // if any ink annotations to remove
    if (inkAnnotations.length > 0) {
      // remove last element
      let lastInkAnnotation: InkEditorAnnotation = inkAnnotations[inkAnnotations.length-1] as InkEditorAnnotation;
      if (lastInkAnnotation.paths.length > 1) {
        lastInkAnnotation.paths.pop();  // remove last element
      } else {
        // remove last annotation
        inkAnnotations.pop();
      }
      // remove all InkEditorAnnotation (annotationType = 15)
      const filter = (serial: any) => serial.annotationType === 15;
      this.ngxService.removeEditorAnnotations(filter);
      // re add all of them minus the last element
      inkAnnotations.forEach(a => {
        this.ngxService.addEditorAnnotation(a);
      });
    } else {
      this.notificationService.showInfo("Aucune annotation à enlever. Veuillez utiliser une version précédente si nécessaire.", "Info");
    }
  }

  redoChange() {
    let annotations: EditorAnnotation[] = this.ngxService.getSerializedAnnotations() || [];
    // search for all InkEditorAnnotation (annotationType = 15)
    const inkAnnotations: EditorAnnotation[] = annotations.filter(a => a.annotationType == 15);

    // if any ink annotations to remove
    if (inkAnnotations.length > 0) {
      // remove last element
      let lastInkAnnotation: InkEditorAnnotation = inkAnnotations[inkAnnotations.length-1] as InkEditorAnnotation;
      if (lastInkAnnotation.paths.length > 1) {
        lastInkAnnotation.paths.pop();  // remove last element
      } else {
        // remove last annotation
        inkAnnotations.pop();
      }
      // remove all InkEditorAnnotation (annotationType = 15)
      const filter = (serial: any) => serial.annotationType === 15;
      this.ngxService.removeEditorAnnotations(filter);
      // re add all of them minus the last element
      inkAnnotations.forEach(a => {
        this.ngxService.addEditorAnnotation(a);
      });
    } else {
      this.notificationService.showInfo("Aucune annotation à enlever. Veuillez utiliser une version précédente si nécessaire.", "Info");
    }
  }

  // function getMousePos(canvas, evt) {
  //     var rect = canvas.getBoundingClientRect();
  //     return {
  //       x: evt.clientX - rect.left,
  //       y: evt.clientY - rect.top
  //     };
  //   }
  //   canvas.addEventListener('mousemove', function(evt) {
  //     var mousePos = getMousePos(canvas, evt);
  //     console.log('Mouse position: ' + mousePos.x + ',' + mousePos.y);
  //   }, false);


}
