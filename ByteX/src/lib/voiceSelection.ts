/**
 * Automatic voice choice ("Automatic Best Natural Voice" in Settings).
 *
 * This is the ORIGINAL ByteX behaviour, restored exactly (it was TTSService.getBestVoice before the streaming-speech
 * change). It is a pure function over a minimal voice shape so it can be unit-tested without a browser.
 *
 * Priority order:
 *   1. the first voice, in the browser's own voice-list order, whose language starts with the target language's
 *      first two letters AND whose name or voiceURI contains the first matching keyword of
 *      natural, neural, online, google, aria, guy, jenny, ana, zira   (keywords are tried in that order)
 *   2. a voice whose language equals the target language exactly (first in list order)
 *   3. the first English voice
 *   4. the first voice in the list
 * A voice picked manually in Settings (voiceURI) always overrides this.
 */
export interface VoiceLike {
  name: string;
  lang: string;
  voiceURI: string;
}

const PRIORITY_KEYWORDS = ['natural', 'neural', 'online', 'google', 'aria', 'guy', 'jenny', 'ana', 'zira'];

export function pickBestVoice<T extends VoiceLike>(voices: readonly T[], targetLang: string = 'en-US'): T | null {
  if (!voices.length) return null;

  for (const kw of PRIORITY_KEYWORDS) {
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
