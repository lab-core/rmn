/**
 * Minimal csv helpers for the class lists the app reads (Moodle exports).
 *
 * The previous checks counted separators per line, so a quoted comma in a
 * name rejected the whole file and a byte-order mark (Excel writes one)
 * hid the first column name.
 */

export const CSV_SEPARATORS = [',', ';'] as const;

/** Removes a leading UTF-8 byte-order mark. */
export function stripBom(text: string): string {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

/** Splits one line into fields. A separator or a doubled quote inside a
 *  double-quoted field stays in the field. */
export function splitCsvLine(line: string, sep: string): string[] {
  const fields: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"') {
        if (line[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      quoted = true;
    } else if (c === sep) {
      fields.push(field);
      field = '';
    } else {
      field += c;
    }
  }
  fields.push(field);
  return fields;
}

/** The separator that splits the header into the most fields. */
export function detectSeparator(headerLine: string): string {
  let best: string = CSV_SEPARATORS[0];
  let count = -1;
  for (const sep of CSV_SEPARATORS) {
    const n = splitCsvLine(headerLine, sep).length;
    if (n > count) {
      best = sep;
      count = n;
    }
  }
  return best;
}

/** The non-empty lines of a csv text, BOM removed, CRLF tolerated. */
export function csvLines(text: string): string[] {
  return stripBom(text).split(/\r?\n/).filter((line) => line.trim() !== '');
}
