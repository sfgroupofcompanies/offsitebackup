"""Talking to Microsoft 365 for the backup: the access token.

The app registration (tenant id, client id, client secret) is exchanged for a
bearer token that is good for about an hour, long enough for one backup run.
There is no sign-in dance and no refresh token, unlike the Dropbox integration.
"""

import frappe
import requests
from frappe import _
from frappe.utils import get_request_session

LOGIN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
TIMEOUT_SECONDS = 30


class MicrosoftError(frappe.ValidationError):
	"""Microsoft could not be reached or refused the request. The message never contains the secret."""


def get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
	"""One POST to Microsoft's login service; returns the access token."""
	if not (tenant_id and client_id and client_secret):
		raise MicrosoftError(_("Tenant ID, Client ID and Client Secret are all required."))

	try:
		response = get_request_session().post(
			LOGIN_URL.format(tenant=tenant_id),
			data={
				"grant_type": "client_credentials",
				"client_id": client_id,
				"client_secret": client_secret,
				"scope": GRAPH_SCOPE,
			},
			timeout=TIMEOUT_SECONDS,
		)
	except requests.RequestException as exc:
		raise MicrosoftError(_("Could not reach Microsoft: {0}").format(type(exc).__name__)) from exc

	if response.status_code != 200:
		raise MicrosoftError(
			_("Microsoft refused the credentials ({0}): {1}").format(
				response.status_code, describe_error(response)
			)
		)

	token = response.json().get("access_token")
	if not token:
		raise MicrosoftError(_("Microsoft answered without an access token."))
	return token


def describe_error(response) -> str:
	"""Microsoft's own explanation of a failed request, short and safe to show."""
	try:
		body = response.json()
	except ValueError:
		return (response.text or "")[:200]
	if isinstance(body, dict):
		if "error_description" in body:
			return str(body["error_description"])[:200]
		error = body.get("error")
		if isinstance(error, dict):
			return str(error.get("message") or error.get("code") or "")[:200]
		if error:
			return str(error)[:200]
	return str(body)[:200]
