from unittest.mock import MagicMock, patch

import requests
from frappe.tests.utils import FrappeTestCase

from offsitebackup.microsoft import GRAPH_SCOPE, MicrosoftError, get_token

CREDS = {"tenant_id": "tenant-1", "client_id": "client-1", "client_secret": "s3cr3t"}


def fake_response(status=200, body=None, text=""):
	response = MagicMock()
	response.status_code = status
	response.text = text
	if body is None:
		response.json.side_effect = ValueError("no json")
	else:
		response.json.return_value = body
	return response


def fake_session(response=None, error=None):
	session = MagicMock()
	if error:
		session.post.side_effect = error
	else:
		session.post.return_value = response
	return session


class TestGetToken(FrappeTestCase):
	def test_good_answer_returns_the_token(self):
		session = fake_session(fake_response(200, {"access_token": "abc", "expires_in": 3599}))
		with patch("offsitebackup.microsoft.get_request_session", return_value=session):
			self.assertEqual(get_token(**CREDS), "abc")
		url = session.post.call_args.args[0]
		sent = session.post.call_args.kwargs
		self.assertIn("tenant-1", url)
		self.assertEqual(sent["data"]["grant_type"], "client_credentials")
		self.assertEqual(sent["data"]["scope"], GRAPH_SCOPE)
		self.assertEqual(sent["data"]["client_secret"], "s3cr3t")
		self.assertGreater(sent["timeout"], 0)

	def test_wrong_secret_is_explained_without_the_secret(self):
		body = {
			"error": "invalid_client",
			"error_description": "AADSTS7000215: Invalid client secret provided.",
		}
		session = fake_session(fake_response(401, body))
		with patch("offsitebackup.microsoft.get_request_session", return_value=session):
			with self.assertRaises(MicrosoftError) as caught:
				get_token(**CREDS)
		message = str(caught.exception)
		self.assertIn("401", message)
		self.assertIn("Invalid client secret", message)
		self.assertNotIn("s3cr3t", message)

	def test_microsoft_unreachable(self):
		session = fake_session(error=requests.ConnectionError("boom"))
		with patch("offsitebackup.microsoft.get_request_session", return_value=session):
			with self.assertRaises(MicrosoftError) as caught:
				get_token(**CREDS)
		self.assertIn("Could not reach Microsoft", str(caught.exception))

	def test_answer_without_token(self):
		session = fake_session(fake_response(200, {"token_type": "Bearer"}))
		with patch("offsitebackup.microsoft.get_request_session", return_value=session):
			self.assertRaises(MicrosoftError, get_token, **CREDS)

	def test_non_json_error_is_still_readable(self):
		session = fake_session(fake_response(503, None, text="Service Unavailable"))
		with patch("offsitebackup.microsoft.get_request_session", return_value=session):
			with self.assertRaises(MicrosoftError) as caught:
				get_token(**CREDS)
		self.assertIn("Service Unavailable", str(caught.exception))

	def test_missing_credentials_never_call_microsoft(self):
		session = fake_session(fake_response(200, {"access_token": "abc"}))
		with patch("offsitebackup.microsoft.get_request_session", return_value=session):
			self.assertRaises(MicrosoftError, get_token, "tenant-1", "client-1", "")
		session.post.assert_not_called()
