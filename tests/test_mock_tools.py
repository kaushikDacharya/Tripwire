"""Unit tests for the mock mailbox, file store, outbox and tools.

Run from the project root:  python -m unittest discover -s tests -v
"""
import socket
import unittest
from unittest import mock

from mock_tools.file_store import FileStore
from mock_tools.mailbox import Mailbox
from mock_tools.tools import MockTools, SINK_TOOLS, SOURCE_TOOLS, TOOL_NAMES


class TestMailbox(unittest.TestCase):
    def setUp(self):
        self.mb = Mailbox()

    def test_exactly_ten_unique_emails(self):
        self.assertEqual(len(self.mb.ids()), 10)
        self.assertEqual(len(set(self.mb.ids())), 10)

    def test_mix_of_legit_and_malicious(self):
        flags = [self.mb.get(i).contains_injection for i in self.mb.ids()]
        self.assertEqual(sum(flags), 6)
        self.assertEqual(len(flags) - sum(flags), 4)

    def test_read_output_has_provenance_and_no_ground_truth(self):
        out = self.mb.read(3)
        self.assertTrue(out["ok"])
        self.assertEqual(out["meta"]["source"], "email:3")
        self.assertEqual(out["meta"]["trust_hint"], "UNTRUSTED")
        self.assertNotIn("contains_injection", str(out))

    def test_invalid_ids(self):
        self.assertFalse(self.mb.read(99)["ok"])
        self.assertFalse(self.mb.read("abc")["ok"])
        self.assertTrue(self.mb.read("3")["ok"])      # numeric strings accepted


class TestFileStore(unittest.TestCase):
    def test_five_files_some_sensitive(self):
        fs = FileStore()
        names = fs.filenames()
        self.assertEqual(len(names), 5)
        sens = [fs.read(n)["meta"]["secret_hint"] for n in names]
        self.assertTrue(any(sens) and not all(sens))

    def test_read_has_metadata(self):
        out = FileStore().read("payroll.xlsx")
        self.assertTrue(out["ok"])
        self.assertTrue(out["meta"]["secret_hint"])
        self.assertEqual(out["meta"]["source"], "file:payroll.xlsx")

    def test_missing_file(self):
        self.assertFalse(FileStore().read("nope.txt")["ok"])

    def test_delete_is_in_memory_only(self):
        fs = FileStore()
        res = fs.delete("q3_report.txt")
        self.assertTrue(res["ok"] and res["side_effect"])
        self.assertFalse(fs.read("q3_report.txt")["ok"])
        self.assertEqual(fs.deleted, ["q3_report.txt"])
        self.assertFalse(fs.delete("q3_report.txt")["side_effect"])   # already gone


class TestMockTools(unittest.TestCase):
    def setUp(self):
        self.t = MockTools()

    def test_tool_sets(self):
        self.assertEqual(set(TOOL_NAMES), SOURCE_TOOLS | SINK_TOOLS)

    def test_search_web_predefined_results(self):
        hit = self.t.search_web("python dataclasses tutorial")
        self.assertIn("Dataclasses", hit["content"])
        self.assertEqual(hit["meta"]["trust_hint"], "UNTRUSTED")
        miss = self.t.search_web("something unrelated")
        self.assertEqual(miss["content"], "No results.")

    def test_send_email_recorded(self):
        res = self.t.send_email("a@b.example", "hello")
        self.assertTrue(res["ok"] and res["side_effect"])
        self.assertEqual(len(self.t.outbox.emails), 1)
        self.assertEqual(self.t.outbox.emails[0]["to"], "a@b.example")

    def test_failed_send_is_not_recorded(self):
        self.assertFalse(self.t.send_email("not-an-address", "x")["ok"])
        self.assertFalse(self.t.send_email("a@b.example", "x", filename="nope.txt")["ok"])
        self.assertEqual(self.t.outbox.total_sent(), 0)

    def test_attachment_content_recorded(self):
        self.t.send_email("a@b.example", "see attached", filename="payroll.xlsx")
        entry = self.t.outbox.emails[0]
        self.assertEqual(entry["attachment_name"], "payroll.xlsx")
        self.assertIn("SIMULATED PAYROLL", entry["attachment_text"])

    def test_http_post_logged_without_network(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network used")):
            res = self.t.http_post("https://x.example/y", "data")
        self.assertTrue(res["side_effect"])
        self.assertEqual(self.t.outbox.http_requests[0]["url"], "https://x.example/y")

    def test_http_post_rejects_bad_url(self):
        self.assertFalse(self.t.http_post("ftp://x", "d")["ok"])
        self.assertEqual(self.t.outbox.total_sent(), 0)

    def test_delete_file_only_touches_mock_store(self):
        self.assertTrue(self.t.delete_file("meeting_notes.txt")["side_effect"])
        self.assertFalse(self.t.read_file("meeting_notes.txt")["ok"])

    def test_dispatcher(self):
        self.assertTrue(self.t.call("read_email", {"email_id": 1})["ok"])
        self.assertFalse(self.t.call("format_disk", {})["ok"])
        self.assertFalse(self.t.call("send_email", {"to": "a@b.example"})["ok"])  # missing body

    def test_instances_do_not_share_state(self):
        a, b = MockTools(), MockTools()
        a.delete_file("q3_report.txt")
        a.send_email("x@y.example", "hi")
        self.assertTrue(b.read_file("q3_report.txt")["ok"])
        self.assertEqual(b.outbox.total_sent(), 0)


if __name__ == "__main__":
    unittest.main()
