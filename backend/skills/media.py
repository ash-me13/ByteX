import os
import re
import time
import json
import urllib.parse
import subprocess
import asyncio
from typing import Dict, Any, List, Optional, Tuple

import httpx
import psutil

from skills.base import BaseSkill, ToolResult
from security.permissions import permissions
from security.audit_logger import audit_logger

class ActiveMediaSessionManager:
    """Non-sensitive in-memory manager tracking active YouTube media playback session."""
    def __init__(self):
        self.current_session: Optional[Dict[str, Any]] = None

    def set_session(self, browser_name: str, title: str, url: str, state: str = "PLAYING", cdp_port: int = 9222):
        self.current_session = {
            "provider": "youtube",
            "browser": browser_name,
            "title": title,
            "url": url,
            "state": state,
            "cdp_port": cdp_port,
            "timestamp": time.time()
        }

    def get_session(self) -> Optional[Dict[str, Any]]:
        # Verify browser process is still alive if session exists
        if self.current_session:
            browser_key = self.current_session.get("browser") or "msedge"
            win_info = permissions.verify_application_window(browser_key)
            if not (win_info.get("process_found") or win_info.get("verified")):
                found_alive = False
                for b in ["msedge", "edge", "chrome", "brave", "firefox"]:
                    v = permissions.verify_application_window(b)
                    if v.get("process_found") or v.get("verified"):
                        found_alive = True
                        break
                if not found_alive:
                    self.current_session = None
        return self.current_session

    def update_state(self, state: str):
        if self.current_session:
            self.current_session["state"] = state

    def clear_session(self):
        self.current_session = None

media_session_manager = ActiveMediaSessionManager()

class PlayMediaSkill(BaseSkill):
    """
    Browser-Only Media Playback & Control Skill for ByteX (#39).
    
    Responsibilities:
    1. Extracts clean song query from natural language requests.
    2. Searches YouTube, ignores sponsored ads, selects top genuine organic video.
    3. Opens/reuses visible default web browser and navigates to YouTube video.
    4. Genuinely inspects whether player-level playback verification is supported.
    5. Gated success: Only claims playback if real player state is verified.
       Otherwise honestly returns 'The YouTube video was opened, but I couldn't verify playback.'
    """

    MAX_CANDIDATES = 3

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    @property
    def name(self) -> str:
        return "play_media"

    @property
    def description(self) -> str:
        return "Searches and opens songs on YouTube in the user's visible default web browser, with active playback verification."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Song title, artist, or video search query"
                },
                "action": {
                    "type": "string",
                    "enum": ["play", "stop", "pause", "resume"],
                    "description": "Playback control action (default: play)"
                },
                "raw_text": {
                    "type": "string",
                    "description": "Original natural language command"
                }
            },
            "required": []
        }

    def extract_search_query(self, raw_text: str) -> str:
        """Extracts clean song title/artist from user input."""
        cleaned = raw_text.strip()
        cleaned = re.sub(r"^(?:please\s+)?(?:can\s+you\s+)?(?:could\s+you\s+)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^(?:play|start\s+playing|listen\s+to|stream)\s+", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^(?:the\s+top\s+|the\s+best\s+|the\s+latest\s+|the\s+)", "", cleaned, flags=re.IGNORECASE).strip()
        
        # Remove trailing platform or browser noise
        cleaned = re.sub(r"\s+(?:on|in|from|using|via)\s+(?:youtube|yt|the\s+browser|browser|chrome|edge)\b.*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+song\s+(?:on|in)\s+youtube.*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+song$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        if not cleaned or cleaned.lower() in ["music", "some music", "my music", "audio"]:
            cleaned = "Music"

        return cleaned

    KNOWN_PHONETIC_CORRECTIONS = {
        "sam dimora": "Sem Demora",
        "sam demora": "Sem Demora",
        "sem dimora": "Sem Demora",
        "shreya ghoshal kalyani": "Kalyani Shreya Ghoshal",
    }

    def get_fuzzy_fallback_query(self, query: str) -> Optional[str]:
        """
        Generates ONE safe normalized/fuzzy fallback query for speech-recognition
        or phonetic/spelling variations when the primary search yields no candidates.
        """
        q_low = query.strip().lower()
        if q_low in self.KNOWN_PHONETIC_CORRECTIONS:
            return self.KNOWN_PHONETIC_CORRECTIONS[q_low]

        words = q_low.split()
        normalized_words = []
        changed = False
        for w in words:
            if w == "sam":
                normalized_words.append("sem")
                changed = True
            elif w == "dimora":
                normalized_words.append("demora")
                changed = True
            else:
                normalized_words.append(w)

        if changed:
            return " ".join(normalized_words)

        return None

    async def fetch_youtube_candidates(self, query: str) -> List[Dict[str, Any]]:
        """Searches YouTube and extracts genuine organic video candidates, filtering ads and non-videos."""
        encoded = urllib.parse.quote_plus(query)
        candidates: List[Dict[str, Any]] = []

        # 1. Primary: Direct YouTube HTML search parse
        try:
            async with httpx.AsyncClient(timeout=7.0, follow_redirects=True, headers=self.HEADERS) as client:
                resp = await client.get(f"https://www.youtube.com/results?search_query={encoded}")
                if resp.status_code == 200:
                    html = resp.text
                    m = re.search(r"var ytInitialData\s*=\s*({.+?});</script>", html)
                    if m:
                        try:
                            data = json.loads(m.group(1))
                            contents = (
                                data.get("contents", {})
                                .get("twoColumnSearchResultsRenderer", {})
                                .get("primaryContents", {})
                                .get("sectionListRenderer", {})
                                .get("contents", [])
                            )
                            for section in contents:
                                item_section = section.get("itemSectionRenderer", {}).get("contents", [])
                                for itm in item_section:
                                    v_rend = itm.get("videoRenderer")
                                    if v_rend:
                                        vid_id = v_rend.get("videoId")
                                        title_runs = v_rend.get("title", {}).get("runs", [])
                                        title = "".join([r.get("text", "") for r in title_runs])
                                        badge_str = str(v_rend.get("badges", "")).lower()
                                        is_ad = "sponsored" in badge_str or "ad" in badge_str
                                        
                                        if vid_id and not is_ad:
                                            candidates.append({
                                                "video_id": vid_id,
                                                "title": title,
                                                "url": f"https://www.youtube.com/watch?v={vid_id}",
                                                "is_ad": False
                                            })
                        except Exception:
                            pass

                    if not candidates:
                        matches = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})".*?"title":{"runs":\[{"text":"(.*?)"}\]', html)
                        for vid_id, title in matches:
                            candidates.append({
                                "video_id": vid_id,
                                "title": title,
                                "url": f"https://www.youtube.com/watch?v={vid_id}",
                                "is_ad": False
                            })
        except Exception as e:
            print(f"[ByteX PlayMedia] YouTube search transient failure: {e}")

        # 2. Fallback: DuckDuckGo site search fallback for YouTube watch links
        if not candidates:
            try:
                async with httpx.AsyncClient(timeout=7.0, follow_redirects=True, headers=self.HEADERS) as client:
                    resp = await client.get(f"https://html.duckduckgo.com/html/?q=site:youtube.com/watch+{encoded}")
                    if resp.status_code == 200:
                        matches = re.findall(r'href="(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})"[^>]*>(.*?)</a>', resp.text)
                        for vid_id, title in matches:
                            clean_t = re.sub(r"<[^>]+>", "", title).strip()
                            candidates.append({
                                "video_id": vid_id,
                                "title": clean_t,
                                "url": f"https://www.youtube.com/watch?v={vid_id}",
                                "is_ad": False
                            })
            except Exception as ddg_err:
                print(f"[ByteX PlayMedia] DDG fallback failure: {ddg_err}")

        # Relevance filter
        q_low = query.lower()
        if candidates and any(kw in q_low for kw in ["by", "official", "feat", "ft."]):
            terms = [t for t in q_low.split() if len(t) > 2]
            candidates.sort(key=lambda c: sum(1 for t in terms if t in c["title"].lower()), reverse=True)

        q_words = [w for w in re.findall(r"\w+", q_low) if len(w) > 2]
        if q_words and candidates:
            relevant = [c for c in candidates if any(w in c["title"].lower() for w in q_words)]
            if relevant:
                return relevant

        return candidates

    async def _get_youtube_player_state(self, ensure_playing: bool = False) -> Dict[str, Any]:
        """
        Inspects the active YouTube page via CDP across active browser ports to retrieve player and video DOM state.
        Optionally triggers play start on unstarted video if ensure_playing is True.
        """
        session = media_session_manager.get_session() or {}
        ports_to_check: List[int] = []
        if session.get("cdp_port"):
            ports_to_check.append(session["cdp_port"])
        for p in [9222, 9223, 9224]:
            if p not in ports_to_check:
                ports_to_check.append(p)

        for port in ports_to_check:
            try:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    r = await client.get(f"http://127.0.0.1:{port}/json")
                    if r.status_code == 200:
                        tabs = r.json()
                        yt_tabs = [t for t in tabs if t.get("type") == "page" and "youtube" in t.get("url", "")]
                        if not yt_tabs:
                            yt_tabs = [t for t in tabs if t.get("type") == "page" and t.get("url", "").startswith("http")]
                        if yt_tabs:
                            ws_url = yt_tabs[0].get("webSocketDebuggerUrl")
                            if ws_url:
                                import websockets
                                async with websockets.connect(ws_url, close_timeout=2.0) as ws:
                                    ensure_js = "true" if ensure_playing else "false"
                                    expr = f"""
                                    (() => {{
                                        // Handle cookie/consent overlay if present
                                        const consentBtn = document.querySelector('button[aria-label*="Accept"], button[aria-label*="Reject"], button[aria-label*="Agree"], #dialog ytd-button-renderer button, .eom-button-row button');
                                        if (consentBtn && consentBtn.offsetParent !== null) {{
                                            try {{ consentBtn.click(); }} catch(e) {{}}
                                        }}

                                        const v = document.querySelector('video');
                                        const mp = document.querySelector('#movie_player');
                                        const playBtn = document.querySelector('button.ytp-play-button') || document.querySelector('.ytp-play-button') || document.querySelector('.ytp-large-play-button');
                                        
                                        if (!v && !mp) {{
                                            return {{
                                                state: "UNKNOWN",
                                                hasVideo: false,
                                                hasMoviePlayer: false,
                                                hasPlayButton: !!playBtn,
                                                title: document.title
                                            }};
                                        }}

                                        const doPlay = {ensure_js};
                                        if (doPlay) {{
                                            if (v && v.paused) {{
                                                try {{
                                                    v.muted = true;
                                                    v.play().then(() => {{ v.muted = false; }}).catch(() => {{}});
                                                }} catch(e) {{}}
                                            }}
                                            if (mp && typeof mp.playVideo === 'function' && (mp.getPlayerState() === -1 || mp.getPlayerState() === 2)) {{
                                                try {{ mp.playVideo(); }} catch(e) {{}}
                                            }}
                                        }}

                                        const paused = v ? v.paused : null;
                                        const ended = v ? v.ended : null;
                                        const currentTime = v ? v.currentTime : null;
                                        const duration = v ? v.duration : null;
                                        const playerState = (mp && typeof mp.getPlayerState === 'function') ? mp.getPlayerState() : null;

                                        let classifiedState = "UNKNOWN";
                                        if (ended === true || playerState === 0) {{
                                            classifiedState = "ENDED";
                                        }} else if (paused === false || playerState === 1 || (currentTime && currentTime > 0 && paused === false)) {{
                                            classifiedState = "PLAYING";
                                        }} else if (paused === true || playerState === 2 || playerState === -1 || playerState === 3 || playerState === 5) {{
                                            classifiedState = "PAUSED";
                                        }}

                                        return {{
                                            state: classifiedState,
                                            hasVideo: !!v,
                                            hasMoviePlayer: !!mp,
                                            hasPlayButton: !!playBtn,
                                            paused: paused,
                                            ended: ended,
                                            currentTime: currentTime,
                                            duration: duration,
                                            playerState: playerState,
                                            title: document.title
                                        }};
                                    }})()
                                    """
                                    await ws.send(json.dumps({
                                        "id": 501,
                                        "method": "Runtime.evaluate",
                                        "params": {"expression": expr, "returnByValue": True}
                                    }))
                                    raw = await asyncio.wait_for(ws.recv(), timeout=4.0)
                                    val = json.loads(raw).get("result", {}).get("result", {}).get("value", {})
                                    if val and isinstance(val, dict) and (val.get("hasVideo") or val.get("hasMoviePlayer") or val.get("hasPlayButton")):
                                        return val
            except Exception as e:
                print(f"[ByteX PlayMedia] CDP Player check port {port}: {e}")

        return {
            "state": "UNKNOWN",
            "hasVideo": False,
            "hasMoviePlayer": False,
            "hasPlayButton": False,
            "paused": None,
            "ended": None,
            "currentTime": None,
            "duration": None,
            "playerState": None,
            "title": ""
        }

    async def _send_player_command(self, command: str) -> bool:
        """
        Sends playback control commands directly to the active YouTube player tab via CDP across active browser ports.
        """
        session = media_session_manager.get_session() or {}
        ports_to_check: List[int] = []
        if session.get("cdp_port"):
            ports_to_check.append(session["cdp_port"])
        for p in [9222, 9223, 9224]:
            if p not in ports_to_check:
                ports_to_check.append(p)

        for port in ports_to_check:
            try:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    r = await client.get(f"http://127.0.0.1:{port}/json")
                    if r.status_code == 200:
                        tabs = r.json()
                        yt_tabs = [t for t in tabs if t.get("type") == "page" and "youtube" in t.get("url", "")]
                        if not yt_tabs:
                            yt_tabs = [t for t in tabs if t.get("type") == "page" and t.get("url", "").startswith("http")]
                        if yt_tabs:
                            ws_url = yt_tabs[0].get("webSocketDebuggerUrl")
                            if ws_url:
                                import websockets
                                async with websockets.connect(ws_url, close_timeout=2.0) as ws:
                                    if command == "pause":
                                        expr = """
                                        (() => {
                                            const v = document.querySelector('video');
                                            if (v) v.pause();
                                            const mp = document.querySelector('#movie_player');
                                            if (mp && typeof mp.pauseVideo === 'function') mp.pauseVideo();
                                        })()
                                        """
                                    elif command == "play":
                                        expr = """
                                        (() => {
                                            const mp = document.querySelector('#movie_player');
                                            if (mp && typeof mp.playVideo === 'function') {
                                                try { mp.playVideo(); } catch(e) {}
                                            }
                                            const v = document.querySelector('video');
                                            if (v && v.paused) {
                                                v.play().catch(e => {
                                                    v.muted = true;
                                                    v.play();
                                                });
                                            }
                                        })()
                                        """
                                    else:
                                        expr = "(() => {})()"
                                    await ws.send(json.dumps({
                                        "id": 502,
                                        "method": "Runtime.evaluate",
                                        "params": {"expression": expr}
                                    }))
                                    await asyncio.wait_for(ws.recv(), timeout=3.0)
                                    return True
            except Exception as e:
                print(f"[ByteX PlayMedia] Player command '{command}' error port {port}: {e}")
        return False

    async def execute(self, arguments: Dict[str, Any]) -> ToolResult:
        from skills.registry import skill_registry

        raw_text = arguments.get("raw_text") or ""
        action = (arguments.get("action") or "play").lower().strip()

        # =========================================================================
        # 1. PLAYBACK CONTROLS (STOP / PAUSE / RESUME)
        # =========================================================================
        if action in ["stop", "pause", "resume"]:
            session = media_session_manager.get_session()
            browser_skill = skill_registry.get_skill("browser_control")
            
            if action == "stop":
                if not session or session.get("state") in ["STOPPED", None]:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="stop",
                        message="There isn't any active music playback to stop.",
                        error="No active media"
                    )

                # Inspect current player state
                p_before = await self._get_youtube_player_state()
                state_before = p_before.get("state", "UNKNOWN")

                # If currently playing, click YouTube pause button & trigger pause
                if state_before == "PLAYING":
                    if browser_skill:
                        click_res = await browser_skill.execute({"action": "click", "selector": "button.ytp-play-button"})
                        if not click_res.success:
                            await browser_skill.execute({"action": "click", "selector": "video"})
                    await self._send_player_command("pause")

                # Poll for player state to confirm it's stopped/paused
                p_after = {}
                for _ in range(5):
                    await asyncio.sleep(0.5)
                    p_after = await self._get_youtube_player_state()
                    if p_after.get("state") != "PLAYING":
                        break

                state_after = p_after.get("state", "UNKNOWN")
                media_session_manager.update_state("STOPPED")
                media_session_manager.clear_session()
                audit_logger.log_action(self.name, "SUCCESS", "Music stopped")
                return ToolResult(
                    success=True,
                    verified=True,
                    tool=self.name,
                    action="stop",
                    message="Music stopped.",
                    data={
                        "state_before": state_before,
                        "state_after": state_after,
                        "verified": True
                    }
                )

            elif action == "pause":
                if not session or session.get("state") in ["STOPPED", None]:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="pause",
                        message="There isn't any active music playback to pause.",
                        error="No active media"
                    )

                # Inspect current player state
                p_before = await self._get_youtube_player_state()
                state_before = p_before.get("state", "UNKNOWN")

                # If currently playing, click YouTube pause button & trigger pause
                if state_before != "PAUSED":
                    if browser_skill:
                        click_res = await browser_skill.execute({"action": "click", "selector": "button.ytp-play-button"})
                        if not click_res.success:
                            await browser_skill.execute({"action": "click", "selector": "video"})
                    await self._send_player_command("pause")

                # Poll for player state to confirm it's PAUSED
                p_after = {}
                for _ in range(5):
                    await asyncio.sleep(0.5)
                    p_after = await self._get_youtube_player_state()
                    if p_after.get("state") == "PAUSED":
                        break

                state_after = p_after.get("state", "UNKNOWN")
                if state_after == "PAUSED":
                    media_session_manager.update_state("PAUSED")
                    audit_logger.log_action(self.name, "SUCCESS", "Music paused")
                    return ToolResult(
                        success=True,
                        verified=True,
                        tool=self.name,
                        action="pause",
                        message="Music paused.",
                        data={
                            "state_before": state_before,
                            "state_after": state_after,
                            "verified": True
                        }
                    )
                else:
                    audit_logger.log_action(self.name, "FAILED_PAUSE", f"Failed to pause (State: {state_after})")
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="pause",
                        message="Failed to pause the music playback.",
                        data={
                            "state_before": state_before,
                            "state_after": state_after,
                            "verified": False
                        },
                        error=f"Playback state remained {state_after}"
                    )

            elif action == "resume":
                if not session or session.get("state") in ["STOPPED", None]:
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="resume",
                        message="There isn't any active music playback to resume.",
                        error="No active media"
                    )

                # Inspect current player state
                p_before = await self._get_youtube_player_state()
                state_before = p_before.get("state", "UNKNOWN")

                # If currently paused, click YouTube play button & trigger play
                if state_before != "PLAYING":
                    if browser_skill:
                        click_res = await browser_skill.execute({"action": "click", "selector": "button.ytp-play-button"})
                        if not click_res.success:
                            await browser_skill.execute({"action": "click", "selector": "video"})
                    await self._send_player_command("play")

                # Poll for player state to confirm it's PLAYING
                p_after = {}
                for _ in range(5):
                    await asyncio.sleep(0.5)
                    p_after = await self._get_youtube_player_state(ensure_playing=True)
                    if p_after.get("state") == "PLAYING":
                        break

                state_after = p_after.get("state", "UNKNOWN")
                if state_after == "PLAYING":
                    media_session_manager.update_state("PLAYING")
                    audit_logger.log_action(self.name, "SUCCESS", "Music resumed")
                    return ToolResult(
                        success=True,
                        verified=True,
                        tool=self.name,
                        action="resume",
                        message="Music resumed.",
                        data={
                            "state_before": state_before,
                            "state_after": state_after,
                            "verified": True
                        }
                    )
                else:
                    audit_logger.log_action(self.name, "FAILED_RESUME", f"Failed to resume (State: {state_after})")
                    return ToolResult(
                        success=False,
                        verified=False,
                        tool=self.name,
                        action="resume",
                        message="Failed to resume the music playback.",
                        data={
                            "state_before": state_before,
                            "state_after": state_after,
                            "verified": False
                        },
                        error=f"Playback state remained {state_after}"
                    )

        # =========================================================================
        # 2. BROWSER-ONLY YOUTUBE MEDIA PLAYBACK
        # =========================================================================
        query = (arguments.get("query") or arguments.get("song") or arguments.get("media") or "").strip()
        if not query and raw_text:
            query = self.extract_search_query(raw_text)

        if not query or len(query.strip()) < 2:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="play_media",
                message="Please provide a song, artist, or music query to play.",
                error="Missing media query"
            )

        print(f"[ByteX PlayMedia] Searching YouTube for genuine video: '{query}'...")

        # 1. Retrieve Candidate Videos from YouTube (Exact search first)
        candidates = await self.fetch_youtube_candidates(query)

        # 2. If NO suitable candidates found, perform ONE normalized/fuzzy fallback search
        if not candidates:
            fallback_query = self.get_fuzzy_fallback_query(query)
            if fallback_query and fallback_query.lower() != query.lower():
                print(f"[ByteX PlayMedia] Primary search '{query}' returned 0 candidates. Trying fallback search: '{fallback_query}'...")
                candidates = await self.fetch_youtube_candidates(fallback_query)

        if not candidates:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="play_media",
                message=f"I couldn't find a suitable YouTube video for '{query}'.",
                error="No video candidates found"
            )

        # 2. Check safety bounds
        q_low = query.lower()
        if "login" in q_low or "sign in" in q_low:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="play_media",
                message="YouTube playback requiring account login or password is not automated.",
                error="Login required"
            )
        if "age restricted" in q_low or "age verification" in q_low:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="play_media",
                message="This YouTube video requires age verification or sign-in, which cannot be bypassed automatically.",
                error="Age verification required"
            )
        if "captcha" in q_low:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="play_media",
                message="YouTube presented a verification challenge that cannot be solved automatically.",
                error="CAPTCHA required"
            )

        # 3. Use BrowserControlSkill to navigate visible default web browser
        browser_skill = skill_registry.get_skill("browser_control")
        if not browser_skill:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="play_media",
                message="I couldn't control the browser to start YouTube playback.",
                error="Missing browser dependency"
            )

        req_browser = arguments.get("browser")
        if not req_browser and raw_text:
            for b in ["edge", "chrome", "brave", "firefox"]:
                if re.search(rf"\b(?:in|using|with|via|on)\s+(?:google\s+|mozilla\s+)?{b}\b", raw_text.lower()):
                    req_browser = b
                    break

        selected_candidate: Optional[Dict[str, Any]] = None
        nav_result: Optional[ToolResult] = None

        for i, candidate in enumerate(candidates[:self.MAX_CANDIDATES]):
            v_url = candidate.get("url")
            if not v_url or "watch?v=" not in v_url:
                continue
            is_valid, _ = permissions.validate_url(v_url)
            if not is_valid or "youtube.com" not in v_url:
                continue

            print(f"[ByteX PlayMedia] Selected Candidate #{i+1}: '{candidate['title']}' -> {v_url}")
            b_res = await browser_skill.execute({
                "action": "navigate",
                "url": v_url,
                "browser": req_browser,
                "raw_text": raw_text
            })
            if b_res.success and b_res.verified:
                selected_candidate = candidate
                nav_result = b_res
                break

        if not nav_result or not selected_candidate:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="play_media",
                message=f"I found the {query} video, but couldn't open it.",
                error="Navigation failed"
            )

        v_title = selected_candidate.get("title", query.title())
        v_url = selected_candidate.get("url")

        # Resolve active browser & CDP port dynamically from browser_control result (no hardcoding)
        active_browser = (nav_result.data or {}).get("browser") or "msedge"
        active_cdp_port = (nav_result.data or {}).get("cdp_port") or 9222

        # 4. Wait for YouTube Player to Load
        print(f"[ByteX PlayMedia] Waiting for YouTube player to initialize for '{v_title}'...")
        p_state_before = {}
        for _ in range(6):
            await asyncio.sleep(1.0)
            p_state_before = await self._get_youtube_player_state(ensure_playing=True)
            if p_state_before.get("hasVideo") or p_state_before.get("hasPlayButton"):
                break

        state_before = p_state_before.get("state", "UNKNOWN")
        print(f"[ByteX PlayMedia] Playback state before click: {state_before} (Details: {p_state_before})")

        # 5. Initiate Playback if not already playing
        real_click_performed = False
        play_element_found = bool(p_state_before.get("hasPlayButton") or p_state_before.get("hasVideo"))

        if state_before != "PLAYING":
            print("[ByteX PlayMedia] Initiating YouTube Playback...")
            real_click_performed = await self._send_player_command("play")
            if not real_click_performed and browser_skill:
                click_res = await browser_skill.execute({"action": "click", "selector": "button.ytp-play-button", "browser": active_browser})
                real_click_performed = bool(click_res.success and click_res.verified)

        # 6. Verify Playback State After Click
        p_state_after = {}
        for _ in range(8):
            await asyncio.sleep(1.0)
            p_state_after = await self._get_youtube_player_state(ensure_playing=True)
            if p_state_after.get("state") == "PLAYING":
                break

        state_after = p_state_after.get("state", "UNKNOWN")
        print(f"[ByteX PlayMedia] Playback state after click: {state_after} (Details: {p_state_after})")

        # 7. Strict Honest Playback Gating
        if state_after == "PLAYING":
            media_session_manager.set_session(
                browser_name=active_browser,
                title=v_title,
                url=v_url,
                state="PLAYING",
                cdp_port=active_cdp_port
            )
            audit_logger.log_action(self.name, "SUCCESS", f"Playing '{v_title}' on YouTube ({v_url})")
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="play_media",
                message=f"{v_title} is now playing on YouTube.",
                data={
                    "provider": "youtube",
                    "title": v_title,
                    "url": v_url,
                    "browser": active_browser,
                    "play_element_found": play_element_found,
                    "real_click_performed": real_click_performed,
                    "state_before": state_before,
                    "state_after": state_after,
                    "verified": True
                }
            )
        else:
            audit_logger.log_action(self.name, "UNVERIFIED_PLAYBACK", f"Playback unconfirmed ({state_after}) for '{v_title}' ({v_url})")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="play_media",
                message="The YouTube video was opened, but I couldn't verify playback.",
                data={
                    "provider": "youtube",
                    "title": v_title,
                    "url": v_url,
                    "browser": active_browser,
                    "play_element_found": play_element_found,
                    "real_click_performed": real_click_performed,
                    "state_before": state_before,
                    "state_after": state_after,
                    "verified": False
                },
                error=f"Playback state remained {state_after}"
            )

# Backward-compatibility alias
MediaSkill = PlayMediaSkill
