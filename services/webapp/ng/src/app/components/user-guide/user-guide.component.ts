import { HttpClient } from '@angular/common/http';
import { AfterViewChecked, ChangeDetectionStrategy, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Marked, Tokens } from 'marked';
import { Subscription, combineLatest, firstValueFrom } from 'rxjs';

import { GUIDE_CHAPTERS, GuideChapter, headingId } from '../../help/guide';

const GUIDE_DIR = 'assets/guide/';

/**
 * The markdown of the guide turned into HTML for the app. The files are
 * written for GitHub, so their relative links are rewritten here: an image
 * `img/x.png` is served from assets/guide/img, a link to `05-x.md#y` opens
 * the chapter in the app.
 */
export function renderGuide(markdown: string): string {
  const marked = new Marked({
    gfm: true,
    walkTokens: (token) => {
      if (token.type === 'image') {
        const image = token as Tokens.Image;
        if (!/^([a-z]+:|\/)/i.test(image.href)) {
          image.href = GUIDE_DIR + image.href.replace(/^\.\//, '');
        }
      } else if (token.type === 'link') {
        const link = token as Tokens.Link;
        const chapter = /^(?:\.\/)?([\w-]+)\.md(#.*)?$/.exec(link.href);
        if (chapter) {
          link.href = `user-guide/${chapter[1]}${chapter[2] || ''}`;
        }
      }
    },
  });
  return marked.parse(markdown, {async: false}) as string;
}

/** marked percent-encodes the accents of the links: é is %C3%A9 in an href. */
function safeDecode(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

/**
 * The user guide: the chapters of src/assets/guide, one at a time, with the
 * table of contents on the side. /user-guide/<chapter>#<heading> opens a
 * section directly, which is where the help bubbles of the screens lead.
 */
@Component({
    selector: 'app-user-guide',
    templateUrl: './user-guide.component.html',
    styleUrls: ['./user-guide.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class UserGuideComponent implements OnInit, AfterViewChecked, OnDestroy {
  @ViewChild('content', {static: true}) content: ElementRef<HTMLElement>;

  chapters: GuideChapter[] = GUIDE_CHAPTERS;
  current: GuideChapter = GUIDE_CHAPTERS[0];
  html = '';
  error = '';
  private subscription: Subscription;
  // the section to show once the chapter is on screen; undefined: nothing to do
  private pendingFragment: string | null | undefined;

  constructor(private http: HttpClient, private route: ActivatedRoute, private router: Router) { }

  ngOnInit(): void {
    this.subscription = combineLatest([this.route.paramMap, this.route.fragment]).subscribe(
      ([params, fragment]) => this.show(params.get('chapter'), fragment));
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }

  async show(file: string | null, fragment: string | null): Promise<void> {
    const chapter = this.chapters.find((c) => c.file === file) || this.chapters[0];
    if (chapter !== this.current || !this.html) {
      this.current = chapter;
      try {
        const markdown = await firstValueFrom(
          this.http.get(GUIDE_DIR + chapter.file + '.md', {responseType: 'text'}));
        this.html = renderGuide(markdown);
        this.error = '';
      } catch {
        this.html = '';
        this.error = 'Ce chapitre du guide n\'a pas pu être chargé.';
      }
    }
    this.pendingFragment = fragment;
  }

  // the sanitizer drops the ids of the headings: they are set on the DOM
  // once Angular has written the HTML of the chapter
  ngAfterViewChecked(): void {
    if (this.pendingFragment !== undefined) {
      const fragment = this.pendingFragment;
      this.pendingFragment = undefined;
      this.setHeadingIds();
      this.scrollTo(fragment);
    }
  }

  setHeadingIds(): void {
    const headings = this.content.nativeElement.querySelectorAll('h1, h2, h3, h4');
    headings.forEach((heading: HTMLElement) => heading.id = headingId(heading.textContent || ''));
  }

  scrollTo(fragment: string | null): void {
    const id = fragment ? safeDecode(fragment) : '';
    const element = id ? this.content.nativeElement.querySelector(`[id="${CSS.escape(id)}"]`) : null;
    if (element) {
      element.scrollIntoView();
    } else {
      this.content.nativeElement.scrollTop = 0;
    }
  }

  /** Links between chapters stay in the app; the others open in a new tab. */
  onContentClick(event: MouseEvent): void {
    const anchor = (event.target as HTMLElement).closest('a');
    const href = anchor?.getAttribute('href');
    if (!href) {
      return;
    }
    if (href.startsWith('user-guide/') || href.startsWith('#')) {
      event.preventDefault();
      const [path, fragment] = href.startsWith('#')
        ? [`user-guide/${this.current.file}`, href.substring(1)]
        : href.split('#');
      this.router.navigate(['/' + path], {fragment: fragment ? safeDecode(fragment) : undefined});
    } else if (/^https?:/.test(href)) {
      event.preventDefault();
      window.open(href, '_blank', 'noopener');
    }
  }
}
