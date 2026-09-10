import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { ValidationService } from './validation.service';
import { UserService } from './user.service';

// a logged-in user: the real service appends user_id + token to every form
const userStub = {
  addTokens: (form: FormData) => {
    form.append('user_id', 'alice');
    form.append('token', 'tok');
  }
};

describe('ValidationService', () => {
  let service: ValidationService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: UserService, useValue: userStub },
      ]
    });
    service = TestBed.inject(ValidationService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('posts the document update with every optional field when given', async () => {
    const file = new File(['%PDF'], 'copy.pdf');
    const pending = service.validateDocument(
      'job', 3, file, 'Q2', 7.5, 10, 'VALIDATED', 2, [{ id: 1 }], 'ok');

    const req = http.expectOne('/api/document/update');
    expect(req.request.method).toBe('POST');
    const form = req.request.body as FormData;
    expect(form.get('user_id')).toBe('alice');
    expect(form.get('token')).toBe('tok');
    expect(form.get('job_id')).toBe('job');
    expect(form.get('document_index')).toBe('3');
    expect(form.get('question_index')).toBe('Q2');
    expect(form.get('grades')).toBe('7.5');
    expect(form.get('status')).toBe('VALIDATED');
    expect(form.get('version')).toBe('2');
    expect(form.get('annotations')).toBe('[{"id":1}]');
    expect(form.get('tag')).toBe('ok');
    expect(form.get('file')).toEqual(jasmine.any(File));

    req.flush({ response: { status: 'VALIDATED' } });
    expect(await pending).toEqual({ status: 'VALIDATED' });
  });

  it('omits the optional fields when they are undefined but keeps a grade of 0', async () => {
    const pending = service.validateDocument(
      'job', 0, new File([''], 'c.pdf'), undefined, 0, 10, 'TO VALIDATE', undefined, undefined, undefined);

    const req = http.expectOne('/api/document/update');
    const form = req.request.body as FormData;
    expect(form.get('grades')).toBe('0');
    expect(form.has('question_index')).toBeFalse();
    expect(form.has('version')).toBeFalse();
    expect(form.has('annotations')).toBeFalse();
    expect(form.has('tag')).toBeFalse();

    req.flush({ response: 'ok' });
    expect(await pending).toBe('ok');
  });

  it('resolves undefined instead of throwing when the server fails', async () => {
    spyOn(console, 'error');
    const pending = service.validateDocument(
      'job', 0, new File([''], 'c.pdf'), undefined, undefined, 10, 'VALIDATED', undefined, undefined, undefined);

    http.expectOne('/api/document/update').flush({ response: 'nope' }, { status: 500, statusText: 'Error' });

    expect(await pending).toBeUndefined();
    expect(console.error).toHaveBeenCalled();
  });

  it('validateJob sends the moodle flag as 0/1', async () => {
    const pending = service.validateJob('job', true);
    const req = http.expectOne('/api/job/validate');
    const form = req.request.body as FormData;
    expect(form.get('job_id')).toBe('job');
    expect(form.get('moodle_ind')).toBe('1');
    expect(form.get('token')).toBe('tok');
    req.flush({ response: 'OK' });
    expect(await pending).toBe('OK');

    const again = service.validateJob('job', false);
    const second = http.expectOne('/api/job/validate');
    expect((second.request.body as FormData).get('moodle_ind')).toBe('0');
    second.flush({ response: 'OK' });
    await again;
  });
});
