/**
 * Opt-in diagnostics. Off by default so nothing a user says or types reaches the console.
 *
 * Turn on in the browser console:  localStorage.setItem('bytex_debug', '1')   (then reload)
 * Turn off:                         localStorage.removeItem('bytex_debug')
 *
 * Never pass raw speech, transcripts or command text to debugLog; log lengths/states instead.
 */
function readFlag(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem('bytex_debug') === '1';
  } catch {
    return false;
  }
}

const enabled = readFlag();

export function debugLog(...args: unknown[]): void {
  if (enabled) console.log(...args);
}
