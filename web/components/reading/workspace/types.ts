/** View-model rows the reading workspace passes between its panels. */

export interface TranscriptRow {
  locator: number;
  title: string;
  text: string;
  sourceHref: string;
}
