"""Making the backup file: Frappe's own database dump, nothing else.

No attachment archives are made. Frappe always writes a copy of the site
config (with the encryption key) next to the dump on the site's own disk,
as it does for its scheduled backups; that copy is never uploaded. Only the
path of the database file is handed on (decision D-5).
"""

import os

import frappe
from frappe import _
from frappe.utils.backups import new_backup


def make_backup() -> dict:
	"""A fresh, database-only dump through Frappe's own backup.

	Returns the file's path, name and size in MB. `force=True` so every run
	makes a new file instead of reusing one Frappe took earlier in the day.
	"""
	backup = new_backup(ignore_files=True, force=True)
	path = getattr(backup, "backup_path_db", None)
	if not path or not os.path.exists(path):
		frappe.throw(_("Frappe did not produce a database backup file."))
	size_mb = round(os.path.getsize(path) / (1024 * 1024), 2)
	return {"path": path, "file_name": os.path.basename(path), "size_mb": size_mb}
