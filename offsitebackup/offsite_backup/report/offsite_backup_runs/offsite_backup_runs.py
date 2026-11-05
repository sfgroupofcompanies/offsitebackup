# Copyright (c) 2026, SF Group of Companies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "started_on", "label": _("Started On"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 90},
		{"fieldname": "trigger", "label": _("Trigger"), "fieldtype": "Data", "width": 90},
		{"fieldname": "file_name", "label": _("File"), "fieldtype": "Data", "width": 300},
		{"fieldname": "size_mb", "label": _("Size (MB)"), "fieldtype": "Float", "width": 100},
		{"fieldname": "duration_seconds", "label": _("Seconds"), "fieldtype": "Int", "width": 80},
		{"fieldname": "folder", "label": _("Folder"), "fieldtype": "Data", "width": 110},
		{"fieldname": "message", "label": _("Message"), "fieldtype": "Data", "width": 400},
		{
			"fieldname": "name",
			"label": _("Run"),
			"fieldtype": "Link",
			"options": "Offsite Backup Run",
			"width": 180,
		},
	]


def get_data(filters):
	from_date = getdate(filters.get("from_date") or add_days(nowdate(), -30))
	to_date = getdate(filters.get("to_date") or nowdate())
	conditions = [
		["Offsite Backup Run", "started_on", ">=", from_date],
		["Offsite Backup Run", "started_on", "<", add_days(to_date, 1)],
	]
	if filters.get("status"):
		conditions.append(["Offsite Backup Run", "status", "=", filters.status])
	return frappe.get_all(
		"Offsite Backup Run",
		filters=conditions,
		fields=[
			"name",
			"started_on",
			"status",
			"trigger",
			"file_name",
			"size_mb",
			"duration_seconds",
			"folder",
			"message",
		],
		order_by="started_on desc",
	)
