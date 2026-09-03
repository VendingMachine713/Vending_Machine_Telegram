import json
import tempfile
import unittest
from pathlib import Path

from shared.vm_core.logging_setup import log_event, redact


class SharedLoggingTests(unittest.TestCase):
    def test_nested_secret_keys_and_token_shaped_text_are_redacted(self):
        raw_token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
        value = {
            "telegram_bot_token": raw_token,
            "nested": {"api_hash_value": "sensitive", "message": f"url/{raw_token}/getMe"},
        }
        redacted = redact(value)
        serialized = json.dumps(redacted)
        self.assertNotIn(raw_token, serialized)
        self.assertNotIn("sensitive", serialized)
        self.assertEqual(redacted["telegram_bot_token"], "[REDACTED]")

    def test_service_name_is_sanitized_for_log_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = log_event("started", service="Demo Bot/Unsafe", data={"ok": True}, root=root)
            self.assertEqual(path.name, "Demo_Bot_Unsafe.jsonl")
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["event"], "started")
            self.assertTrue(record["data"]["ok"])


if __name__ == "__main__":
    unittest.main()
