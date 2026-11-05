from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from offsitebackup.backup.prune import backup_date, choose_files_to_delete, prune_folder
from offsitebackup.integrations.microsoft.graph import GRAPH_URL, GraphClient

TODAY = date(2026, 11, 5)


def nightly(day: date, hour="023000", site="gva_sf"):
	stamp = day.strftime("%Y%m%d") + "_" + hour
	return {"id": f"id-{stamp}", "name": f"{stamp}-{site}-database.sql.gz", "size": 1, "created": ""}


def every_night(days_back: int):
	return [nightly(TODAY - timedelta(days=n)) for n in range(days_back)]


def names(files):
	return sorted(f["name"] for f in files)


class TestChooseFilesToDelete(FrappeTestCase):
	def test_keeps_the_newest_thirty_and_each_monthly_first(self):
		files = every_night(400)  # ~13 months of nightly files
		keep, delete = choose_files_to_delete(files, keep_daily=30, keep_monthly=12, today=TODAY)

		newest_30 = names(every_night(30))
		self.assertTrue(set(newest_30) <= set(names(keep)))
		# first file of each of the last 12 months (Nov 2026 back to Dec 2025) survives
		for year, month in [(2026, m) for m in range(11, 0, -1)] + [(2025, 12)]:
			first = min(f["name"] for f in files if f["name"].startswith(f"{year}{month:02d}"))
			self.assertIn(first, names(keep), f"{year}-{month} first file must be kept")
		# November 2025 is the 13th month back: gone, even its first file
		self.assertFalse(any(n.startswith("202511") for n in names(keep)))
		self.assertEqual(len(keep) + len(delete), 400)
		self.assertEqual(len(keep), 30 + 11)  # Nov 2026's first file is already inside the newest 30

	def test_nothing_deleted_while_under_the_daily_limit(self):
		files = every_night(10)
		keep, delete = choose_files_to_delete(files, 30, 12, today=TODAY)
		self.assertEqual(delete, [])
		self.assertEqual(len(keep), 10)

	def test_non_backup_files_are_never_touched(self):
		files = [
			*every_night(40),
			{"id": "x", "name": "README.txt", "size": 1, "created": "2020-01-01T00:00:00Z"},
			{"id": "y", "name": "20260101_000000-gva_sf-site_config_backup.json", "size": 1, "created": ""},
			{"id": "z", "name": "20260101_000000-gva_sf-files.tar", "size": 1, "created": ""},
		]
		keep, delete = choose_files_to_delete(files, 30, 12, today=TODAY)
		touched = names(keep) + names(delete)
		for odd in (
			"README.txt",
			"20260101_000000-gva_sf-site_config_backup.json",
			"20260101_000000-gva_sf-files.tar",
		):
			self.assertNotIn(odd, touched)

	def test_two_files_on_one_day_count_as_two(self):
		files = [*every_night(30), nightly(TODAY, hour="150000")]  # a manual run this afternoon
		keep, delete = choose_files_to_delete(files, 30, 0, today=TODAY)
		self.assertEqual(len(keep), 30)
		self.assertEqual(names(delete), [nightly(TODAY - timedelta(days=29))["name"]])

	def test_zero_monthly_keeps_only_the_daily_window(self):
		keep, delete = choose_files_to_delete(every_night(100), 30, 0, today=TODAY)
		self.assertEqual(len(keep), 30)
		self.assertEqual(len(delete), 70)

	def test_date_comes_from_the_name_then_from_microsoft(self):
		self.assertEqual(backup_date(nightly(date(2026, 3, 9))), date(2026, 3, 9))
		self.assertEqual(
			backup_date({"name": "odd.sql.gz", "created": "2026-04-01T02:30:00Z"}), date(2026, 4, 1)
		)
		self.assertIsNone(backup_date({"name": "odd.sql.gz", "created": ""}))


SITE = "https://example.sharepoint.com/sites/ERPBackups"
SITE_ID = "example.sharepoint.com,1,2"


def response(status, body):
	r = MagicMock()
	r.status_code = status
	r.json.return_value = body
	return r


class TestPruneFolder(FrappeTestCase):
	def client(self, pages):
		"""A GraphClient whose folder listing answers from `pages` (a list of Graph page bodies)."""
		session = MagicMock()
		pages = list(pages)
		self.deleted = []

		def request(method, url, **kwargs):
			if method == "GET" and url.endswith("/sites/ERPBackups"):
				return response(200, {"id": SITE_ID})
			if method == "GET" and (":/children" in url or url.endswith("/next")):
				return response(200, pages.pop(0))
			if method == "DELETE":
				self.deleted.append(url.rsplit("/", 1)[-1])
				return response(204, {})
			raise AssertionError(f"unexpected {method} {url}")

		session.request.side_effect = request
		with patch("offsitebackup.integrations.microsoft.graph.get_request_session", return_value=session):
			return GraphClient("tok", SITE, "gva-sf")

	def test_lists_every_page_skips_folders_and_deletes_the_right_files(self):
		files = every_night(35)
		page1 = {
			"value": [*files[:20], {"id": "f", "name": "sub", "folder": {}}],
			"@odata.nextLink": f"{GRAPH_URL}/next",
		}
		page2 = {"value": files[20:]}
		client = self.client([page1, page2])

		result = prune_folder(client, keep_daily=30, keep_monthly=0, today=TODAY)

		self.assertEqual(len(result["kept"]), 30)
		self.assertEqual(sorted(result["deleted"]), names(files[30:]))
		self.assertEqual(sorted(self.deleted), sorted(f["id"] for f in files[30:]))

	def test_listing_asks_for_the_folder_with_the_token(self):
		client = self.client([{"value": []}])
		self.assertEqual(client.list_folder(), [])
		call = client.session.request.call_args_list[-1]
		self.assertIn(f"/sites/{SITE_ID}/drive/root:/gva-sf:/children", call.args[1])
		self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer tok")

	def test_nothing_to_delete_means_no_delete_calls(self):
		client = self.client([{"value": every_night(5)}])
		result = prune_folder(client, 30, 12, today=TODAY)
		self.assertEqual(result["deleted"], [])
		self.assertEqual(self.deleted, [])
