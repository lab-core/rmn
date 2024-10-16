import Dexie, { Table } from 'dexie';
import { PDFSource } from 'src/app/services/documents.service';


interface StatusItem {
  id?: number;
  jobId: string;
  offline: boolean;
}

export interface OfflineCopy {
  id?: number;
  pdfSrc: PDFSource;
  pdfSrcJSON?: any;
  grade?: number;
  status: string;
  file64?: any;
  updated?: boolean;
  questionIndex: string;
  jobId?: string;
}

class OfflineDB extends Dexie {
  statusItems: Table<StatusItem, number>;
  copyItems: Table<OfflineCopy, number>;
  jobId: string;
  statusId: number;

  constructor() {
    super('ngdexieliveQuery');
    this.version(1).stores({
      statusItems: '++id, jobId',
      copyItems: '++id, jobId',
    });
  }

  setCurrentJobId(jobId: string) {
    this.jobId = jobId;
  }

  async markOffline() {
    this.statusId = await db.statusItems.put({
      jobId: this.jobId,
      offline: true
    });
  }

  async isOffline() {
    if (!this.jobId) {
      throw "You need to set a current jobId for offline db!";
    }
    const value = await db.statusItems.get({jobId: this.jobId});
    if (value) {
      this.statusId = value.id;
      return value.offline;
    }
    return false;
  }

  async markOnline() {
    await db.statusItems.delete(this.statusId);
  }

  async getAllCopies(): Promise<OfflineCopy[]> {
    const allCopies: OfflineCopy[] = await db.copyItems.where({'jobId': this.jobId}).toArray();
    for (let copy of allCopies) {
      copy.pdfSrc = new PDFSource();
      await copy.pdfSrc.loadDict(copy.pdfSrcJSON);
    }
    return allCopies;
  }

  async saveAllCopies(copies: Map<number, OfflineCopy>) {
    const allCopies: OfflineCopy[] = [];
    for (let copy of copies.values()) {
      copy.pdfSrcJSON = await copy.pdfSrc.toJSONDict();
      copy.jobId = this.jobId;
      allCopies.push(copy);
    }
    const keys = await db.copyItems.bulkAdd(allCopies, {allKeys: true});
    for (let i=0; i<keys.length; ++i) {
      allCopies[i].id = keys[i];
    }
    await this.markOffline();
  }

  async updateCopy(copy: OfflineCopy) {
    copy.pdfSrcJSON = await copy.pdfSrc.toJSONDict();
    await db.copyItems.put(copy);
  }

  async deleteAllCopies(copies: Map<number, OfflineCopy>) {
    const keys: number[] = [];
    for (let copy of copies.values()) {
      keys.push(copy.id);
    }
    await db.copyItems.bulkDelete(keys)
  }
}

export const db = new OfflineDB();
