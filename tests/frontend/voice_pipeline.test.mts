// Frontend unit tests for the sentence-level speech pipeline (pure TypeScript modules, no browser needed).
// Run from the repo root:  node --test tests/frontend/
import test from 'node:test';
import assert from 'node:assert/strict';
import { SpeechChunker, cleanForSpeech, CODE_ON_SCREEN_SENTENCE } from '../../ByteX/src/lib/speechChunker.ts';
import { pickBestVoice } from '../../ByteX/src/lib/voiceSelection.ts';
import { LatencyMarks } from '../../ByteX/src/lib/latencyMarks.ts';

// ---- helpers -------------------------------------------------------------------------------------------------
function rng(seed: number) {
  let s = seed;
  return () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296; };
}

function speak(parts: string[], opts = {}): string[] {
  const c = new SpeechChunker(opts);
  const out: string[] = [];
  for (const p of parts) out.push(...c.push(p));
  out.push(...c.flush());
  return out;
}

function chunkings(text: string): string[][] {
  const r = rng(42);
  const all = [[text], text.split('')];
  for (let k = 0; k < 20; k++) {
    const parts: string[] = [];
    for (let i = 0; i < text.length;) { const n = 1 + Math.floor(r() * 7); parts.push(text.slice(i, i + n)); i += n; }
    all.push(parts);
  }
  return all;
}

// ---- SpeechChunker -------------------------------------------------------------------------------------------
test('same sentences regardless of how the stream is chunked', () => {
  const texts = [
    'Hello there. How are you today? I am fine!',
    'First point.\nSecond point.\nThird point.\nFourth point.',
    'Here is code:\n```python\nprint("hi.")\n```\nThat is all. Done.',
    'Use e.g. a loop. Version 3.5 works well. Really?',
  ];
  for (const text of texts) {
    const expected = speak([text], { unlimited: true });
    assert.ok(expected.length > 0, text);
    for (const parts of chunkings(text)) assert.deepEqual(speak(parts, { unlimited: true }), expected, JSON.stringify(parts));
  }
});

test('never speaks a partial sentence or partial word', () => {
  const c = new SpeechChunker();
  assert.deepEqual(c.push('Hello wor'), []);
  assert.deepEqual(c.push('ld.'), []);          // terminator seen, but the next character has not arrived yet
  assert.deepEqual(c.push(' Next'), ['Hello world.']);
  assert.deepEqual(c.push(' one is here.'), []);
  assert.deepEqual(c.flush(), ['Next one is here.']);
});

test('code blocks are never spoken; a single on-screen sentence replaces them', () => {
  const text = 'Here you go:\n```js\nconst secret = 1;\nconsole.log(secret);\n```\nRun it with node.';
  for (const parts of chunkings(text)) {
    const spoken = speak(parts, { unlimited: true });
    const joined = spoken.join(' ');
    assert.ok(!/secret|console|const /.test(joined), joined);
    assert.equal(spoken.filter((s) => s === CODE_ON_SCREEN_SENTENCE).length, 1, joined);
    assert.ok(joined.includes('Run it with node.'));
  }
});

test('fence split across chunks is handled and an unterminated block stays silent', () => {
  assert.ok(!speak(['Sure.\n``', '`py\nx = 1\n``', '`\nDone here.'], { unlimited: true }).join(' ').includes('x = 1'));
  const open = speak(['Sure thing.\n```py\nprint(1)\nprint(2)'], { unlimited: true }).join(' ');
  assert.ok(!open.includes('print'));
});

test('JSON / tool-call / reasoning text is never spoken', () => {
  const protocol = [
    '{"name": "delete_file", "arguments": {"path": "x"}}',
    '<tool>{"name": "x"}</tool>',
    '<tool_call>{"name": "x"}</tool_call>',
    '<think>secret reasoning</think>',
    '  \n {"tool_use": {"name": "x"}}',
  ];
  for (const text of protocol) for (const parts of chunkings(text)) assert.deepEqual(speak(parts, { unlimited: true }), [], text);
});

test('a marker in the middle of a message stops speech after the text before it', () => {
  const text = 'Let me check that for you. <tool>{"name": "web_search"}</tool> and then more words follow here.';
  for (const parts of chunkings(text)) {
    const joined = speak(parts, { unlimited: true }).join(' ');
    assert.equal(joined, 'Let me check that for you.');
  }
});

test('a lookalike such as "<3" is spoken once it is clear it is not a marker', () => {
  const text = 'I really like <3 pizza night. It is great.';
  for (const parts of chunkings(text)) assert.ok(speak(parts, { unlimited: true }).join(' ').includes('pizza night'));
});

test('markdown, urls and list markers are cleaned before speech', () => {
  assert.equal(cleanForSpeech('**Bold** [docs](https://x.dev/a) and https://y.dev/z'), 'Bold docs and link');
  assert.equal(cleanForSpeech('- first item'), 'first item');
  assert.equal(cleanForSpeech('2. second item'), 'second item');
  assert.deepEqual(speak(['1. Alpha is first.\n2. Beta is second.\n'], { unlimited: true }), ['Alpha is first.', 'Beta is second.']);
});

test('default speech is limited to the first few sentences; unlimited speaks all', () => {
  const text = 'One is a number. Two is a number. Three is a number. Four is a number. Five is a number.';
  assert.equal(speak([text]).length, 3);
  assert.equal(speak([text], { unlimited: true }).length, 5);
  const long = ('A fairly long sentence about nothing in particular that keeps going. ').repeat(20);
  assert.ok(speak([long]).join(' ').length <= 500 + 80);
});

test('flush after everything was spoken does not repeat anything (no duplicate speech on COMPLETE)', () => {
  const c = new SpeechChunker({ unlimited: true });
  const first = [...c.push('Complete sentence one. Complete sentence two. '), ...c.flush()];
  assert.deepEqual(first, ['Complete sentence one.', 'Complete sentence two.']);
  assert.deepEqual(c.flush(), []);
});

test('reset() clears all state for the next message', () => {
  const c = new SpeechChunker();
  c.push('{"x": 1}');
  assert.ok(c.isSuppressed);
  c.reset();
  assert.deepEqual([...c.push('Fine now, thanks. '), ...c.flush()], ['Fine now, thanks.']);
});

// ---- voice selection: the ORIGINAL behaviour must be preserved ------------------------------------------------
// Verbatim copy of TTSService.getBestVoice from audit-backup-2026-10-26-voice.tgz (the version before the streaming change).
function originalGetBestVoice<T extends { name: string; lang: string; voiceURI: string }>(voices: T[], targetLang: string = 'en-US'): T | null {
  if (!voices.length) return null;
  const priorityKeywords = ['natural', 'neural', 'online', 'google', 'aria', 'guy', 'jenny', 'ana', 'zira'];
  for (const kw of priorityKeywords) {
    const match = voices.find((v) =>
      v.lang.toLowerCase().startsWith(targetLang.slice(0, 2).toLowerCase()) &&
      (v.name.toLowerCase().includes(kw) || v.voiceURI.toLowerCase().includes(kw))
    );
    if (match) return match;
  }
  const langMatch = voices.find((v) => v.lang.toLowerCase() === targetLang.toLowerCase());
  if (langMatch) return langMatch;
  const enMatch = voices.find((v) => v.lang.toLowerCase().startsWith('en'));
  if (enMatch) return enMatch;
  return voices[0] || null;
}

const v = (name: string, lang = 'en-US', uri = name) => ({ name, lang, voiceURI: uri });

test('automatic voice choice is identical to the original algorithm on random voice lists', () => {
  const r = rng(99);
  const names = ['Daniel', 'Samantha', 'Google US English', 'Microsoft Aria Online (Natural)', 'Microsoft Guy Online', 'Jenny', 'Zira', 'Ana',
    'Fred', 'Albert', 'Alex', 'Lekha', 'Google हिन्दी', 'Neural Voice', 'Kathy', 'Rishi', 'Tessa'];
  const langs = ['en-US', 'en-GB', 'en-IN', 'hi-IN', 'fr-FR', 'es-ES', 'EN-us'];
  const targets = ['en-US', 'en-GB', 'hi-IN', 'fr-FR', 'de-DE', 'en'];
  for (let k = 0; k < 500; k++) {
    const voices = Array.from({ length: Math.floor(r() * 12) }, () => v(names[Math.floor(r() * names.length)], langs[Math.floor(r() * langs.length)]));
    for (const t of targets) assert.equal(pickBestVoice(voices, t), originalGetBestVoice(voices, t));
  }
});

test('original priority order: keywords in order, then exact language, then English, then first voice', () => {
  assert.equal(pickBestVoice([v('Samantha'), v('Google US English'), v('Microsoft Aria Online (Natural)')])?.name, 'Microsoft Aria Online (Natural)'); // "natural" before "google"
  assert.equal(pickBestVoice([v('Samantha'), v('Google US English')])?.name, 'Google US English');
  assert.equal(pickBestVoice([v('Daniel', 'en-GB'), v('Alex', 'en-US')], 'en-US')?.name, 'Alex');        // exact language
  assert.equal(pickBestVoice([v('Lekha', 'hi-IN'), v('Daniel', 'en-GB')], 'fr-FR')?.name, 'Daniel');     // English fallback
  assert.equal(pickBestVoice([v('Lekha', 'hi-IN')], 'fr-FR')?.name, 'Lekha');                            // first voice
  assert.equal(pickBestVoice([], 'en-US'), null);
});

// ---- latency marks -------------------------------------------------------------------------------------------
test('latency marks log durations once per turn and never any text', () => {
  let now = 1000;
  const lines: string[] = [];
  const m = new LatencyMarks(() => now, (l) => lines.push(l));
  assert.equal(m.markFirstText(), null);          // nothing before a submit
  m.markSubmit();
  now = 1350; assert.equal(m.markFirstText(), 350);
  now = 1400; assert.equal(m.markFirstText(), null);
  now = 1900; assert.equal(m.markFirstSpeech(), 900);
  assert.equal(m.markFirstSpeech(), null);
  assert.deepEqual(lines, ['[ByteX Latency] first_ai_text_ms=350', '[ByteX Latency] first_speech_ms=900']);
  m.markSubmit(); now = 2000;
  assert.equal(m.markFirstSpeech(), 100);          // marks reset on the next submit
});

// ---- real macOS voice list ---------------------------------------------------------------------------------------
// English voices reported by speechSynthesis.getVoices() in the Claude desktop app's browser pane on the user's Mac
// on 2026-10-26 (180 voices in total). A Chrome profile may add network "Google ..." voices, which the original
// algorithm prefers (keyword "google").
const REAL_MAC_EN = [
  ['Rishi', 'en-IN'], ['Albert', 'en-US'], ['Bad News', 'en-US'], ['Bahh', 'en-US'], ['Bells', 'en-US'], ['Boing', 'en-US'],
  ['Bubbles', 'en-US'], ['Cellos', 'en-US'], ['Daniel', 'en-GB'], ['Eddy (English (United Kingdom))', 'en-GB'],
  ['Eddy (English (United States))', 'en-US'], ['Flo (English (United Kingdom))', 'en-GB'], ['Flo (English (United States))', 'en-US'],
  ['Fred', 'en-US'], ['Good News', 'en-US'], ['Grandma (English (United Kingdom))', 'en-GB'], ['Grandma (English (United States))', 'en-US'],
  ['Grandpa (English (United Kingdom))', 'en-GB'], ['Grandpa (English (United States))', 'en-US'], ['Jester', 'en-US'], ['Junior', 'en-US'],
  ['Karen', 'en-AU'], ['Kathy', 'en-US'], ['Moira', 'en-IE'], ['Organ', 'en-US'], ['Ralph', 'en-US'],
  ['Reed (English (United Kingdom))', 'en-GB'], ['Reed (English (United States))', 'en-US'], ['Rocko (English (United Kingdom))', 'en-GB'],
  ['Rocko (English (United States))', 'en-US'], ['Samantha', 'en-US'], ['Sandy (English (United Kingdom))', 'en-GB'],
  ['Sandy (English (United States))', 'en-US'], ['Shelley (English (United Kingdom))', 'en-GB'], ['Shelley (English (United States))', 'en-US'],
  ['Superstar', 'en-US'], ['Tessa', 'en-ZA'], ['Trinoids', 'en-US'], ['Whisper', 'en-US'], ['Wobble', 'en-US'], ['Zarvox', 'en-US'],
].map(([name, lang]) => v(name, lang));

test('on the captured Mac list the original algorithm yields the first en-US voice (no keyword voices are installed there)', () => {
  assert.equal(pickBestVoice(REAL_MAC_EN, 'en-US')?.name, 'Albert');
  assert.equal(pickBestVoice([...REAL_MAC_EN, v('Google US English')], 'en-US')?.name, 'Google US English');
});

