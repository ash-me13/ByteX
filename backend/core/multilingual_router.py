import re
from typing import Tuple, Optional, Dict, Any, List

DEVANAGARI_REGEX = re.compile(r"[\u0900-\u097F]")

HINGLISH_KEYWORDS = {
    "kholo", "khol", "kholna", "chalao", "chala", "chalu", "band", "karo", "kar", "karna",
    "dhundo", "dhoondo", "dhoond", "khojo", "dikhao", "dikhana", "batao", "banao", "likho",
    "hatao", "mitao", "mita", "le", "lo", "lena", "pe", "par", "mein", "ka", "ki", "ke",
    "aur", "phir", "fir", "ye", "yeh", "wo", "woh", "mera", "meri", "mere", "kya", "hai",
    "aawaz", "awaaz", "badhao", "kam", "thoda", "tej", "dheere", "badi", "chhote", "chhota",
    "bas", "ab", "sath", "saath", "dekho"
}

# Devanagari word mappings for deterministic normalization
HINDI_SCRIPT_APP_MAP = {
    "क्रोम": "chrome",
    "गूगल क्रोम": "chrome",
    "डिस्कॉर्ड": "discord",
    "डिस्कर्ड": "discord",
    "नोटपैड": "notepad",
    "कैलकुलेटर": "calculator",
    "गूगल": "google",
    "यूट्यूब": "youtube",
    "डाउनलोड्स": "downloads",
    "डॉक्यूमेंट्स": "documents",
    "फाइल": "file",
    "फोल्डर": "folder",
}

def detect_language(text: str) -> str:
    """
    Detects whether text is 'hi' (Hindi in Devanagari script),
    'hinglish' (Mixed Hindi+English in Latin script), or 'en' (English).
    """
    if not text or not text.strip():
        return "en"
    
    clean = text.strip()
    
    # 1. Check for Devanagari Unicode block (\u0900-\u097F)
    if DEVANAGARI_REGEX.search(clean):
        return "hi"
    
    # 2. Check for Hinglish vocabulary tokens
    words = re.findall(r"[a-zA-Z]+", clean.lower())
    hinglish_match_count = sum(1 for w in words if w in HINGLISH_KEYWORDS)
    if hinglish_match_count >= 1:
        return "hinglish"
    
    return "en"

def normalize_hindi_script_to_english(text: str) -> str:
    """Normalizes pure Devanagari Hindi commands to standard English command structure."""
    clean = text.strip()
    
    # Common Devanagari command patterns
    # 1. Screenshot
    if re.search(r"स्क्रीनशॉट\s+(?:ले\s*लो|लो|लीजिए|लेना|ले\s*ली)", clean):
        return "take a screenshot"
    
    # 2. Search
    m_search = re.search(r"(?:गूगल|यूट्यूब|[a-zA-Z\u0900-\u097F0-9\s]+?)\s*(?:पर|पे)\s*(.+?)\s*(?:सर्च\s+करो|ढूंढो|खोजो)", clean)
    if m_search:
        target = "google" if "गूगल" in clean else ("youtube" if "यूट्यूब" in clean else "")
        query = m_search.group(1).strip()
        if target:
            return f"search {target} for {query}"
        return f"search for {query}"

    # 2.5. Memory & Preference Commands in Hindi (Feature #39)
    m_hi_mem = re.match(r"^याद\s+रखना\s+(?:कि\s+)?(.+)$", clean)
    if m_hi_mem:
        return f"remember that {m_hi_mem.group(1).strip()}"
    if re.search(r"भूल\s+जाओ", clean):
        m_hi_forget = re.sub(r"\s*(?:की\s+preference\s+|वाली\s+preference\s+|वाली\s+मेमोरी\s+)?(?:भूल\s+जाओ)$", "", clean).strip()
        return f"forget that {m_hi_forget}"

    # Abstract targets in Hindi
    if re.search(r"मेरा\s+ब्राउज़र\s+(?:खोलो|खोल\s+दो|चलाओ)", clean):
        return "open my browser"
    if re.search(r"मेरा\s+(?:एडिटर|कोड\s+एडिटर)\s+(?:खोलो|खोल\s+दो|चलाओ)", clean):
        return "open my editor"
    if re.search(r"मेरा\s+प्रोजेक्ट\s+(?:खोलो|खोल\s+दो|चलाओ)", clean):
        return "open my project"

    # 3. Open App / Target
    m_open = re.search(r"(.+?)\s+(?:खोलो|खोल\s+दो|खोलिए|चलाओ|चालू\s+करो)", clean)
    if m_open:
        target = m_open.group(1).strip()
        target_en = HINDI_SCRIPT_APP_MAP.get(target, target)
        if "डाउनलोड्स" in target:
            return "open downloads folder"
        elif "डॉक्यूमेंट्स" in target:
            return "open documents folder"
        return f"open {target_en}"
        
    # 4. Close App / Target
    m_close = re.search(r"(.+?)\s+(?:बंद\s+करो|बंद\s+कर\s+दो|बंद\s+कीजिए)", clean)
    if m_close:
        target = m_close.group(1).strip()
        target_en = HINDI_SCRIPT_APP_MAP.get(target, target)
        return f"close {target_en}"
    elif re.search(r"बंद\s+करो|बंद\s+कर\s+दो|रुक\s+जाओ", clean):
        return "stop"
        
    # 5. Volume
    if re.search(r"(?:वॉल्यूम|आवाज़|आवाज)\s+(?:बढ़ाओ|तेज\s+करो)", clean):
        return "increase volume"
    if re.search(r"(?:वॉल्यूम|आवाज़|आवाज)\s+(?:कम\s+करो|धीमी\s+करो)", clean):
        return "decrease volume"

    # 6. Delete File / Folder
    if re.search(r"(?:फाइल|फोल्डर|ये\s+फाइल)\s+(?:डिलीट\s+करो|हटाओ|हटा\s+दो|मिटा\s+दो)", clean):
        return "delete file"

    return clean

def normalize_hinglish_to_english(text: str) -> str:
    """Normalizes Latin-script Hinglish commands into standard English intent format."""
    clean = text.strip()
    low = clean.lower()

    # Pre-clean wake words and fillers
    low = re.sub(r"^(?:hey\s+bytex|hi\s+bytex|hello\s+bytex|yo\s+bytex|a\s+bytex|bytex)[,:\s]+", "", low, flags=re.IGNORECASE).strip()

    # Memory Commands in Hinglish (Feature #39)
    m_hng_mem = re.match(r"^(?:yaad\s+rakhna\s+(?:ki\s+)?|save\s+karo\s+(?:ki\s+)?)(.+)$", low)
    if m_hng_mem:
        return f"remember that {m_hng_mem.group(1).strip()}"
    if "bhool jao" in low or "bhul jao" in low:
        target = re.sub(r"^(?:forget\s+|delete\s+)?", "", low)
        target = re.sub(r"\s*(?:wali\s+preference|ki\s+preference|wali\s+memory|ko)?\s*(?:bhool\s+jao|bhul\s+jao)$", "", target).strip()
        return f"forget that {target}"

    # Abstract targets in Hinglish
    if re.search(r"\bmera\s+browser\s+(?:kholo|chalao|open\s+karo)\b", low):
        return "open my browser"
    if re.search(r"\bmera\s+(?:editor|code\s+editor)\s+(?:kholo|chalao|open\s+karo)\b", low):
        return "open my editor"
    if re.search(r"\bmera\s+project\s+(?:kholo|chalao|open\s+karo)\b", low):
        return "open my project"

    # 0. Ambiguity handling
    if low in ["ye kholo", "yeh kholo", "ise kholo", "isko kholo"]:
        return "AMBIGUOUS_OPEN: What should I open?"
    if low in ["ye chalao", "yeh chalao", "ise chalao", "isko chalao"]:
        return "AMBIGUOUS_OPEN: What should I launch?"

    # 0.5. Stop Commands
    if low in ["bas ab band karo", "ab band karo", "stop karo", "band kar do ab", "ruk jao", "chup ho jao"]:
        return "stop"

    # 1. Multi-Step Splitter with 'aur' / 'and' / 'phir' / 'fir'
    # E.g. "Chrome kholo aur Google pe Python search karo" -> "open chrome and search google for python"
    if " aur " in low or " phir " in low or " fir " in low:
        parts = re.split(r"\s+(?:aur|phir|fir)\s+", low)
        norm_parts = [normalize_hinglish_to_english(p) for p in parts]
        return " and ".join(norm_parts)

    # 2. Screenshot
    if re.search(r"\b(?:screenshot\s+(?:le\s*lo|lo|lena|le)|screen\s*shot\s+(?:le\s*lo|lo))\b", low):
        return "take a screenshot"

    # 3. Volume & System Controls
    if re.search(r"\b(?:volume|aawaz|awaaz)\s+(?:thoda\s+)?(?:badhao|badha\s+do|tej\s+karo|up\s+karo)\b", low):
        return "increase volume"
    if re.search(r"\b(?:volume|aawaz|awaaz)\s+(?:thoda\s+)?(?:kam\s+karo|dheere\s+karo|down\s+karo)\b", low):
        return "decrease volume"
    if re.search(r"\bwifi\s+(?:on\s+karo|chalu\s+karo)\b", low):
        return "turn on wifi"
    if re.search(r"\bwifi\s+(?:off\s+karo|band\s+karo)\b", low):
        return "turn off wifi"
    if re.search(r"\bbluetooth\s+(?:on\s+karo|chalu\s+karo)\b", low):
        return "turn on bluetooth"
    if re.search(r"\bbluetooth\s+(?:off\s+karo|band\s+karo)\b", low):
        return "turn off bluetooth"
    if re.search(r"\b(?:computer|system)\s+ki\s+(?:information|info)\s+batao\b", low) or "system info batao" in low:
        return "get system info"
    if "cpu usage batao" in low or "cpu usage check karo" in low:
        return "get cpu usage"

    # 4. Screen Vision & OCR
    if re.search(r"\b(?:screen\s+dekho|mere\s+screen\s+pe\s+kya\s+hai|screen\s+pe\s+kya\s+dikh\s+raha\s+hai|screen\s+pe\s+kya\s+hai|screen\s+read\s+karo)\b", low):
        return "what is on my screen"
    
    m_screen_click = re.match(r"^(.+?)\s+pe\s+click\s+karo$", low)
    if m_screen_click:
        elem = m_screen_click.group(1).strip()
        return f"click on {elem}"
    
    m_screen_find = re.match(r"^(.+?)\s+(?:button|box|input|icon)\s+(?:dhundo|dhoondo|khojo)$", low)
    if m_screen_find:
        elem = m_screen_find.group(1).strip()
        return f"find {elem} on screen"

    # 5. Web Search
    # E.g. "Google pe search karo Python" or "Google pe Python search karo"
    m_web_search1 = re.match(r"^(?:google|youtube)\s+(?:pe|par)\s+search\s+karo\s+(.+)$", low)
    if m_web_search1:
        eng = "google" if "google" in low else "youtube"
        return f"search {eng} for {m_web_search1.group(1).strip()}"

    m_web_search2 = re.match(r"^(?:google|youtube)\s+(?:pe|par)\s+(.+?)\s+search\s+karo$", low)
    if m_web_search2:
        eng = "google" if "google" in low else "youtube"
        return f"search {eng} for {m_web_search2.group(1).strip()}"

    # E.g. "Python tutorial search karo"
    m_search_gen = re.match(r"^(.+?)\s+(?:search\s+karo|search\s+kar\s+do|search\s+karna)$", low)
    if m_search_gen:
        q = m_search_gen.group(1).strip()
        return f"search for {q}"

    # 6. File & Folder Operations
    if "downloads folder kholo" in low or "downloads kholo" in low or "downloads folder open karo" in low:
        return "open downloads folder"
    if "documents folder kholo" in low or "documents kholo" in low or "documents open karo" in low:
        return "open documents folder"
    
    m_file_find = re.match(r"^(.+?)\s+(?:dhundo|dhoondo|khojo|dhoond\s+do|dhund\s+do)$", low)
    if m_file_find:
        q = m_file_find.group(1).strip()
        if "badi files" in q or "large files" in q:
            return "find large files"
        return f"find {q}"

    m_file_rename = re.match(r"^(.+?)\s+rename\s+karo(?:\s+(?:to|ko)\s+(.+))?$", low)
    if m_file_rename:
        src = m_file_rename.group(1).strip()
        dest = m_file_rename.group(2).strip() if m_file_rename.group(2) else ""
        if dest:
            return f"rename {src} to {dest}"
        return f"rename {src}"

    m_folder_create = re.match(r"^(?:folder\s+banao|new\s+folder\s+banao|folder\s+create\s+karo)(?:\s+(?:named|called)?\s*(.+))?$", low)
    if m_folder_create:
        fname = m_folder_create.group(1).strip() if m_folder_create.group(1) else "New Folder"
        return f"create folder {fname}"

    # DESTRUCTIVE FILE DELETION (Confirmation required!)
    m_file_delete = re.match(r"^(?:ye\s+file\s+|file\s+|(.+?)\s+)?(?:delete\s+kar\s+do|delete\s+karo|hatao|hata\s+do|mita\s+do)$", low)
    if m_file_delete:
        tgt = m_file_delete.group(1).strip() if m_file_delete.group(1) else "file"
        return f"delete {tgt}"

    # 7. Coding Commands
    # E.g. "C++ mein prime number ka program banao" -> "create a C++ program for prime number"
    m_code_create = re.match(r"^([a-zA-Z0-9_\+\#]+)\s+mein\s+(.+?)\s+(?:ka\s+program|ka\s+code)\s+(?:banao|likho|bana\s+do)$", low)
    if m_code_create:
        lang = m_code_create.group(1).strip()
        topic = m_code_create.group(2).strip()
        return f"create a {lang} program for {topic}"

    m_code_run = re.match(r"^(?:code|program|main\.[a-z]+)\s+(?:run\s+karo|execute\s+karo|chalao)$", low)
    if m_code_run:
        return "run code"

    if "error check karo" in low or "errors check karo" in low:
        return "check for errors"
    if "ye error fix karo" in low or "error fix karo" in low:
        return "fix this error"
    if "code explain karo" in low or "ye code explain karo" in low:
        return "explain this code"

    # 8. Open / Launch Suffix
    m_open = re.match(r"^(.+?)\s+(?:kholo|khol\s+do|kholna|khol|khol\s+dena|chalao|chala|open\s+karo)$", low)
    if m_open:
        app_target = m_open.group(1).strip()
        if app_target not in ["door", "window"]:
            return f"open {app_target}"

    # 9. Close Suffix
    m_close = re.match(r"^(.+?)\s+(?:band\s+karo|band\s+kar|band\s+kar\s+do|band|close\s+karo)$", low)
    if m_close:
        app_target = m_close.group(1).strip()
        return f"close {app_target}"

    # 10. Show / Tell Suffix
    m_show = re.match(r"^(.+?)\s+(?:dikhao|dikhana|batao|bata\s+dena|bata\s+do)$", low)
    if m_show:
        target = m_show.group(1).strip()
        return f"show {target}"

    return clean

def format_personality_response(
    action: str,
    target: str = "",
    success: bool = True,
    personality: str = "friendly",
    length: str = "balanced",
    lang: str = "en",
    details: str = "",
    error: str = ""
) -> str:
    """
    Generates tailored, concise personality responses across English, Hindi, and Hinglish.
    Strictly receives physical execution status to guarantee zero fake success.
    """
    p = personality.lower() if personality in ["friendly", "professional", "casual", "concise"] else "friendly"
    l = length.lower() if length in ["short", "balanced", "detailed"] else "balanced"
    
    # 1. Failure Handling (Zero fake success)
    if not success:
        if lang == "hi":
            return f"{target} नहीं खुल सका।" if action == "open_application" else f"क्रिया असफल रही: {error or 'त्रुटि'}"
        elif lang == "hinglish":
            return f"Main {target} open nahi kar paya." if action == "open_application" else f"Action fail ho gaya: {error or 'Error'}"
        else:
            if p == "professional":
                return f"{target} could not be opened." if action == "open_application" else f"Operation failed: {error or 'Unknown error'}"
            elif p == "casual":
                return f"Couldn't get {target} to open." if action == "open_application" else f"Failed: {error or 'Error'}"
            elif p == "concise":
                return f"{target} failed to open." if action == "open_application" else f"Failed: {error or 'Error'}"
            else: # friendly
                return f"I couldn't open {target}." if action == "open_application" else f"I couldn't complete that: {error or 'Error'}"

    # 2. Confirmation Handling
    if action == "confirmation_required":
        if lang == "hi":
            return f"{target} को हटाने के लिए पुष्टि आवश्यक है। क्या आप जारी रखना चाहते हैं?"
        elif lang == "hinglish":
            return f"Yeh {target} delete karega. Kya main continue karoon?"
        else:
            if p == "professional":
                return f"Confirmation required to delete {target}."
            elif p == "casual":
                return f"That'll delete {target}. Want me to go ahead?"
            elif p == "concise":
                return f"Delete {target}?"
            else: # friendly
                return f"This will delete {target}. Should I continue?"

    # 3. Application Open Success
    if action == "open_application":
        if lang == "hi":
            if p == "professional": return f"{target} सफलतापूर्वक खोल दिया गया है।"
            if p == "casual": return f"{target} खुल गया।"
            if p == "concise": return f"{target} खुला।"
            return f"हो गया! {target} खोल दिया है।"
        elif lang == "hinglish":
            if p == "professional": return f"{target} successfully open kar diya gaya hai."
            if p == "casual": return f"Yep, {target} open ho gaya."
            if p == "concise": return f"{target} open."
            return f"Done! {target} open kar diya hai."
        else:
            if p == "professional":
                if l == "short": return f"{target} opened."
                if l == "detailed": return f"{target} has been launched on your desktop and verified."
                return f"{target} has been opened successfully."
            elif p == "casual":
                if l == "short": return f"Yep, open."
                if l == "detailed": return f"Got it! {target} is up and running."
                return f"Yep, {target}'s open."
            elif p == "concise":
                if l == "short": return f"{target} open."
                return f"{target} opened."
            else: # friendly
                if l == "short": return "Done."
                if l == "detailed": return f"Done! I opened {target} successfully and it's ready to use."
                return f"Done! {target} is open."

    # 4. Application Close Success
    if action == "close_application":
        if lang == "hi":
            return f"{target} बंद कर दिया गया है।"
        elif lang == "hinglish":
            return f"Done! {target} band kar diya hai."
        else:
            if p == "professional": return f"{target} has been closed."
            if p == "casual": return f"Closed {target} for you."
            if p == "concise": return f"{target} closed."
            return f"Done! {target} is closed."

    # 5. Screenshot Success
    if action == "take_screenshot":
        if lang == "hi":
            return "स्क्रीनशॉट ले लिया गया है।"
        elif lang == "hinglish":
            return "Done! Screenshot le liya hai."
        else:
            if p == "professional": return "Screenshot captured successfully."
            if p == "casual": return "Got the screenshot."
            if p == "concise": return "Screenshot taken."
            return "Done! I captured your screen."

    return details or f"{target} completed successfully."

def sanitize_speech_text(text: str, max_chars: int = 500) -> str:
    """
    Sanitizes raw AI / tool output for natural, concise speech.
    Strips raw code blocks, markdown tables, URLs, and enforces safe length.
    """
    if not text or not text.strip():
        return ""

    raw = text.strip()

    # 1. Replace multi-line code blocks with brief spoken summaries
    code_block_match = re.search(r"```([a-zA-Z0-9_\+\#]*)\s*([\s\S]*?)```", raw)
    if code_block_match:
        lang_name = code_block_match.group(1).upper() or "source"
        raw = re.sub(r"```[\s\S]*?```", f"I've generated the {lang_name} code and displayed it on screen.", raw)

    # 2. Strip URLs and raw symbols
    clean = re.sub(r"https?://\S+", "link", raw)
    clean = re.sub(r"[*_~`#\[\]()]", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    # 3. Limit spoken characters to max_chars with clean sentence truncation
    if len(clean) > max_chars:
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        truncated = ""
        for s in sentences:
            if len(truncated) + len(s) + 1 <= max_chars:
                truncated += (" " if truncated else "") + s
            else:
                break
        if not truncated:
            truncated = clean[:max_chars].rstrip() + "..."
        return truncated

    return clean

class MultilingualRouter:
    """Centralized multilingual parsing & localization engine for Hindi & Hinglish."""

    @classmethod
    def normalize_command(cls, text: str) -> str:
        """Convenience alias returning only normalized command."""
        return cls.process_input(text)[0]

    @classmethod
    def process_input(cls, text: str) -> Tuple[str, str]:
        """
        Processes raw input string in English, Hindi, or Hinglish.
        Returns (normalized_command_for_execution, detected_language).
        """
        if not text:
            return "", "en"
        
        lang = detect_language(text)
        
        if lang == "hi":
            norm = normalize_hindi_script_to_english(text)
            return norm, "hi"
        elif lang == "hinglish":
            norm = normalize_hinglish_to_english(text)
            return norm, "hinglish"
        else:
            return text, "en"

    @classmethod
    def localize_response(
        cls,
        response_text: str,
        lang: str = "en",
        personality: str = "friendly",
        length: str = "balanced"
    ) -> str:
        """
        Localizes and shapes assistant responses according to personality & language.
        """
        if not response_text:
            return response_text

        low_resp = response_text.strip().lower()

        # Handle specific app open / close responses
        if "opened successfully" in low_resp or "is open" in low_resp:
            app_name = response_text.split()[0]
            return format_personality_response("open_application", target=app_name, success=True, personality=personality, length=length, lang=lang)

        if "closed successfully" in low_resp or "is closed" in low_resp:
            app_name = response_text.split()[0]
            return format_personality_response("close_application", target=app_name, success=True, personality=personality, length=length, lang=lang)

        if "screenshot taken" in low_resp or "screenshot captured" in low_resp:
            return format_personality_response("take_screenshot", success=True, personality=personality, length=length, lang=lang)

        if low_resp == "stopped.":
            if lang == "hi": return "रुक गया।"
            if lang == "hinglish": return "Stop kar diya hai."
            return "Stopped."

        return response_text
