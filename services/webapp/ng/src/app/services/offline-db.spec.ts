import { db, OfflineCopy } from './offline-db';

/** A copy whose pdf source serialises without fetching anything. */
function copy(index: number, status = 'TO VALIDATE'): OfflineCopy {
  const pdfSrc: any = { index, toJSONDict: async () => ({ index, version: 0 }) };
  return { pdfSrc, status, questionIndex: 'Q1' };
}

describe('OfflineDB', () => {
  beforeEach(async () => {
    await db.clearAll();
    db.setCurrentJobId('job-a');
  });

  it('keeps one row per copy and one status per job across repeated saves', async () => {
    const copies = new Map([[1, copy(1)], [2, copy(2)]]);
    await db.saveAllCopies(copies);
    // a second "corriger hors ligne" used to duplicate every copy and add a status row
    await db.saveAllCopies(new Map([[1, copy(1, 'VALIDATED')], [2, copy(2)]]));
    await db.markOffline();

    expect(await db.copyItems.where({ jobId: 'job-a' }).count()).toBe(2);
    expect(await db.statusItems.where({ jobId: 'job-a' }).count()).toBe(1);
    expect(await db.isOffline()).toBeTrue();
    const rows = await db.copyItems.where({ jobId: 'job-a' }).sortBy('index');
    expect(rows.map(r => [r.index, r.status])).toEqual([[1, 'VALIDATED'], [2, 'TO VALIDATE']]);
  });

  it('scopes the copies by job and forgets the status when back online', async () => {
    await db.saveAllCopies(new Map([[1, copy(1)]]));
    db.setCurrentJobId('job-b');
    await db.saveAllCopies(new Map([[1, copy(1)], [5, copy(5)]]));
    expect((await db.copyItems.where({ jobId: 'job-a' }).toArray()).length).toBe(1);
    expect((await db.copyItems.where({ jobId: 'job-b' }).toArray()).length).toBe(2);

    await db.markOnline();
    expect(await db.isOffline()).toBeFalse();
    db.setCurrentJobId('job-a');
    expect(await db.isOffline()).toBeTrue();
  });

  it('updates a copy in place and deletes the given ones', async () => {
    const copies = new Map([[1, copy(1)], [2, copy(2)]]);
    await db.saveAllCopies(copies);
    const first = copies.get(1);
    first.grade = 7;
    await db.updateCopy(first);
    expect(await db.copyItems.where({ jobId: 'job-a' }).count()).toBe(2);
    expect((await db.copyItems.get(first.id)).grade).toBe(7);

    await db.deleteAllCopies(copies);
    expect(await db.copyItems.where({ jobId: 'job-a' }).count()).toBe(0);
  });

  it('refuses to work without a current job', async () => {
    db.setCurrentJobId(undefined);
    await expectAsync(db.isOffline()).toBeRejectedWithError(/current jobId/);
  });

  it('clearAll wipes every job', async () => {
    await db.saveAllCopies(new Map([[1, copy(1)]]));
    await db.clearAll();
    expect(await db.copyItems.count()).toBe(0);
    expect(await db.statusItems.count()).toBe(0);
  });
});
