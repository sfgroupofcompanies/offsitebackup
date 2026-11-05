"""Talking to Microsoft 365 for the backup: the access token.

The app registration (tenant id, client id, client secret) is exchanged for a
bearer token that is good for about an hour, long enough for one backup run.
There is no sign-in dance and no refresh token, unlike the Dropbox integration.
"""

import os

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


# ---------------------------------------------------------------------------
# The library: folder, upload session, chunks
# ---------------------------------------------------------------------------

GRAPH_URL = "https://graph.microsoft.com/v1.0"
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MiB, a multiple of the 320 KiB Microsoft requires
CHUNK_TRIES = 3
UPLOAD_TIMEOUT_SECONDS = 120


class GraphClient:
	"""One SharePoint document library, reached with one access token.

	`site_url` is the library's site, e.g. https://company.sharepoint.com/sites/ERPBackups;
	`folder` is the folder inside its default document library, e.g. gva-sf.
	"""

	def __init__(self, token: str, site_url: str, folder: str):
		self.token = token
		self.site_url = site_url.strip().rstrip("/")
		self.folder = folder.strip().strip("/")
		self.session = get_request_session()
		self._site_id = None

	# -- plumbing -----------------------------------------------------------

	def request(self, method: str, url: str, ok=(200,), **kwargs):
		"""One Graph call with the token; any answer outside `ok` becomes a MicrosoftError."""
		headers = {"Authorization": f"Bearer {self.token}", **kwargs.pop("headers", {})}
		kwargs.setdefault("timeout", TIMEOUT_SECONDS)
		try:
			response = self.session.request(method, url, headers=headers, **kwargs)
		except requests.RequestException as exc:
			raise MicrosoftError(_("Could not reach Microsoft: {0}").format(type(exc).__name__)) from exc
		if response.status_code not in ok:
			raise MicrosoftError(
				_("Microsoft answered {0} to {1} {2}: {3}").format(
					response.status_code, method, url.replace(GRAPH_URL, ""), describe_error(response)
				)
			)
		return response

	@property
	def site_id(self) -> str:
		"""Graph's id for the SharePoint site, looked up once from its URL."""
		if not self._site_id:
			parts = self.site_url.split("://", 1)[-1].split("/", 1)
			host = parts[0]
			path = "/" + parts[1] if len(parts) > 1 and parts[1] else ""
			url = f"{GRAPH_URL}/sites/{host}:{path}" if path else f"{GRAPH_URL}/sites/{host}"
			self._site_id = self.request("GET", url).json()["id"]
		return self._site_id

	def item_url(self, name: str = "") -> str:
		"""Path-based address of the folder, or of a file inside it."""
		path = f"{self.folder}/{name}" if name else self.folder
		return f"{GRAPH_URL}/sites/{self.site_id}/drive/root:/{path}"

	# -- folder ---------------------------------------------------------------

	def ensure_folder(self):
		"""Create the site's folder in the library if it is not there yet (mirrors Dropbox's create_folder_if_not_exists)."""
		response = self.request("GET", self.item_url(), ok=(200, 404))
		if response.status_code == 200:
			return
		self.request(
			"POST",
			f"{GRAPH_URL}/sites/{self.site_id}/drive/root/children",
			ok=(200, 201),
			json={"name": self.folder, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
		)

	# -- upload ---------------------------------------------------------------

	def upload_file(self, path: str) -> dict:
		"""Send one file into the folder in CHUNK_SIZE pieces; returns Microsoft's record of the file."""
		name = os.path.basename(path)
		size = os.path.getsize(path)
		self.ensure_folder()
		upload_url = self.request(
			"POST",
			f"{self.item_url(name)}:/createUploadSession",
			json={"item": {"@microsoft.graph.conflictBehavior": "replace", "name": name}},
		).json()["uploadUrl"]

		item = None
		with open(path, "rb") as handle:
			start = 0
			while start < size:
				chunk = handle.read(CHUNK_SIZE)
				end = start + len(chunk) - 1
				item = self._send_chunk(upload_url, chunk, start, end, size)
				start = end + 1
		if not item:
			raise MicrosoftError(_("Microsoft did not confirm the upload of {0}.").format(name))
		return item

	def _send_chunk(self, upload_url: str, chunk: bytes, start: int, end: int, size: int):
		"""PUT one piece, up to CHUNK_TRIES times. Returns the file record on the last piece, else None."""
		headers = {"Content-Length": str(len(chunk)), "Content-Range": f"bytes {start}-{end}/{size}"}
		last_error = None
		for _attempt in range(CHUNK_TRIES):
			try:
				response = self.session.put(
					upload_url, data=chunk, headers=headers, timeout=UPLOAD_TIMEOUT_SECONDS
				)
			except requests.RequestException as exc:
				last_error = type(exc).__name__
				continue
			if response.status_code in (200, 201):
				return response.json()
			if response.status_code == 202:
				return None
			last_error = f"{response.status_code}: {describe_error(response)}"
			if 400 <= response.status_code < 500 and response.status_code != 429:
				break  # Microsoft will not take this piece however often we send it
		raise MicrosoftError(
			_("Upload failed at bytes {0}-{1} of {2} after {3} tries: {4}").format(
				start, end, size, CHUNK_TRIES, last_error
			)
		)
