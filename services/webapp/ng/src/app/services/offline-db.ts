import Dexie, { Table } from 'dexie';
import { PDFSource } from './pdf-source';


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
  tag?: string;
  file64?: any;
  updated?: boolean;
  questionIndex: string;
  jobId?: string;
  index?: number;  // the document index, unique with jobId
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
    // one row per (job, document): a second "corriger hors ligne" used to
    // duplicate every copy (bulkAdd), and markOffline added a status row each
    // time so isOffline() could read a stale one
    this.version(2).stores({
      statusItems: '++id, &jobId',
      copyItems: '++id, jobId, &[jobId+index]',
    }).upgrade(tx => tx.table('copyItems').toCollection().modify((copy: OfflineCopy) => {
      copy.index = copy.index ?? copy.pdfSrcJSON?.index;
    }));
  }

  setCurrentJobId(jobId: string) {
    this.jobId = jobId;
  }

  private requireJobId(): string {
    if (!this.jobId) {
      throw new Error('You need to set a current jobId for offline db!');
    }
    return this.jobId;
  }

  async markOffline() {
    const jobId = this.requireJobId();
    const existing = await this.statusItems.get({ jobId });
    this.statusId = await this.statusItems.put({ id: existing?.id, jobId, offline: true });
  }

  async isOffline() {
    const value = await this.statusItems.get({ jobId: this.requireJobId() });
    if (value) {
      this.statusId = value.id;
      return value.offline;
    }
    return false;
  }

  async markOnline() {
    await this.statusItems.where({ jobId: this.requireJobId() }).delete();
    this.statusId = undefined;
  }

  async getAllCopies(): Promise<OfflineCopy[]> {
    const allCopies: OfflineCopy[] = await this.copyItems.where({ jobId: this.requireJobId() }).toArray();
    for (const copy of allCopies) {
      copy.pdfSrc = new PDFSource();
      await copy.pdfSrc.loadDict(copy.pdfSrcJSON);
    }
    return allCopies;
  }

  /** The row stored for a copy: its pdf as JSON (pdfSrcJSON), never the live
   *  PDFSource (object URL, blob) which is rebuilt by getAllCopies. */
  private async row(copy: OfflineCopy, jobId: string): Promise<OfflineCopy> {
    copy.pdfSrcJSON = await copy.pdfSrc.toJSONDict();
    copy.jobId = jobId;
    copy.index = copy.pdfSrc.index;
    const { pdfSrc, ...stored } = copy;
    return stored as OfflineCopy;
  }

  /** Replace the offline copies of the current job with ``copies`` and mark it offline. */
  async saveAllCopies(copies: Map<number, OfflineCopy>) {
    const jobId = this.requireJobId();
    const originals = Array.from(copies.values());
    const rows: OfflineCopy[] = [];
    for (const copy of originals) {
      delete copy.id;
      rows.push(await this.row(copy, jobId));
    }
    await this.transaction('rw', this.copyItems, this.statusItems, async () => {
      await this.copyItems.where({ jobId }).delete();
      const keys = await this.copyItems.bulkAdd(rows, { allKeys: true });
      for (let i = 0; i < keys.length; ++i) {
        originals[i].id = keys[i];
      }
      await this.markOffline();
    });
  }

  async updateCopy(copy: OfflineCopy) {
    await this.copyItems.put(await this.row(copy, copy.jobId ?? this.requireJobId()));
  }

  async deleteAllCopies(copies: Map<number, OfflineCopy>) {
    const keys: number[] = [];
    for (const copy of copies.values()) {
      if (copy.id !== undefined) {
        keys.push(copy.id);
      }
    }
    await this.copyItems.bulkDelete(keys);
  }

  /** Every offline copy and status of every job: called on logout, so the
   *  student pdfs stored for offline correction do not outlive the session on
   *  a shared machine. */
  async clearAll() {
    await this.copyItems.clear();
    await this.statusItems.clear();
    this.statusId = undefined;
  }
}

export const db = new OfflineDB();
