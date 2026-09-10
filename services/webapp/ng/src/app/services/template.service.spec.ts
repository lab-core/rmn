import { TemplateService } from './template.service';

describe('TemplateService', () => {
  beforeEach(() => localStorage.clear());

  it('restores the current template id from localStorage', () => {
    expect(new TemplateService().getId()).toBeNull();
    localStorage.setItem('templateId', 't1');
    expect(new TemplateService().getId()).toBe('t1');
  });

  it('persists the id and clear() forgets everything', () => {
    const service = new TemplateService();
    service.setId('t2');
    service.setName('Exam');
    service.setLocked(true);
    service.setNQuestions(3);
    const file = new File([''], 'exam.pdf');
    service.setFile(file);

    expect(localStorage.getItem('templateId')).toBe('t2');
    expect(service.getName()).toBe('Exam');
    expect(service.getLocked()).toBeTrue();
    expect(service.getNQuestions()).toBe(3);
    expect(service.getFile()).toBe(file);

    service.clear();
    expect(service.getId()).toBeUndefined();
    expect(service.getName()).toBeUndefined();
    expect(service.getLocked()).toBeFalse();
    expect(service.getNQuestions()).toBe(0);
    expect(localStorage.getItem('templateId')).toBeNull();
  });

  it('creates an object URL per rendered template and revokes the previous one', async () => {
    spyOn(URL, 'createObjectURL').and.returnValues('blob:1', 'blob:2');
    spyOn(URL, 'revokeObjectURL');
    const service = new TemplateService();

    await service.createNewTemplate(new Blob(['a']));
    expect(service.getUrl()).toBe('blob:1');
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();

    await service.createNewTemplate(new Blob(['b']));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:1');
    expect(service.getUrl()).toBe('blob:2');

    service.revokeUrl();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:2');
  });
});
