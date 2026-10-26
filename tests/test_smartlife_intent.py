"""
SMART LIFE routing gate (smartlife.intent): reminder phrasings reach the AI model + smart_life tool; existing features
(files, automations, routines, history, plain memory notes) keep their old handlers. Pure stdlib.

    PYTHONPATH=backend python3 -m unittest tests.test_smartlife_intent -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from smartlife.intent import is_smart_life_request as gate  # noqa: E402

ROUTER = Path(__file__).resolve().parent.parent / "backend" / "core" / "command_router.py"


class IntentGateTests(unittest.TestCase):
    def test_managing_a_reminder_is_left_to_the_model(self):
        for m in ["Delete the birthday reminder", "Remove my exam reminder", "Delete my DBMS assignment reminder.", "Cancel the birthday reminder.",
                  "Move my assignment reminder to 7 PM.", "Change the exam reminder to 8 AM", "Reschedule my assignment reminder to Friday",
                  "Rename my assignment reminder to submit lab file", "Move my exam reminder to tomorrow", "Mark the Wi-Fi bill reminder as complete",
                  "Snooze the reminder", "Clear my overdue reminders", "Postpone the deadline reminder"]:
            self.assertTrue(gate(m), m)

    def test_dated_life_events_after_remember_are_not_plain_notes(self):
        for m in ["Remember Rahul's birthday is on 27 October every year.", "Remember that my passport expires on 15 January 2027",
                  "Remember my mother's birthday is 4 March", "Remember to submit the fee form on Monday",
                  "Remember I have a DBMS exam on 10 November", "please remember the rent is due on the 5th", "Remember my sister's anniversary is next month"]:
            self.assertTrue(gate(m), m)

    def test_existing_features_are_untouched(self):
        for m in ["Remember that I like dark mode", "remember my name is Suryansha", "remember to drink water", "Remember my wifi password is hunter2",
                  "delete report.txt", "delete reminder.txt", "move reminder.pdf to Desktop", "delete the file notes.txt", "rename old.txt to new.txt",
                  "clear task history", "show my task history", "delete my morning automation", "cancel my morning routine reminder",
                  "disable all automations", "run my morning routine", "every day at 9 AM open chrome", "open chrome", "what is the weather",
                  "forget everything you know about me", "hello", "", "   "]:
            self.assertFalse(gate(m), m)

    def test_plain_remind_me_needs_no_gate_because_nothing_else_claims_it(self):
        # these already fall through to the model; the gate only has to avoid breaking them
        for m in ["Remind me to call mom at 6 PM", "What reminders do I have today?", "Set a reminder for 5 pm"]:
            self.assertFalse(gate(m), m)

    def test_very_long_input_is_ignored(self):
        self.assertFalse(gate("delete reminder " * 100))

    def test_router_calls_the_gate_after_the_confirmation_handling_and_before_the_file_skills(self):
        src = ROUTER.read_text(encoding="utf-8")
        gate_at = src.index("is_smart_life_request(message)")
        self.assertGreater(gate_at, src.index("confirmation_manager.evaluate_response(message)"))   # 'yes'/'no' are handled first
        self.assertLess(gate_at, src.index("# 1.35. Direct Code Workspace Intent Priority"))
        self.assertLess(gate_at, src.index("handle_natural_automation_command(message)"))
        self.assertLess(gate_at, src.index("await cls.classify_request(message)"))
        block = src[gate_at - 200: gate_at + 400]
        self.assertIn("return False,", block)                          # passes the message on; executes nothing
        self.assertNotIn("execute_tool", block)


if __name__ == "__main__":
    unittest.main()
