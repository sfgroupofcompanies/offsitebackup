"""A stand-in for Microsoft's login service and Graph, for rehearsals without a tenant.

It keeps a "library" as a folder on disk and answers only the calls this app makes:
token, site lookup, folder check/create, upload session with chunks, listing, delete.

    bench --site <site> set-config offsitebackup_login_url http://127.0.0.1:8765
    bench --site <site> set-config offsitebackup_graph_url http://127.0.0.1:8765/v1.0
    ./env/bin/python -m offsitebackup.integrations.microsoft.fake /path/to/library --port 8765

Never run it on a real site: it accepts any credentials.
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.parse import unquote, urlparse

SITE_ID = "fake.sharepoint.com,11111111-1111-1111-1111-111111111111,22222222-2222-2222-2222-222222222222"


class FakeMicrosoft(BaseHTTPRequestHandler):
	library = "."  # set by serve()
	sessions: ClassVar[dict] = {}  # upload id -> target path
	log_requests = False

	# -- helpers ---------------------------------------------------------------

	def send(self, status, body=None):
		data = json.dumps(body).encode() if body is not None else b""
		self.send_response(status)
		if body is not None:
			self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		if data:
			self.wfile.write(data)

	def body(self):
		length = int(self.headers.get("Content-Length") or 0)
		return self.rfile.read(length) if length else b""

	def path_in_library(self, item_path: str) -> str:
		clean = os.path.normpath("/" + unquote(item_path)).lstrip("/")
		return os.path.join(self.library, clean)

	def item(self, full_path: str) -> dict:
		stat = os.stat(full_path)
		record = {
			"id": self.item_id(full_path),
			"name": os.path.basename(full_path),
			"size": stat.st_size,
			"createdDateTime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
		}
		if os.path.isdir(full_path):
			record["folder"] = {"childCount": len(os.listdir(full_path))}
		return record

	def item_id(self, full_path: str) -> str:
		return os.path.relpath(full_path, self.library).replace(os.sep, "|")

	def path_from_id(self, item_id: str) -> str:
		"""An item id back to a path, kept inside the library: the id comes from the request."""
		return self.path_in_library(unquote(item_id).replace("|", "/"))

	def log_message(self, fmt, *args):
		if self.log_requests:
			sys.stderr.write("fake-microsoft: " + fmt % args + "\n")

	# -- routes ------------------------------------------------------------------

	def do_POST(self):
		url = urlparse(self.path)
		if url.path.endswith("/oauth2/v2.0/token"):
			return self.send(
				200,
				{
					"token_type": "Bearer",
					"expires_in": 3599,
					"access_token": "fake-token-" + uuid.uuid4().hex,
				},
			)
		if not self.authorised():
			return
		m = re.match(r"^/v1\.0/sites/[^/]+/drive/root:/(.+):/createUploadSession$", url.path)
		if m:
			target = self.path_in_library(m.group(1))
			if not os.path.isdir(os.path.dirname(target)):
				return self.send(404, {"error": {"code": "itemNotFound", "message": "Folder not found"}})
			upload_id = uuid.uuid4().hex
			self.sessions[upload_id] = target
			open(target + ".partial", "wb").close()
			host = self.headers.get("Host")
			return self.send(
				200, {"uploadUrl": f"http://{host}/upload/{upload_id}", "expirationDateTime": ""}
			)
		if re.match(r"^/v1\.0/sites/[^/]+/drive/root/children$", url.path):
			payload = json.loads(self.body() or b"{}")
			target = self.path_in_library(payload.get("name", ""))
			if os.path.exists(target):
				return self.send(409, {"error": {"code": "nameAlreadyExists", "message": "Folder exists"}})
			os.makedirs(target)
			return self.send(201, self.item(target))
		self.send(404, {"error": {"code": "unknownRoute", "message": self.path}})

	def do_GET(self):
		url = urlparse(self.path)
		if not self.authorised():
			return
		if re.match(r"^/v1\.0/sites/[^/]+:/", url.path) or re.match(r"^/v1\.0/sites/[^/:]+$", url.path):
			return self.send(200, {"id": SITE_ID, "webUrl": "https://fake.sharepoint.com/sites/ERPBackups"})
		m = re.match(r"^/v1\.0/sites/[^/]+/drive/root:/(.+):/children$", url.path)
		if m:
			folder = self.path_in_library(m.group(1))
			if not os.path.isdir(folder):
				return self.send(404, {"error": {"code": "itemNotFound", "message": "Folder not found"}})
			names = sorted(n for n in os.listdir(folder) if not n.endswith(".partial"))
			return self.send(200, {"value": [self.item(os.path.join(folder, n)) for n in names]})
		m = re.match(r"^/v1\.0/sites/[^/]+/drive/root:/(.+)$", url.path)
		if m:
			target = self.path_in_library(m.group(1))
			if not os.path.exists(target):
				return self.send(404, {"error": {"code": "itemNotFound", "message": "Not found"}})
			return self.send(200, self.item(target))
		self.send(404, {"error": {"code": "unknownRoute", "message": self.path}})

	def do_PUT(self):
		url = urlparse(self.path)
		m = re.match(r"^/upload/([0-9a-f]+)$", url.path)
		if not m or m.group(1) not in self.sessions:
			self.body()
			return self.send(404, {"error": {"code": "itemNotFound", "message": "Upload session expired"}})
		target = self.sessions[m.group(1)]
		content_range = self.headers.get("Content-Range", "")
		r = re.match(r"^bytes (\d+)-(\d+)/(\d+)$", content_range)
		chunk = self.body()
		if not r or int(r.group(2)) - int(r.group(1)) + 1 != len(chunk):
			return self.send(
				400, {"error": {"code": "invalidRange", "message": f"Bad Content-Range {content_range}"}}
			)
		start, end, total = (int(x) for x in r.groups())
		with open(target + ".partial", "r+b") as handle:
			handle.seek(start)
			handle.write(chunk)
		if end + 1 < total:
			return self.send(202, {"nextExpectedRanges": [f"{end + 1}-{total - 1}"]})
		os.replace(target + ".partial", target)
		del self.sessions[m.group(1)]
		self.send(201, self.item(target))

	def do_DELETE(self):
		url = urlparse(self.path)
		if not self.authorised():
			return
		m = re.match(r"^/v1\.0/sites/[^/]+/drive/items/(.+)$", url.path)
		if m:
			target = self.path_from_id(m.group(1))
			if not os.path.isfile(target):
				return self.send(404, {"error": {"code": "itemNotFound", "message": "Not found"}})
			os.remove(target)
			return self.send(204)
		self.send(404, {"error": {"code": "unknownRoute", "message": self.path}})

	def authorised(self) -> bool:
		if (self.headers.get("Authorization") or "").startswith("Bearer fake-token-"):
			return True
		self.body()
		self.send(
			401,
			{
				"error": {
					"code": "InvalidAuthenticationToken",
					"message": "Access token is empty or not ours.",
				}
			},
		)
		return False


def serve(
	library: str, port: int = 8765, host: str = "127.0.0.1", log_requests: bool = False
) -> ThreadingHTTPServer:
	os.makedirs(library, exist_ok=True)
	FakeMicrosoft.library = os.path.abspath(library)
	FakeMicrosoft.log_requests = log_requests
	return ThreadingHTTPServer((host, port), FakeMicrosoft)


def main(argv=None):
	parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
	parser.add_argument("library", help="folder on disk that plays the SharePoint library")
	parser.add_argument("--port", type=int, default=8765)
	args = parser.parse_args(argv)
	server = serve(args.library, args.port, log_requests=True)
	print(f"fake Microsoft on http://127.0.0.1:{args.port}, library at {FakeMicrosoft.library}")
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		pass


if __name__ == "__main__":
	main()
