import { Component, OnInit, Inject } from '@angular/core';
import { HttpClient, HttpEvent, HttpEventType } from '@angular/common/http';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { DocumentsService, PDFSource } from 'src/app/services/documents.service';
import { SERVER_URL } from 'src/app/utils';
import { OfflineCopy } from '../offline-db';
import { PDFDocument } from 'pdf-lib';
import { saveAs } from 'file-saver';
import * as JSZip from 'jszip';


export interface DialogData {
  jobId: string;
  index: string;
  jobName: string;
  nPagesPerQuestion: Map<string, number>;
  examsList: Array<any>;
  offlineCopies: Map<number, OfflineCopy>;
}

@Component({
  selector: 'pdf-management-dialog',
  templateUrl: './pdf-management-dialog.component.html',
  styleUrls: ['./pdf-management-dialog.component.css']
})
export class PdfManagementDialogComponent implements OnInit {

  processing: boolean = false;
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
    @Inject(MAT_DIALOG_DATA) public data: DialogData) { }

  async ngOnInit() {
    let e = document.getElementById('maxCopies') as HTMLInputElement;
    e.value = this.maxCopiesPerPdf.toString();
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
        if (exam["status"] !== 'NOT_READY') {
          let pdfFileSrc;
          if (exam["offline"]) {
            pdfFileSrc = this.data.offlineCopies.get(exam["document_index"]).file64 ||
                        this.docService.getAvailablePdfSource(this.data.jobId, exam["document_index"]).url;
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
              rows[question] = [["Fichier", "Note", "Index"]];
          }
          let i = mergedDocs[question].length - 1;
          rows[question].push([`${question}${i > 0 ? `_${i}` : ''}.pdf`,
            exam["grade"] != undefined ? exam["grade"] : "",
            exam["document_index"]]);

          const copiedPages = await cDoc.copyPages(pdfDoc, pdfDoc.getPageIndices());
          copiedPages.forEach((page) => {
              cDoc.addPage(page);
          });
        }
        i++;
        this.percentageDone = Math.round(100 * i / this.data.examsList.length);
    }

    for (const question of Object.keys(mergedDocs)) {
        for (let i = 0; i < mergedDocs[question].length; i++) {
            const doc = mergedDocs[question][i];
            if (doc.getPageCount() > 0) {
                const mergedPdfBytes = await doc.save();
                const blob = new Blob([mergedPdfBytes], { type: 'application/pdf' });
                zip.file(`${question}/${question}${i > 0 ? `_${i}` : ''}.pdf`, blob);
            }
        }
    }

    for (const question of Object.keys(rows)) {
      let csvContent = "";
      rows[question].forEach((rowArray) => {
          let row = rowArray.join(this.csvSeparator);
          csvContent += row + "\r\n";
      });
      zip.file(`${question}/notes.csv`, csvContent);
    }

    const zipName = this.data.index && this.data.index !== "Tout sélectionner"
        ? `${this.data.jobName}_Q${this.data.index}.zip`
        : `${this.data.jobName}.zip`;

    zip.generateAsync({ type: 'blob' })
        .then((content) => {
            saveAs(content, zipName);
        });

    this.processing = false;
    this.notificationService.showSuccess('Téléchargement terminé!', 'Success');
    this.dialogRef.close({hasDownloadedZip: true});
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
    var lines = text.split('\n');

   // Check separator
   var line = lines[0].trim();
   let commas = (line.match(/,/g) || []).length;
   let semicolumn = (line.match(/;/g) || []).length;
   const sep = commas >= semicolumn ? ',' : ';';

   // Find index grade
   let values = line.split(sep);
   const nCols = values.length;
   const gradeIndex = values.findIndex((v) => { return v == 'Note'; })
   const docIndex = values.findIndex((v) => { return v == 'Index'; })
   if (gradeIndex == -1 || docIndex == -1) {
     this.notificationService.showError(`Csv file (${filename}) does not have either Note or/and Index columns.`, 'Erreur!')
     return -1;
   }

   // find grades for indices
   let n = 0;
   for (let i=1; i < lines.length; i++) {
     values = lines[i].trim().split(sep);
     if (values.length != nCols) {
       if (lines[i].trim() != "") this.notificationService.showError(`Csv file (${filename}) has an invalid row ${i+1}: ${lines[i]}`, 'Erreur!');
     } else {
       const grade = parseFloat(values[gradeIndex]?.replace(",", "."));
       if (!isNaN(grade)) {
         try {
           const index = parseInt(values[docIndex]);
           grades[index] = grade;
           ++n;
         } catch {
           this.notificationService.showError(`Csv file (${filename}) has an invalid Index for row ${i+1}: ${lines[i]}`, 'Erreur!')
         }
       }
     }
   }
   return n;
  }

  async timeout(ms = 0) {
      return new Promise(resolve => setTimeout(resolve, ms));
  }

  async uploadZipFile(file: File) {
    const nPagesPerQuestionArray = this.data.nPagesPerQuestion;
    const nPagesPerQuestion = new Map<string, number>(nPagesPerQuestionArray);
    const zip = new JSZip();
    const grades = {};

    this.percentageDone = 0;
    this.processing = true;
    this.info = "Loading (1/3)";
    let i = 0;
    try {
        let mergedFiles = new Map<string,ArrayBuffer>();
        if (file.name.endsWith('.pdf')) {
          mergedFiles[file.name] = await this.readFileSync(file);
        } else {
          const zipContent = await JSZip.loadAsync(file);
          const zipMergedFiles = Object.keys(zipContent.files).filter(filename => filename.endsWith('.pdf'));
          const zipMergedCSV = Object.keys(zipContent.files).filter(filename => filename.endsWith('.csv'));
          const nLength = zipMergedFiles.length + zipMergedCSV.length

          for (const f of zipMergedFiles) {
            if (f.startsWith('__MACOSX')) continue;
            const pdfDoc = await zipContent.file(f).async('arraybuffer');
            mergedFiles[f] = pdfDoc;
            i++;
            this.percentageDone = Math.round(50 * i / nLength);
          }

          for (const f of zipMergedCSV) {
            if (f.startsWith('__MACOSX')) continue;
            const csvDoc = await zipContent.file(f).async('blob');
            await this.parseCSVGrades(f, csvDoc, grades);
            i++;
            this.percentageDone = Math.round(50 * i / nLength);
          }
        }

        // loading and merge PDFs based on their question indices
        // sort names to process them in the right order
        let keys = Object.keys(mergedFiles);
        keys.sort();
        const mergedPDFDocs = {};
        i = 0;
        for (const name of keys) {
            try {
                const pdfDoc = await PDFDocument.load(mergedFiles[name]);
                const match = name.match(/Q\d+(?=(_\d+)?.pdf$)/);
                const questionIndex = match ? match[0] : "Unknown";
                if (!mergedPDFDocs[questionIndex]) {
                    mergedPDFDocs[questionIndex] = await PDFDocument.create();
                }

                const totalPageCount = pdfDoc.getPageCount();
                console.log(`The document ${name} has ${totalPageCount} pages.`);

                const copiedPages = await mergedPDFDocs[questionIndex].copyPages(pdfDoc, pdfDoc.getPageIndices());
                copiedPages.forEach((page) => {
                    mergedPDFDocs[questionIndex].addPage(page);
                });
            } catch (pdfError) {
                console.error(`Error processing merged file: ${name}`, pdfError);
                this.notificationService.showError(`Error processing merged file: ${name}.`, 'Erreur');
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

        this.info = "Splitting (2/3)";
        this.percentageDone = 0;
        i = 0;
        for (const questionIndex of Object.keys(mergedPDFDocs)) {
            await this.timeout();
            const mergedDoc = mergedPDFDocs[questionIndex];
            const totalPageCount = mergedDoc.getPageCount();
            const originalDocs = this.data.examsList.filter(exam => exam.question === questionIndex);
            const pagesPerQuestion = nPagesPerQuestion.get(questionIndex);

            let startPage = 0;
            for (const originalDoc of originalDocs) {
                try {
                    const singlePagePdf = await PDFDocument.create();
                    const endPage = startPage + pagesPerQuestion;

                    if (totalPageCount < endPage) {
                        console.warn(`The merged document for ${questionIndex} does not have enough pages for ${originalDoc["filename"]}.pdf. Required: ${endPage}, available: ${totalPageCount}.`);
                        break;
                    }

                    const copiedPages = await singlePagePdf.copyPages(mergedDoc, Array.from({ length: pagesPerQuestion }, (_, k) => startPage + k));
                    copiedPages.forEach((page) => {
                        singlePagePdf.addPage(page);
                    });

                    const pdfBytes = await singlePagePdf.save();
                    const blob = new Blob([pdfBytes], { type: 'application/pdf' });
                    const fileName = originalDoc["filename"] + ".pdf";
                    zip.file(fileName, blob);

                    startPage = endPage;
                } catch (innerError) {
                    console.error(`Error processing original document: ${originalDoc["filename"]}.pdf`, innerError);
                }
                i++;
                this.percentageDone = Math.round(100 * i / nQuestionExams);
            }
        }

        const finalZipBlob = await zip.generateAsync({ type: 'blob' });
        const finalZipFile = new File([finalZipBlob], 'split_documents.zip', { type: 'application/zip' });

        // update exam grades
        for (const docIndex of Object.keys(grades)) {
          const doc_idx = parseInt(docIndex);
          const exam = this.data.examsList.find((e) => { return e['document_index'] == doc_idx; });
          exam['grade'] = grades[docIndex];
          exam['status'] = "VALIDATED";
        }

        const uploadFormData = new FormData();
        this.userService.addTokens(uploadFormData);
        uploadFormData.append('job_id', this.data.jobId);
        uploadFormData.append('file', finalZipFile);
        uploadFormData.append('grades', JSON.stringify(grades));
        uploadFormData.append('questions', 'true');

        this.percentageDone = 0;
        this.info = "Uploading (3/3)";
        const sub = this.http.post(`${SERVER_URL}/documents/replace`, uploadFormData,
                              {reportProgress: true, observe: "events"})
        .subscribe(
          (data) => {
            if (data.type == HttpEventType.UploadProgress) {
              this.percentageDone = data.total ? Math.round(100 * data.loaded / data.total) : 0
            }
            else if (data.type == HttpEventType.Response) {
              if(data.ok) {
                console.log('Files replaced successfully', data);
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
    }
  }
}
