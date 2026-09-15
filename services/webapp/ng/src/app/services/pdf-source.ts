import { EditorAnnotation } from 'ngx-extended-pdf-viewer';

/**
 * A downloaded copy: its object URL, version and annotation layers, plus the
 * local draft of its annotations (localStorage, per job and document index).
 * In its own module so the offline database and the user service can import
 * it without pulling the HTTP service (and its dependency cycle) along.
 */
export class PDFSource {
  index: number;
  version: number;
  annotations: EditorAnnotation[];
  url?: string;
  blob?: Blob;
  timestamp_min: number;
  lastVersion: number;
  modified: boolean;

  constructor(index: number=undefined, url: string=undefined, version=undefined) {
    this.index = index;
    this.url = url;
    this.version = version;
    this.timestamp_min = Date.now() / 60000;
    this.annotations = [];
  }

  destroy() {
    this.revokeURL();
  }

  setLastVersion(lastVersion: number) {
    this.lastVersion = lastVersion;
    if (this.version === undefined || this.version > this.lastVersion) {
      this.version = this.lastVersion;
    }
  }

  isOlderThan(minutes) {
    const t = Date.now() / 60000;
    return t - this.timestamp_min > minutes;
  }

  canBeUsed(minutes, version=undefined) {
    return (minutes === undefined || !this.isOlderThan(minutes)) &&
          (version === undefined || this.version === version);
  }

  toMinimalJSONDict() {
    return {
      index: this.index,
      version: this.version,
      annotations: this.annotations,
      timestamp_min: this.timestamp_min,
      lastVersion: this.lastVersion,
    }
  }

  async toJSONDict() {
    const json = this.toMinimalJSONDict();
    const blob = await fetch(this.url).then(r => r.blob());
    json['base64'] = await PDFSource.readBlobSync(blob);
    return json;
  }

  static async readBlobSync(blob: Blob | File): Promise<string | ArrayBuffer> {
     return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve(reader.result);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);  // base64 string of the pdf
    });
  }

  async loadMinimalDict(dict) {
    this.index = dict['index'];
    this.version = dict['version'];
    this.annotations = dict['annotations'];
    this.timestamp_min = dict['timestamp_min'];
    this.lastVersion = dict['lastVersion'];
  }

  async loadDict(dict) {
    this.loadMinimalDict(dict);
    this.blob = dict['blob'] || await fetch(dict['base64']).then(async (r) => r.blob());
    if (this.blob) {
      this.url = window.URL.createObjectURL(this.blob);
    }
  }

  revokeURL() {
    if (this.url) {
      URL.revokeObjectURL(this.url);
    }
  }

  save(jobId: string) {
    const jsonDict = this.toMinimalJSONDict();
    localStorage.setItem(`${jobId}_pdf_${this.index}`, JSON.stringify(jsonDict));
  }

  restore(jobId: string) {
    const jsonDict = localStorage.getItem(`${jobId}_pdf_${this.index}`);
    if (jsonDict) {
      const dict = JSON.parse(jsonDict);
      if (this.version === dict.version) {
        this.loadMinimalDict(dict);
        this.modified = true;
      }
    }
  }

  clear(jobId: string) {
    localStorage.removeItem(`${jobId}_pdf_${this.index}`);
  }

  static clearAll(jobId: string, size: number) {
    for (let i = 0; i < size; i++) {
      localStorage.removeItem(`${jobId}_pdf_${i}`);
    }
  }
}
