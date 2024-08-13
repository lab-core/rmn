import { Component, OnInit, Inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { NotificationService } from 'src/app/services/notification.service';
import { UserService } from 'src/app/services/user.service';
import { SERVER_URL } from 'src/app/utils';
import { PDFDocument } from 'pdf-lib';
import * as saveAs from 'file-saver';
import * as JSZip from 'jszip';


export interface DialogData {
  jobId: string;
  index: string;
  jobName: string;
  nPagesPerQuestion: Map<string, number>;
  examsList: Array<any>;
}

@Component({
  selector: 'pdf-management-dialog',
  templateUrl: './pdf-management-dialog.component.html',
  styleUrls: ['./pdf-management-dialog.component.css']
})
export class PdfManagementDialogComponent implements OnInit {

  constructor(public dialogRef: MatDialogRef<PdfManagementDialogComponent>,
    private http: HttpClient,
    private userService: UserService,
    private notificationService: NotificationService,
    @Inject(MAT_DIALOG_DATA) public data: DialogData) { }

  // default max copies per pdf value
  maxCopiesPerPdf: number = 40;

  ngOnInit(): void {}

  
  async downloadAllFilesAsZip() {
    this.notificationService.showInfo('Téléchargement des copies en cours...', 'Information');
    const zip = new JSZip();
    const mergedDocs: { [key: string]: PDFDocument[] } = {};

    for (const exam of this.data.examsList) {
        if (exam["status"] !== 'NOT_READY') {
            const formdata: FormData = new FormData();
            this.userService.addTokens(formdata);
            formdata.append('job_id', this.data.jobId);
            formdata.append('document_index', exam["document_index"].toString());
            formdata.append('questions', 'true');

            await this.http.post(`${SERVER_URL}document/download`, formdata, { responseType: 'blob' })
                .toPromise()
                .then(async data => {
                    const arrayBuffer = await data.arrayBuffer();
                    const pdfDoc = await PDFDocument.load(arrayBuffer);
                    const fileName = exam["filename"];
                    const questionIndex = exam["question"];

                    if (!mergedDocs[questionIndex]) {
                        mergedDocs[questionIndex] = [await PDFDocument.create()];
                    }

                    let cDoc = mergedDocs[questionIndex][mergedDocs[questionIndex].length - 1];
                    if (cDoc.getPageCount() >= this.maxCopiesPerPdf * pdfDoc.getPageCount()) {
                      cDoc = await PDFDocument.create();
                      mergedDocs[questionIndex].push(cDoc);
                    }

                    const copiedPages = await cDoc.copyPages(pdfDoc, pdfDoc.getPageIndices());
                    copiedPages.forEach((page) => {
                        cDoc.addPage(page);
                    });
                })
                .catch((error) => {
                    console.error(`Error downloading file ${exam["filename"]}:`, error);
                    this.notificationService.showError(`Erreur lors du téléchargement du fichier ${exam["filename"]}`, 'Erreur de téléchargement');
                });
        }
    }

    for (const questionIndex of Object.keys(mergedDocs)) {
        for (let i = 0; i < mergedDocs[questionIndex].length; i++) {
            const doc = mergedDocs[questionIndex][i];
            if (doc.getPageCount() > 0) {
                const mergedPdfBytes = await doc.save();
                const blob = new Blob([mergedPdfBytes], { type: 'application/pdf' });
                zip.file(`${questionIndex}/${questionIndex}${i > 0 ? `_${i}` : ''}.pdf`, blob);
            }
        }
    }

    const zipName = this.data.index && this.data.index !== "Tout sélectionner"
        ? `${this.data.jobName}_Q${this.data.index}.zip`
        : `${this.data.jobName}.zip`;

    zip.generateAsync({ type: 'blob' })
        .then((content) => {
            saveAs(content, zipName);
        });

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

  async readFileSync(file: File) {
     return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve(reader.result);
      };
      reader.onerror = reject;
      reader.readAsArrayBuffer(file);
    });
  }

  async uploadZipFile(file: File) {
    const nPagesPerQuestionArray = this.data.nPagesPerQuestion;
    const nPagesPerQuestion = new Map<string, number>(nPagesPerQuestionArray);
    const zip = new JSZip();

    try {
        let mergedFiles = new Map<string,ArrayBuffer>();
        if (file.name.endsWith('.pdf')) {
          mergedFiles[file.name] = await this.readFileSync(file);
        } else {
          const zipContent = await JSZip.loadAsync(file);
          const zipMergedFiles = Object.keys(zipContent.files).filter(filename => filename.endsWith('.pdf'));
          for (const f of zipMergedFiles) {
            const pdfDoc = await zipContent.file(f).async('arraybuffer');
            mergedFiles[f] = pdfDoc;
          }
        }

        // loading and merge PDFs based on their question indices
        // sort names to process them in the right order
        let keys = Object.keys(mergedFiles);
        keys.sort();
        const mergedPDFDocs = {};
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
            }
        }

        // processing each question index and replace the original documents
        for (const questionIndex of Object.keys(mergedPDFDocs)) {
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
            }
        }

        const finalZipBlob = await zip.generateAsync({ type: 'blob' });
        const finalZipFile = new File([finalZipBlob], 'split_documents.zip', { type: 'application/zip' });

        const uploadFormData = new FormData();
        this.userService.addTokens(uploadFormData);
        uploadFormData.append('job_id', this.data.jobId);
        uploadFormData.append('file', finalZipFile);
        uploadFormData.append('questions', 'true');

        await this.http.post(`${SERVER_URL}/documents/replace`, uploadFormData).toPromise()
            .then((response) => {
              if(response) {
                console.log('Files replaced successfully', response);
                this.notificationService.showSuccess('Fichiers remplacés avec succès!', 'Succès');
                this.dialogRef.close({hasUploadedZip: true});
              } else {
                this.notificationService.showError('Erreur lors du remplacement des fichiers', 'Erreur');
              }
            })
            .catch((uploadError) => {
                console.error('Error replacing files:', uploadError);
                this.notificationService.showError('Erreur lors du remplacement des fichiers', 'Erreur');
            });
    } catch (zipError) {
        console.error('Error processing zip file:', zipError);
        this.notificationService.showError('Erreur lors du traitement du fichier zip', 'Erreur');
    }
  }
}
