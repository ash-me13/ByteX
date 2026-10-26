/**
 * Turns a stream of ASSISTANT_DELTA text into complete, speakable sentences.
 *
 * Rules (all covered by tests/frontend/speech_chunker.test.mts):
 *  - A sentence is released only after the character that ends it has arrived (so no partial words/sentences).
 *  - Fenced code blocks are never spoken; one short "code is on screen" sentence is spoken when a block closes.
 *  - A message that starts like JSON / a tool call / a reasoning tag is never spoken.
 *  - A reasoning/tool marker that shows up mid-message stops speech for the rest of the message; a possibly
 *    incomplete marker at the end of the buffer is held back until it resolves.
 *  - Markdown decoration, URLs and list markers are removed before speaking.
 *  - By default speech is limited to the first few sentences (the same "highlights" idea the non-streaming path
 *    uses); pass `unlimited: true` to speak everything.
 *
 * Pure TypeScript, no DOM access.
 */

export interface SpeechChunkerOptions {
  maxUnits?: number;
  maxChars?: number;
  unlimited?: boolean;
}

export const CODE_ON_SCREEN_SENTENCE = "I've generated the code and displayed it on screen.";

const ABBREVIATIONS = new Set(['e.g', 'i.e', 'vs', 'mr', 'mrs', 'ms', 'dr', 'st', 'no', 'approx', 'fig', 'inc', 'etc']);
const PROTOCOL_START = /^(?:\{|<\s*(?:tool|think))/i;
const PROTOCOL_ANYWHERE = /<\s*(?:tool_call|tool|think)\b/i;
const PARTIAL_PROTOCOL_TAIL = /<\s*\/?[a-z_]{0,10}$/i;

export function cleanForSpeech(text: string): string {
  return text
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, 'link')
    .replace(/^[\s>*\-•]+(?=\S)/, '')
    .replace(/^\d+[.)]\s+/, '')
    .replace(/[*_~`#]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function hasSpeakableContent(text: string): boolean {
  return /[\p{L}\p{N}]/u.test(text);
}

export class SpeechChunker {
  private readonly maxUnits: number;
  private readonly maxChars: number;
  private readonly unlimited: boolean;

  private pending = '';      // text not yet classified (prose or code)
  private sentence = '';     // prose accumulated for the sentence in progress
  private carry = '';        // very short sentence waiting to be merged with the next one
  private inCode = false;
  private started = false;   // first non-whitespace content seen
  private suppressed = false;
  private units = 0;
  private chars = 0;

  constructor(options: SpeechChunkerOptions = {}) {
    this.unlimited = options.unlimited === true;
    this.maxUnits = options.maxUnits ?? 3;
    this.maxChars = options.maxChars ?? 500;
  }

  get spokenAnything(): boolean {
    return this.units > 0;
  }

  get isSuppressed(): boolean {
    return this.suppressed;
  }

  reset(): void {
    this.pending = '';
    this.sentence = '';
    this.carry = '';
    this.inCode = false;
    this.started = false;
    this.suppressed = false;
    this.units = 0;
    this.chars = 0;
  }

  /** Feed one delta; returns the sentences that are now complete and safe to speak. */
  push(delta: string): string[] {
    if (this.suppressed || !delta) return [];
    this.pending += delta;
    const out: string[] = [];

    if (!this.started) {
      const lead = this.pending.trimStart();
      if (!lead) return out;
      if (PROTOCOL_START.test(lead)) {
        this.suppressed = true;
        this.pending = '';
        return out;
      }
      if (/^<\s*[a-z_]{0,5}$/i.test(lead) && lead.length < 7) return out; // could still become <tool / <think
      this.started = true;
    }

    for (;;) {
      if (this.inCode) {
        const close = this.pending.indexOf('```');
        if (close === -1) {
          this.pending = this.pending.slice(-2); // keep a possible partial closing fence
          break;
        }
        this.pending = this.pending.slice(close + 3);
        this.inCode = false;
        this.emitUnit(CODE_ON_SCREEN_SENTENCE, out, true);
        continue;
      }

      const fence = this.pending.indexOf('```');
      let prose: string;
      if (fence !== -1) {
        prose = this.pending.slice(0, fence);
        this.pending = this.pending.slice(fence + 3);
        this.inCode = true;
        this.consumeProse(prose, out);
        // a sentence cut off by the code block ends there
        if (this.sentence.trim()) this.finishSentence(out, true);
        if (this.suppressed) break;
        continue;
      }

      // No complete fence: hold back trailing backticks (a fence may be arriving) and a possible partial tag.
      const tailTicks = /`{1,2}$/.exec(this.pending);
      const holdTicks = tailTicks ? tailTicks[0].length : 0;
      let body = this.pending.slice(0, this.pending.length - holdTicks);
      const tag = PARTIAL_PROTOCOL_TAIL.exec(body);
      const holdTag = tag ? tag[0].length : 0;
      body = body.slice(0, body.length - holdTag);
      this.pending = this.pending.slice(body.length);
      this.consumeProse(body, out);
      break;
    }
    return out;
  }

  /** End of message: speak whatever sentence is still in progress (code blocks / protocol text stay silent). */
  flush(): string[] {
    const out: string[] = [];
    if (this.suppressed) return out;
    if (!this.inCode) {
      this.consumeProse(this.pending.replace(/`{1,2}$/, ''), out);
      this.pending = '';
      if (!this.suppressed) this.finishSentence(out, true);
    }
    if (this.carry) {
      const rest = this.carry;
      this.carry = '';
      this.emitUnit(rest, out, true);
    }
    this.pending = '';
    return out;
  }

  // -- internals ------------------------------------------------------------------------------------------

  private consumeProse(text: string, out: string[]): void {
    if (!text || this.suppressed) return;
    const marker = PROTOCOL_ANYWHERE.exec(text);
    if (marker) {
      text = text.slice(0, marker.index);
      this.suppressed = true;
    }
    this.sentence += text;
    for (;;) {
      const cut = this.findBoundary(this.sentence);
      if (cut === -1) break;
      const piece = this.sentence.slice(0, cut);
      this.sentence = this.sentence.slice(cut);
      this.emitUnit(piece, out, false);
    }
    if (this.suppressed) {
      this.finishSentence(out, true);
    }
  }

  private finishSentence(out: string[], final: boolean): void {
    const piece = this.sentence;
    this.sentence = '';
    if (piece.trim()) this.emitUnit(piece, out, final);
  }

  /** Index just after the first complete sentence/line in `s`, or -1. Needs the character after the terminator. */
  private findBoundary(s: string): number {
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      if (ch === '\n') {
        if (s.slice(0, i).trim()) return i + 1;
        continue;
      }
      if (ch === '.' || ch === '!' || ch === '?') {
        let j = i + 1;
        while (j < s.length && /["')\]*_]/.test(s[j])) j++;
        while (j < s.length && (s[j] === '.' || s[j] === '!' || s[j] === '?')) j++;
        if (j >= s.length) return -1; // terminator may continue ("..." / "3.5") or the next char has not arrived
        if (!/\s/.test(s[j])) { i = j - 1; continue; }
        if (ch === '.') {
          const word = (/([A-Za-z.]+)$/.exec(s.slice(0, i)) || [])[1] ?? '';
          if (ABBREVIATIONS.has(word.toLowerCase())) { i = j; continue; }
          if (/^\s*\d+$/.test(s.slice(0, i))) { i = j; continue; } // "1. item"
        }
        return j;
      }
    }
    return -1;
  }

  private emitUnit(raw: string, out: string[], force: boolean): void {
    if (this.unlimited ? false : (this.units >= this.maxUnits || this.chars >= this.maxChars)) return;
    const cleaned = cleanForSpeech(raw);
    if (!cleaned || !hasSpeakableContent(cleaned)) return;
    const text = this.carry ? `${this.carry} ${cleaned}` : cleaned;
    this.carry = '';
    if (!force && text.length < 12) {
      this.carry = text; // too short to be worth its own utterance; merge with the next sentence
      return;
    }
    this.units += 1;
    this.chars += text.length;
    out.push(text);
  }
}
