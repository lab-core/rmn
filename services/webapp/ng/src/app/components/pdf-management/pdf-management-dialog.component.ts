import { Component, Inject, ChangeDetectionStrategy } from '@angular/core';
import { HttpClient, HttpEvent, HttpEventType } from '@angular/common/http';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { DocumentsService, PDFSource } from 'src/app/services/documents.service';
import { SERVER_URL } from 'src/app/utils';
import { OfflineCopy } from 'src/app/services/offline-db';
import { PDFDocument, PDFArray, PDFName, PDFNumber, PDFString, rgb, StandardFonts } from 'pdf-lib';
import { saveAs } from 'file-saver';
import { csvLines, detectSeparator, splitCsvLine } from 'src/app/csv';
import JSZip from 'jszip';
import { DocumentStatus } from '../../generated/rmn-contracts';


export interface DialogData {
  jobId: string;
  index: string;
  jobName: string;
  nPagesPerQuestion: Map<string, number>;
  nMaxPointsPerQuestion: Map<string, number>;
  bonusEnabledMap: Map<string, boolean>;
  examsList: Array<any>;
  offlineCopies: Map<number, OfflineCopy>;
}

@Component({
    selector: 'pdf-management-dialog',
    templateUrl: './pdf-management-dialog.component.html',
    styleUrls: ['./pdf-management-dialog.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class PdfManagementDialogComponent {

  processing: boolean = false;
  // read the grades off the annotated pages instead of importing a csv
  readGrades: boolean = false;

  percentageDone: number = 0;
  info: string = "";

  // default max copies per pdf value
  maxCopiesPerPdf: number = 40;

  setmaxCopies(event: any) {
    this.maxCopiesPerPdf = event.target.valueAsNumber;
  }

  csvSeparator: string = ",";

  setCsvSeparator(event: any) {
    this.csvSeparator = event.target.value;
  }

  constructor(public dialogRef: MatDialogRef<PdfManagementDialogComponent>,
              private http: HttpClient,
              private userService: UserService,
              private docService: DocumentsService,
              private notificationService: NotificationService,
              @Inject(MAT_DIALOG_DATA) public data: DialogData) {
  }

  async downloadAllFilesAsZip() {
    this.notificationService.showInfo('Téléchargement des copies en cours...', 'Information');
    const zip = new JSZip();
    const mergedDocs: { [key: string]: PDFDocument[] } = {};
    const rows: { [key: string]: string[][] } = {};

    this.percentageDone = 0;
    this.processing = true;
    this.info = "Downloading and Merging";
    let i = 0;
    for (const exam of this.data.examsList) {
      if (exam["status"] !== DocumentStatus.NOT_READY) {
        let pdfFileSrc;
        if (exam["offline"]) {
          pdfFileSrc = this.data.offlineCopies.get(exam["document_index"])?.file64 ||
            this.docService.getAvailablePdfSource(this.data.jobId, exam["document_index"])?.url;
          if (!pdfFileSrc) {
            this.notificationService.showError(`Copie ${exam["document_index"]} introuvable hors ligne.`, 'Erreur');
            this.processing = false;
            return;
          }
        } else {
          // fetch latest pdf file
          pdfFileSrc = (await this.docService.getPdfSource(this.data.jobId, exam["document_index"], false, undefined, -1)).url;
        }

        const pdfBuffer = await fetch(pdfFileSrc).then(r => r.arrayBuffer());
        const pdfDoc = await PDFDocument.load(pdfBuffer);
        const fileName = exam["filename"];
        const question = exam["question"];

        if (!mergedDocs[question]) {
          mergedDocs[question] = [await PDFDocument.create()];
        }

        let cDoc = mergedDocs[question].at(-1);
        if (cDoc.getPageCount() >= this.maxCopiesPerPdf * pdfDoc.getPageCount()) {
          cDoc = await PDFDocument.create();
          mergedDocs[question].push(cDoc);
        }

        if (!rows[question]) {
          rows[question] = [["Fichier", "Index", "Note"]];
        }
        const i = mergedDocs[question].length - 1;
        rows[question].push([`${question}${i > 0 ? `_${i}` : ''}.pdf`,
          exam.document_index,
          exam.grade !== undefined ? exam.grade : '']);
        await this.addCopyIndex(pdfDoc, exam.document_index);

        const copiedPages = await cDoc.copyPages(pdfDoc, pdfDoc.getPageIndices());
        copiedPages.forEach((page) => {
          cDoc.addPage(page);
          this.addAnnotation(cDoc, cDoc.getPageCount() - 1);
        });
      }
      i++;
      this.percentageDone = Math.round(100 * i / this.data.examsList.length);
    }

    for (const question of Object.keys(mergedDocs)) {
      for (let i = 0; i < mergedDocs[question].length; i++) {
        const doc = mergedDocs[question][i];
        if (doc.getPageCount() > 0) {
          const pdfFileName = `${question}${i > 0 ? `_${i}` : ''}.pdf`;
          doc.setSubject(pdfFileName);
          const mergedPdfBytes = await doc.save();
          const blob = new Blob([mergedPdfBytes as Uint8Array<ArrayBuffer>], {type: 'application/pdf'});
          zip.file(`${question}/${pdfFileName}`, blob);
        }
      }
    }

    for (const question of Object.keys(rows)) {
      let csvContent = "";
      rows[question].forEach((rowArray) => {
        const row = rowArray.join(this.csvSeparator);
        csvContent += row + "\r\n";
      });
      zip.file(`${question}/notes.csv`, csvContent);
    }

    const zipName = this.data.index && this.data.index !== "Tout sélectionner"
      ? `${this.data.jobName}_Q${this.data.index}.zip`
      : `${this.data.jobName}.zip`;

    // the success toast and the close used to run before the zip existed
    try {
      const content = await zip.generateAsync({type: 'blob'});
      saveAs(content, zipName);
    } catch (error) {
      console.error(error);
      this.notificationService.showError('La création du zip a échoué.', 'Erreur');
      this.processing = false;
      return;
    }

    this.processing = false;
    this.notificationService.showSuccess('Téléchargement terminé!', 'Success');
    this.dialogRef.close({hasDownloadedZip: true});
  }

  async addCopyIndex(pdfDoc, index, pageNumber = 0) {
    const font = await pdfDoc.embedFont(StandardFonts.Helvetica);
    const fontSize = 12;
    const text = `Copie ${index}`;
    const textWidth = font.widthOfTextAtSize(text, fontSize);

    const page = pdfDoc.getPages()[pageNumber];
    const {width, height} = page.getSize();
    page.drawText(text, {
      x: width - textWidth - 5, // 20px right margin
      y: height - fontSize - 5, // 20px top margin
      size: fontSize,
      font,
      color: rgb(0.8, 0, 0), // dark red
    });
  }

  async hideCopyIndex(pdfDoc, pageNumber) {
    const font = await pdfDoc.embedFont(StandardFonts.Helvetica);
    const fontSize = 12;
    const text = `Copie 1000`;
    const textWidth = font.widthOfTextAtSize(text, fontSize);
    const page = pdfDoc.getPages()[pageNumber];
    const {width, height} = page.getSize();
    page.drawRectangle({
      x: width - textWidth - 10, // match the original drawText x
      y: height - fontSize - 10, // match the original y
      width: textWidth + 10, // make sure it covers the text
      height: fontSize + 10,
      color: rgb(1, 1, 1), // white
    });
  }

  addAnnotation(pdfDoc, pageNumber) {
    // Create a PDFArray for Rect manually
    const rectArray = PDFArray.withContext(pdfDoc.context);
    rectArray.push(PDFNumber.of(0));
    rectArray.push(PDFNumber.of(0));
    rectArray.push(PDFNumber.of(0));
    rectArray.push(PDFNumber.of(0));

    // Create a PDFArray for the RGB color (red)
    const colorArray = PDFArray.withContext(pdfDoc.context);
    colorArray.push(PDFNumber.of(1)); // R
    colorArray.push(PDFNumber.of(0)); // G
    colorArray.push(PDFNumber.of(0)); // B

    const textAnnotation = pdfDoc.context.obj({
      Type: PDFName.of('Annot'),
      Subtype: PDFName.of('Text'),
      Rect: rectArray, // Position (x1, y1, x2, y2)
      Contents: PDFString.of(`Page${pageNumber} - NE PAS TOUCHER!`),
      Name: PDFString.of(`Page${pageNumber}`),
      T: PDFString.of('RMN'),
      C: colorArray, // RGB color for the icon (red)
      Open: false,
    });
    const annotationRef = pdfDoc.context.register(textAnnotation);

    // Check for existing annotations and add new annotation
    const page = pdfDoc.getPages()[pageNumber];
    const existingAnnots = page.node.lookup(PDFName.of('Annots'));
    if (existingAnnots instanceof PDFArray) {
      existingAnnots.push(annotationRef);
    } else {
      const annotsArray = PDFArray.withContext(pdfDoc.context);
      annotsArray.push(annotationRef);
      page.node.set(PDFName.of('Annots'), annotsArray);
    }
  }

  checkAnnotationAndRemove(pdfDoc, pageNumber) {
    const page = pdfDoc.getPages()[pageNumber];
    const annots = page.node.lookup(PDFName.of('Annots'));
    const newAnnotsArray = PDFArray.withContext(pdfDoc.context);
    for (let i = 0; i < annots.size(); i++) {
      const annotRef = annots.get(i);
      const annot = page.doc.context.lookup(annotRef);
      const title = annot.get(PDFName.of('T'));
      if (title instanceof PDFString && title.decodeText() === 'RMN') {
        const contents = annot.get(PDFName.of('Contents')).decodeText();
        if (contents.startsWith('Page') && !contents.startsWith(`Page${pageNumber}`)) {
          return false;
        }
      } else {
        newAnnotsArray.push(annotRef);
      }
    }
    page.node.set(PDFName.of('Annots'), newAnnotsArray);
    return true;
  }

  onFileSelected(event: any) {
    const file = event.target.files[0];
    if (file) {
      this.uploadZipFile(file);
    }
  }

  onDrop(event: DragEvent) {
    event.preventDefault();
    const file = event.dataTransfer?.files[0];
    if (file) {
      this.uploadZipFile(file);
    }
  }

  onDragOver(event: DragEvent) {
    event.preventDefault();
  }

  async readFileSync(file: File | Blob, text = false): Promise<string | ArrayBuffer> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve(reader.result);
      };
      reader.onerror = reject;
      text ? reader.readAsText(file) : reader.readAsArrayBuffer(file);
    });
  }

  async parseCSVGrades(filename: string, file: File | Blob, grades: any) {
    // Entire file
    const text: string = String(await this.readFileSync(file, true));
    const lines = csvLines(text);
    if (lines.length === 0) {
      this.notificationService.showError(`Csv file (${filename}) is empty.`, 'Erreur!');
      return -1;
    }

    // header: separator, then the Note and Index columns
    const sep = detectSeparator(lines[0]);
    let values = splitCsvLine(lines[0], sep).map((v) => v.trim());
    const nCols = values.length;
    const gradeIndex = values.indexOf('Note');
    const docIndex = values.indexOf('Index');
    if (gradeIndex === -1 || docIndex === -1) {
      this.notificationService.showError(`Csv file (${filename}) does not have either Note or/and Index columns.`, 'Erreur!');
      return -1;
    }

    // find grades for indices
    let n = 0;
    for (const line of lines.slice(1)) {
      values = splitCsvLine(line, sep).map((v) => v.trim());
      if (values.length !== nCols) {
        this.notificationService.showError(`Csv file (${filename}) has an invalid row: ${line}`, 'Erreur!');
        continue;
      }
      const grade = parseFloat(values[gradeIndex].replace(',', '.'));
      if (isNaN(grade)) {
        continue;  // no grade for this copy
      }
      // parseInt never throws: a non-numeric Index used to be dropped silently
      const index = parseInt(values[docIndex], 10);
      if (isNaN(index)) {
        this.notificationService.showError(`Csv file (${filename}) has an invalid Index for row: ${line}`, 'Erreur!');
        continue;
      }
      grades[index] = grade;
      ++n;
    }
    return n;
  }

  async timeout(ms = 0) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async uploadZipFile(file: File) {
    const nPagesPerQuestionArray = this.data.nPagesPerQuestion;
    const nPagesPerQuestion = new Map<string, number>(nPagesPerQuestionArray);
    const zip = new JSZip();

    const grades = {};
    const mergedFiles = new Map<string, ArrayBuffer>();
    const pdfFilesByIndex = new Map<string, string>();
    const mergedPDFDocs = {};
    const errorMessages = {};
    const errorCopies = {};

    this.percentageDone = 0;
    this.processing = true;
    this.info = 'Loading (1/4)';
    let i = 0;
    try {
      const zipContent = await JSZip.loadAsync(file);
      const zipMergedFiles = Object.keys(zipContent.files).filter((filename) => filename.endsWith('.pdf'));
      const zipMergedCSV = Object.keys(zipContent.files).filter((filename) => filename.endsWith('.csv'));
      const nLength = zipMergedFiles.length + zipMergedCSV.length;

      for (const f of zipMergedFiles) {
        if (!f.startsWith('__MACOSX')) {
          const match = f.match(/Q(\d+)(?=(_\d+)?.pdf$)/);
          if (!match) {
            this.notificationService.showError(`Ignoring this pdf document name that does not match a question: ${name}.`, 'Warning');
          } else {
            const pdfDoc = await zipContent.file(f).async('arraybuffer');
            mergedFiles[f] = pdfDoc;
            // get index after question index
            const questionIndex = parseInt(match[1]);  // get only the number without Q
            let suffix = f.slice(match.index! + match[0].length);  // get suffix after question index
            suffix = suffix.slice(0, suffix.lastIndexOf('.'));  // remove extension
            suffix = suffix.replace('_', '');  // remove leading underscore if any
            const indexKey = suffix ? parseInt(suffix) : 0;
            pdfFilesByIndex[1e6 * questionIndex + indexKey] = f;  // large multiplier to avoid collisions
          }

          i++;
          this.percentageDone = Math.round(50 * i / nLength);
        }
      }

      for (const f of zipMergedCSV) {
        if (!f.startsWith('__MACOSX')) {
          const csvDoc = await zipContent.file(f).async('blob');
          await this.parseCSVGrades(f, csvDoc, grades);
          i++;
          this.percentageDone = Math.round(50 * i / nLength);
        }
      }

      this.info = 'Processing (2/4)';
      // loading and merge PDFs based on their question indices
      // sort names to process them in the right order
      const keys = Object.keys(pdfFilesByIndex);
      keys.sort();
      i = 0;
      for (const index of keys) {
        const pdfFile = pdfFilesByIndex[index];
        try {
          const pdfDoc = await PDFDocument.load(mergedFiles[pdfFile]);

          // recover question index
          const match = pdfFile.match(/Q\d+(?=(_\d+)?.pdf$)/);
          const questionIndex = match[0];

          // initialize merged PDF doc if not already done
          if (!mergedPDFDocs[questionIndex]) {
            mergedPDFDocs[questionIndex] = await PDFDocument.create();
            errorMessages[questionIndex] = [];
          }

          const errorMessagesDoc = [];
          const pdfSubject = pdfDoc.getSubject();
          const pdfName = pdfFile.split('/').length > 0 ? pdfFile.split('/').pop() : pdfFile;
          if (pdfSubject !== pdfName) {
            this.notificationService.showError(`The pdf document name has been changed or the subject metadata has been modified: ${pdfName} instead of ${pdfSubject}.`, 'Error');
            this.processing = false;
            return;
          }

          const pagesPerQuestion = nPagesPerQuestion.get(questionIndex);
          if (!(pagesPerQuestion > 0)) {
            // a question missing from the task definition used to flow as NaN
            // through the page arithmetic and produce empty documents
            this.notificationService.showError(`Nombre de pages inconnu pour ${questionIndex}.`, 'Erreur');
            this.processing = false;
            return;
          }
          for (let j = 0; j < pdfDoc.getPageCount(); j++) {
            try {
              if (!this.checkAnnotationAndRemove(pdfDoc, j)) {
                this.notificationService.showError(`The page order of the pdf document has been changed: page ${j + 1} is not at the right place.`, 'Error');
                this.processing = false;
                return;
              }
              if (j % pagesPerQuestion === 0) {
                await this.hideCopyIndex(pdfDoc, j);
              }
            } catch (pdfError) {
              const p = j + 1;
              const errorMessage = `Error checking annotation on page ${p} of document ${pdfFile}`;
              console.error(errorMessage, pdfError);
              errorMessagesDoc.push(j);
            }
          }

          const totalPageCount = pdfDoc.getPageCount();

          let k = 0;
          const pageCount = mergedPDFDocs[questionIndex].getPageCount();
          const copiedPages = await mergedPDFDocs[questionIndex].copyPages(pdfDoc, pdfDoc.getPageIndices());
          copiedPages.forEach((page) => {
            if (errorMessagesDoc.includes(k)) {
              errorMessages[questionIndex].push(pageCount + k);
            }
            k++;
            mergedPDFDocs[questionIndex].addPage(page);
          });
        } catch (pdfError) {
          console.error(`Error processing merged file: ${pdfFile}`, pdfError);
          this.notificationService.showError(`Error processing merged file: ${pdfFile}.`, 'Erreur');
        }
        i++;
        this.percentageDone = 50 + Math.round(50 * i / keys.length);
      }

      // processing each question index and replace the original documents
      let nQuestionExams = 0;
      for (const questionIndex of Object.keys(mergedPDFDocs)) {
        const totalPageCount = mergedPDFDocs[questionIndex].getPageCount();
        const pagesPerQuestion = nPagesPerQuestion.get(questionIndex);
        nQuestionExams += totalPageCount / pagesPerQuestion;
      }

      this.info = 'Splitting (3/4)';
      this.percentageDone = 0;
      i = 0;
      for (const questionIndex of Object.keys(mergedPDFDocs)) {
        await this.timeout();
        const mergedDoc = mergedPDFDocs[questionIndex];
        const totalPageCount = mergedDoc.getPageCount();
        const originalDocs = this.data.examsList.filter((exam) => exam.question === questionIndex);
        const pagesPerQuestion = nPagesPerQuestion.get(questionIndex);

        let startPage = 0;
        let j = 0;
        errorCopies[questionIndex] = [];
        for (const originalDoc of originalDocs) {
          try {
            const singlePagePdf = await PDFDocument.create();
            const endPage = startPage + pagesPerQuestion;

            if (totalPageCount < endPage) {
              const miss = (endPage - totalPageCount) / pagesPerQuestion;
              const message = `The merged document for ${questionIndex} does not have enough pages for ${originalDoc.filename}.pdf. Required: ${endPage}, available: ${totalPageCount}, missing: ${miss} copies.`;
              console.warn(message);
              this.notificationService.showWarning(message, 'Warning');
              break;
            }

            const copiedPages = await singlePagePdf.copyPages(mergedDoc, Array.from({length: pagesPerQuestion}, (_, l) => startPage + l));
            let k = j * pagesPerQuestion;
            copiedPages.forEach((page) => {
              if (errorMessages[questionIndex].includes(k) && !errorCopies[questionIndex].includes(j + 1)) {
                errorCopies[questionIndex].push(j + 1);
              }
              k++;
              singlePagePdf.addPage(page);
            });

            const pdfBytes = await singlePagePdf.save();
            const blob = new Blob([pdfBytes as Uint8Array<ArrayBuffer>], {type: 'application/pdf'});
            const fileName = originalDoc.filename + '.pdf';
            zip.file(fileName, blob);

            startPage = endPage;
            j++;
          } catch (innerError) {
            console.error(`Error processing original document: ${originalDoc.filename}.pdf`, innerError);
            this.notificationService.showError(`Error processing original document: ${originalDoc.filename}.pdf`, 'Erreur');
          }
          i++;
          this.percentageDone = Math.round(100 * i / nQuestionExams);
        }
      }

      for (const questionIndex of Object.keys(errorCopies)) {
        if (errorCopies[questionIndex].length > 0) {
          const message = `The ${questionIndex} have errors on copies: ${errorCopies[questionIndex].join(', ')}.`;
          console.warn(message);
          this.notificationService.showWarning(message + ' Check them.', 'Warning');
        }
      }

      const finalZipBlob = await zip.generateAsync({type: 'blob'});
      const finalZipFile = new File([finalZipBlob], 'split_documents.zip', {type: 'application/zip'});

      // update exam grades: a negative grade or one above the question's
      // maximum goes back to validation; an unknown maximum refuses nothing
      // (it used to send every imported grade back with one blanket error)
      const suspicious: number[] = [];
      const unknown: string[] = [];
      for (const docIndex of Object.keys(grades)) {
        const docIdx = parseInt(docIndex, 10);
        const exam = this.data.examsList.find((e) => {
          return e.document_index === docIdx;
        });
        if (!exam) {
          unknown.push(docIndex);
          continue;
        }
        exam.grade = grades[docIndex];
        const total = this.data.nMaxPointsPerQuestion.get(exam.question);
        if (exam.grade < 0 || (total !== undefined && exam.grade > total + 1e-3)) {
          suspicious.push(docIdx);
          exam.status = DocumentStatus.TO_VALIDATE;
        } else {
          exam.status = DocumentStatus.VALIDATED;
        }
      }
      if (unknown.length > 0) {
        this.notificationService.showWarning(`Aucune copie pour les index ${unknown.join(', ')} du csv.`, 'Attention');
      }
      if (suspicious.length > 0) {
        this.notificationService.showError(
          `Les notes des copies ${suspicious.join(', ')} sont négatives ou dépassent le maximum: elles restent à valider.`, 'Erreur');
      }

      const uploadFormData = new FormData();
      this.userService.addTokens(uploadFormData);
      uploadFormData.append('job_id', this.data.jobId);
      uploadFormData.append('file', finalZipFile);
      uploadFormData.append('grades', JSON.stringify(grades));
      uploadFormData.append('questions', 'true');
      // with no csv there is nothing to fill the grades with, so ask the
      // server to read what was written on the pages instead
      if (this.readGrades) {
        uploadFormData.append('read_grades', 'true');
      }

      this.percentageDone = 0;
      this.info = 'Uploading (4/4)';
      const sub = this.http.post(`${SERVER_URL}documents/replace`, uploadFormData,
        {reportProgress: true, observe: 'events'})
        .subscribe(
          (data) => {
            if (data.type === HttpEventType.UploadProgress) {
              this.percentageDone = data.total ? Math.round(100 * data.loaded / data.total) : 0
            } else if (data.type === HttpEventType.Response) {
              if (data.ok) {
                this.notificationService.showSuccess('Fichiers remplacés avec succès!', 'Succès');
                this.dialogRef.close({hasUploadedZip: true});
              } else {
                this.notificationService.showError('Erreur lors du remplacement des fichiers', 'Erreur');
              }
              sub.unsubscribe();
              this.processing = false;
            }
          }, (uploadError) => {
            console.error('Error replacing files:', uploadError);
            this.notificationService.showError('Erreur lors du remplacement des fichiers', 'Erreur');
            sub.unsubscribe();
            this.processing = false;
          });
    } catch (zipError) {
      console.error('Error processing zip file:', zipError);
      this.notificationService.showError('Erreur lors du traitement du fichier zip', 'Erreur');
      this.processing = false;
    }
  }
}
