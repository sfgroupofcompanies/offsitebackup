import os
import tempfile
from unittest.mock import MagicMock, patch

import requests
from frappe.tests.utils import FrappeTestCase

from offsitebackup.integrations.microsoft import graph as microsoft
from offsitebackup.integrations.microsoft.graph import GRAPH_URL, GraphClient, MicrosoftError

SITE = "https://example.sharepoint.com/sites/ERPBackups"
SITE_ID = "example.sharepoint.com,1111,2222"
UPLOAD_URL = "https://upload.example/session-1"


def response(status, body=None):
	r = MagicMock()
	r.status_code = status
	r.text = "" if body is None else str(body)
	if body is None:
		r.json.side_effect = ValueError("no json")
	else:
		r.json.return_value = body
	return r


class FakeSession:
	"""Answers Graph calls from a script; records every call it gets."""

	def __init__(self, folder_exists=True, chunk_answers=None):
		self.calls = []
		self.folder_exists = folder_exists
		self.chunk_answers = list(chunk_answers or [])

	def request(self, method, url, **kwargs):
		self.calls.append((method, url, kwargs))
		if method == "GET" and url == f"{GRAPH_URL}/sites/example.sharepoint.com:/sites/ERPBackups":
			return response(200, {"id": SITE_ID})
		if method == "GET" and url.endswith("/drive/root:/gva-sf"):
			return (
				response(200, {"id": "folder-1"})
				if self.folder_exists
				else response(404, {"error": {"code": "itemNotFound"}})
			)
		if method == "POST" and url.endswith("/drive/root/children"):
			self.folder_exists = True
			return response(201, {"id": "folder-1", "name": kwargs["json"]["name"]})
		if method == "POST" and url.endswith(":/createUploadSession"):
			return response(200, {"uploadUrl": UPLOAD_URL})
		raise AssertionError(f"unexpected call {method} {url}")

	def put(self, url, data=None, headers=None, timeout=None):
		self.calls.append(("PUT", url, {"data": data, "headers": headers, "timeout": timeout}))
		answer = self.chunk_answers.pop(0)
		if isinstance(answer, Exception):
			raise answer
		return answer


def make_file(size):
	handle = tempfile.NamedTemporaryFile(
		prefix="20261105_023000-site-database", suffix=".sql.gz", delete=False
	)
	handle.write(os.urandom(size))
	handle.close()
	return handle.name


class TestUploadFile(FrappeTestCase):
	def setUp(self):
		self.chunk = patch.object(microsoft, "CHUNK_SIZE", 1000)
		self.chunk.start()
		self.addCleanup(self.chunk.stop)

	def client(self, session):
		with patch("offsitebackup.integrations.microsoft.graph.get_request_session", return_value=session):
			return GraphClient("tok-1", SITE, "gva-sf")

	def test_file_goes_up_in_pieces_with_the_right_ranges(self):
		path = make_file(2500)
		self.addCleanup(os.remove, path)
		session = FakeSession(
			chunk_answers=[
				response(202, {"nextExpectedRanges": ["1000-"]}),
				response(202, {}),
				response(201, {"id": "file-1", "name": os.path.basename(path), "size": 2500}),
			]
		)
		item = self.client(session).upload_file(path)

		self.assertEqual(item["id"], "file-1")
		puts = [c for c in session.calls if c[0] == "PUT"]
		self.assertEqual(len(puts), 3)
		ranges = [c[2]["headers"]["Content-Range"] for c in puts]
		self.assertEqual(ranges, ["bytes 0-999/2500", "bytes 1000-1999/2500", "bytes 2000-2499/2500"])
		self.assertEqual(sum(len(c[2]["data"]) for c in puts), 2500)
		self.assertTrue(all(c[1] == UPLOAD_URL for c in puts))

	def test_every_graph_call_carries_the_token_and_the_session_asks_to_replace(self):
		path = make_file(10)
		self.addCleanup(os.remove, path)
		session = FakeSession(chunk_answers=[response(201, {"id": "file-1"})])
		self.client(session).upload_file(path)
		graph_calls = [c for c in session.calls if c[0] != "PUT"]
		self.assertTrue(all(c[2]["headers"]["Authorization"] == "Bearer tok-1" for c in graph_calls))
		create = next(c for c in graph_calls if c[1].endswith(":/createUploadSession"))
		self.assertIn(os.path.basename(path), create[1])
		self.assertEqual(create[2]["json"]["item"]["@microsoft.graph.conflictBehavior"], "replace")

	def test_missing_folder_is_created_first(self):
		path = make_file(10)
		self.addCleanup(os.remove, path)
		session = FakeSession(folder_exists=False, chunk_answers=[response(201, {"id": "file-1"})])
		self.client(session).upload_file(path)
		methods = [(c[0], c[1].rsplit("/", 1)[-1]) for c in session.calls]
		self.assertIn(("POST", "children"), methods)
		create = next(c for c in session.calls if c[1].endswith("/children"))
		self.assertEqual(create[2]["json"]["name"], "gva-sf")
		self.assertEqual(create[2]["json"]["folder"], {})

	def test_existing_folder_is_left_alone(self):
		path = make_file(10)
		self.addCleanup(os.remove, path)
		session = FakeSession(folder_exists=True, chunk_answers=[response(201, {"id": "file-1"})])
		self.client(session).upload_file(path)
		self.assertFalse(any(c[1].endswith("/children") for c in session.calls))

	def test_a_failed_piece_is_retried_and_then_succeeds(self):
		path = make_file(10)
		self.addCleanup(os.remove, path)
		session = FakeSession(
			chunk_answers=[
				response(503, None),
				requests.ConnectionError("blip"),
				response(201, {"id": "file-1"}),
			]
		)
		item = self.client(session).upload_file(path)
		self.assertEqual(item["id"], "file-1")
		self.assertEqual(len([c for c in session.calls if c[0] == "PUT"]), 3)

	def test_three_failures_on_one_piece_stop_the_upload(self):
		path = make_file(10)
		self.addCleanup(os.remove, path)
		session = FakeSession(chunk_answers=[response(503, None), response(503, None), response(503, None)])
		with self.assertRaises(MicrosoftError) as caught:
			self.client(session).upload_file(path)
		self.assertIn("after 3 tries", str(caught.exception))
		self.assertIn("bytes 0-9 of 10", str(caught.exception))

	def test_a_refused_piece_is_not_retried(self):
		path = make_file(10)
		self.addCleanup(os.remove, path)
		session = FakeSession(
			chunk_answers=[
				response(404, {"error": {"code": "itemNotFound", "message": "Upload session expired"}})
			]
		)
		with self.assertRaises(MicrosoftError) as caught:
			self.client(session).upload_file(path)
		self.assertIn("Upload session expired", str(caught.exception))
		self.assertEqual(len([c for c in session.calls if c[0] == "PUT"]), 1)

	def test_refused_graph_call_is_explained_without_the_token(self):
		session = FakeSession()
		session.request = lambda method, url, **kwargs: response(
			403, {"error": {"code": "accessDenied", "message": "Access denied"}}
		)
		with self.assertRaises(MicrosoftError) as caught:
			self.client(session).site_id
		message = str(caught.exception)
		self.assertIn("403", message)
		self.assertIn("Access denied", message)
		self.assertNotIn("tok-1", message)

	def test_site_url_becomes_the_graph_address(self):
		session = FakeSession()
		client = self.client(session)
		self.assertEqual(client.site_id, SITE_ID)
		self.assertEqual(
			client.item_url("x.sql.gz"), f"{GRAPH_URL}/sites/{SITE_ID}/drive/root:/gva-sf/x.sql.gz"
		)
		self.assertEqual(len(session.calls), 1)
		client.site_id
		self.assertEqual(len(session.calls), 1, "the site id is looked up once")
