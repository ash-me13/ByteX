/**
 * Voice-turn latency marks. Logs durations only (never message text) to the browser console:
 *   [ByteX Latency] first_ai_text_ms=...   time from submitting a message to the first assistant text
 *   [ByteX Latency] first_speech_ms=...    time from submitting a message to the first audible speech
 */
type Clock = () => number;

const defaultClock: Clock = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

export class LatencyMarks {
  private submitAt: number | null = null;
  private firstTextAt: number | null = null;
  private firstSpeechAt: number | null = null;

  private clock: Clock;
  private log: (line: string) => void;

  constructor(clock: Clock = defaultClock, log: (line: string) => void = (l) => console.info(l)) {
    this.clock = clock;
    this.log = log;
  }

  markSubmit(): void {
    this.submitAt = this.clock();
    this.firstTextAt = null;
    this.firstSpeechAt = null;
  }

  markFirstText(): number | null {
    if (this.submitAt === null || this.firstTextAt !== null) return null;
    this.firstTextAt = this.clock();
    const ms = Math.round(this.firstTextAt - this.submitAt);
    this.log(`[ByteX Latency] first_ai_text_ms=${ms}`);
    return ms;
  }

  markFirstSpeech(): number | null {
    if (this.submitAt === null || this.firstSpeechAt !== null) return null;
    this.firstSpeechAt = this.clock();
    const ms = Math.round(this.firstSpeechAt - this.submitAt);
    this.log(`[ByteX Latency] first_speech_ms=${ms}`);
    return ms;
  }
}

export const latencyMarks = new LatencyMarks();
export default latencyMarks;
