"""
Router bypass for SMART LIFE phrasings. Pure, deterministic, side-effect free.

This predicate does NOT execute or create anything. It only tells the command router to leave a message alone so the
AI model can handle it with the validated, user-approved ``smart_life`` tool, instead of the older generic handlers
(file move/delete/rename skills, automation editing, "remember that ..." memory notes) grabbing it first.
It is deliberately narrow so existing behaviour ("remember that I like dark mode", "delete report.txt",
"clear task history", automations and routines) is unchanged.
"""
import re

_MANAGE_VERBS = re.compile(r"\b(?:delete|remove|cancel|rename|move|change|edit|update|reschedule|postpone|snooze|mark|clear|erase)\b")
_REMINDER_NOUN = re.compile(r"\b(?:reminders?|deadlines?)\b")
# things that mean the user is talking about a file or one of the older features, not a SMART LIFE item
_OTHER_FEATURE = re.compile(r"\b(?:automations?|routines?|workflows?|history|memor(?:y|ies))\b|\w\.[a-z][a-z0-9]{1,4}\b")

_REMEMBER_START = re.compile(r"^\s*(?:please\s+)?remember\b")
_LIFE_EVENT = re.compile(
    r"\b(?:birthdays?|anniversar(?:y|ies)|exams?|deadlines?|assignments?|due|expir(?:e|es|ed|y|ation)|renew\w*|bills?|"
    r"appointments?|submissions?|submit|interviews?|meeting|payments?|pay)\b")
_DATE_HINT = re.compile(
    r"\b(?:today|tomorrow|tonight|next\s+\w+|this\s+\w+|every\s+(?:year|month|week|day|\w+day)|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|\d{1,2}(?:st|nd|rd|th)\b|\d{1,2}[/-]\d{1,2})\b")


def is_smart_life_request(message: str) -> bool:
    text = " ".join((message or "").lower().split())
    if not text or len(text) > 600:
        return False
    # "delete/cancel/move/change ... reminder" -> a SMART LIFE item, unless it is about a file or an older feature
    if _MANAGE_VERBS.search(text) and _REMINDER_NOUN.search(text) and not _OTHER_FEATURE.search(text):
        return True
    # "remember <birthday/exam/deadline/expiry ...> <date>" -> a dated life event, not a plain memory note
    if _REMEMBER_START.match(text) and _LIFE_EVENT.search(text) and _DATE_HINT.search(text):
        return True
    return False
