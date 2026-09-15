/**
 * The copy the dashboard's "Recherche index" points the correction pages at.
 *
 * Stored per task in localStorage as the copy's identity: the file name,
 * shared by the whole copy and by each of its per-question documents, and
 * the whole copy's document index (each question's document has its own).
 * A position would not do: the dashboard, the correction page and the
 * matricule page each order their lists differently, which is how the old
 * `<job>_copy` key sent graders to the wrong copy.
 */

export const SELECTED_COPY_SUFFIX = '_dashboard_copy';

export interface SelectedCopy {
  document_index: number;
  basename?: string;
}

export function selectedCopyKey(jobId: string): string {
  return `${jobId}${SELECTED_COPY_SUFFIX}`;
}

export function selectedCopy(jobId: string): SelectedCopy | null {
  try {
    const raw = localStorage.getItem(selectedCopyKey(jobId));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    return typeof parsed?.document_index === 'number' ? parsed : null;
  } catch {
    return null;  // storage unavailable or an old value in another format
  }
}

/** Position in `exams` of the selected copy, -1 when it is not there (the
 *  student has no document for this question, or nothing is selected). The
 *  file name identifies a per-question document, the document index a whole
 *  copy on the matricule page. */
export function selectedCopyIndex(jobId: string, exams: { document_index: number; basename?: string }[]): number {
  const selected = selectedCopy(jobId);
  if (!selected) {
    return -1;
  }
  const byName = selected.basename
    ? exams.findIndex((e) => e.basename === selected.basename)
    : -1;
  return byName >= 0 ? byName : exams.findIndex((e) => e.document_index === selected.document_index);
}
