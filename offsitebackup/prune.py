"""Keeping the library tidy: the newest N nightly files plus the first file of each month.

Mirrors Dropbox's delete_older_backups (keep the newest N) and adds the monthly rule
from decision D-4: keep the first file of each of the last `keep_monthly` months, so
a year of monthly restore points survives while the nightly files roll over.
"""

import re
from datetime import date, datetime

from frappe.utils import getdate, nowdate

BACKUP_NAME = re.compile(r"^(?P<stamp>\d{8}_\d{6})-.*-database.*\.sql\.gz$")


def backup_date(file: dict):
	"""The day a backup file was taken, from Frappe's file name; else from Microsoft's created time."""
	match = BACKUP_NAME.match(file.get("name") or "")
	if match:
		return datetime.strptime(match.group("stamp"), "%Y%m%d_%H%M%S").date()
	created = file.get("created") or ""
	return getdate(created[:10]) if created else None


def choose_files_to_delete(files: list[dict], keep_daily: int, keep_monthly: int, today: date | None = None):
	"""Split the folder's files into (keep, delete). Only backup files are ever candidates."""
	today = today or getdate(nowdate())
	dated = []
	for file in files:
		day = backup_date(file)
		if BACKUP_NAME.match(file.get("name") or "") and day:
			dated.append((day, file.get("name") or "", file))
	dated.sort(key=lambda row: (row[0], row[1]), reverse=True)

	keep = {id(row[2]) for row in dated[: max(int(keep_daily), 0)]}

	months = set()
	year, month = today.year, today.month
	for _ in range(max(int(keep_monthly), 0)):
		months.add((year, month))
		month -= 1
		if month == 0:
			month, year = 12, year - 1
	first_of_month = {}
	for day, _name, file in sorted(dated, key=lambda row: (row[0], row[1])):
		key = (day.year, day.month)
		if key in months and key not in first_of_month:
			first_of_month[key] = file
	keep.update(id(file) for file in first_of_month.values())

	keep_list = [row[2] for row in dated if id(row[2]) in keep]
	delete_list = [row[2] for row in dated if id(row[2]) not in keep]
	return keep_list, delete_list


def prune_folder(client, keep_daily: int, keep_monthly: int, today: date | None = None) -> dict:
	"""List the folder, decide, delete. Returns what was kept and what was deleted, by name."""
	files = client.list_folder()
	keep, delete = choose_files_to_delete(files, keep_daily, keep_monthly, today)
	for file in delete:
		client.delete_item(file["id"])
	return {"kept": [f["name"] for f in keep], "deleted": [f["name"] for f in delete]}
