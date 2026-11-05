# Copyright (c) 2026, SF Group of Companies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, split_emails, validate_email_address

CONNECTION_FIELDS = ("site_url", "folder", "tenant_id", "client_id", "client_secret")


class OffsiteBackupSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		backup_frequency: DF.Literal["Daily", "Weekly"]
		client_id: DF.Data | None
		client_secret: DF.Password | None
		enabled: DF.Check
		folder: DF.Data | None
		keep_daily: DF.Int
		keep_monthly: DF.Int
		last_file: DF.Data | None
		last_result: DF.SmallText | None
		last_run_on: DF.Datetime | None
		last_size_mb: DF.Float
		send_email_for_successful_backup: DF.Check
		send_notifications_to: DF.Data
		site_url: DF.Data | None
		tenant_id: DF.Data | None
	# end: auto-generated types

	def validate(self):
		self.validate_connection()
		self.validate_retention()
		self.validate_recipients()

	def validate_connection(self):
		"""Every connection field is required while backups are enabled."""
		if not self.enabled:
			return
		missing = [self.meta.get_label(f) for f in CONNECTION_FIELDS if not self.get(f)]
		if missing:
			frappe.throw(
				_("Fill {0} before enabling backups.").format(", ".join(missing)),
				title=_("Connection incomplete"),
			)
		if not str(self.site_url).lower().startswith("https://"):
			frappe.throw(_("SharePoint Site URL must start with https://"))

	def validate_retention(self):
		if cint(self.keep_daily) < 1:
			frappe.throw(_("Keep Daily Backups cannot be less than 1."))
		if cint(self.keep_monthly) < 0:
			frappe.throw(_("Keep Monthly Backups cannot be negative."))

	def validate_recipients(self):
		for address in split_emails(self.send_notifications_to or ""):
			validate_email_address(address, throw=True)
