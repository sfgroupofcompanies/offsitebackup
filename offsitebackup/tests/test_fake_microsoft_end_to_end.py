"""The whole client against the fake Microsoft over real HTTP: no mocks in this file."""

import os
import tempfile
import threading
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from offsitebackup.backup.prune import prune_folder
from offsitebackup.integrations.microsoft import graph as microsoft
from offsitebackup.integrations.microsoft.fake import serve
from offsitebackup.integrations.microsoft.graph import GraphClient
from offsitebackup.integrations.microsoft.token import MicrosoftError, get_token

SITE = "https://fake.sharepoint.com/sites/ERPBackups"


class TestAgainstTheFake(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.library = tempfile.mkdtemp(prefix="fake-library-")
		cls.server = serve(cls.library, port=0)
		cls.port = cls.server.server_address[1]
		cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
		cls.thread.start()
		cls.base = f"http://127.0.0.1:{cls.port}"
		frappe.conf["offsitebackup_login_url"] = cls.base
		frappe.conf["offsitebackup_graph_url"] = cls.base + "/v1.0"

	@classmethod
	def tearDownClass(cls):
		cls.server.shutdown()
		frappe.conf.pop("offsitebackup_login_url", None)
		frappe.conf.pop("offsitebackup_graph_url", None)
		super().tearDownClass()

	def client(self, folder="gva-sf"):
		return GraphClient(get_token("tenant", "client", "secret"), SITE, folder)

	def test_token_comes_from_the_fake(self):
		self.assertTrue(get_token("t", "c", "s").startswith("fake-token-"))

	def test_wrong_token_is_refused(self):
		client = GraphClient("not-ours", SITE, "x")
		with self.assertRaises(MicrosoftError) as caught:
			client.site_id
		self.assertIn("401", str(caught.exception))

	def test_upload_in_pieces_lands_byte_for_byte(self):
		path = os.path.join(tempfile.mkdtemp(), "20261105_023000-site-database.sql.gz")
		payload = os.urandom(2_500_000)
		with open(path, "wb") as handle:
			handle.write(payload)
		with patch.object(microsoft, "CHUNK_SIZE", 1_000_000):
			item = self.client().upload_file(path)
		self.assertEqual(item["name"], os.path.basename(path))
		self.assertEqual(item["size"], len(payload))
		with open(os.path.join(self.library, "gva-sf", os.path.basename(path)), "rb") as handle:
			self.assertEqual(handle.read(), payload)

	def test_list_and_prune_against_the_fake(self):
		client = self.client("prune-test")
		client.ensure_folder()
		folder = os.path.join(self.library, "prune-test")
		for n in range(1, 36):
			with open(
				os.path.join(
					folder,
					f"202610{n:02d}_023000-site-database.sql.gz"
					if n <= 31
					else f"202611{n - 31:02d}_023000-site-database.sql.gz",
				),
				"wb",
			) as handle:
				handle.write(b"x")
		self.assertEqual(len(client.list_folder()), 35)
		result = prune_folder(client, keep_daily=30, keep_monthly=0)
		self.assertEqual(len(result["deleted"]), 5)
		self.assertEqual(len(os.listdir(folder)), 30)
		self.assertTrue(all(n.startswith("202611") or int(n[6:8]) >= 6 for n in os.listdir(folder)))

	def test_delete_cannot_leave_the_library(self):
		outside = os.path.join(os.path.dirname(self.library), "outside-" + os.path.basename(self.library))
		with open(outside, "wb") as handle:
			handle.write(b"keep me")
		self.addCleanup(lambda: os.path.exists(outside) and os.remove(outside))
		client = self.client("gva-sf")
		bad_id = "..|" + os.path.basename(outside)
		with self.assertRaises(MicrosoftError) as caught:
			client.delete_item(bad_id)
		self.assertIn("404", str(caught.exception))
		self.assertTrue(os.path.exists(outside), "a traversal id must never delete outside the library")
