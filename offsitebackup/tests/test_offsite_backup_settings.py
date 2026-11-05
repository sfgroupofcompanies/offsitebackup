import frappe
from frappe.tests.utils import FrappeTestCase


def settings(**values):
	doc = frappe.get_doc("Offsite Backup Settings")
	doc.update(
		{
			"enabled": 0,
			"backup_frequency": "Daily",
			"site_url": "https://example.sharepoint.com/sites/ERPBackups",
			"folder": "test-site",
			"tenant_id": "tenant",
			"client_id": "client",
			"client_secret": "secret",
			"keep_daily": 30,
			"keep_monthly": 12,
			"send_notifications_to": "ops@example.com",
		}
	)
	doc.update(values)
	return doc


class TestOffsiteBackupSettings(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_disabled_saves_without_connection(self):
		doc = settings(site_url="", tenant_id="", client_id="", client_secret="")
		doc.save()
		self.assertEqual(doc.enabled, 0)

	def test_enabled_needs_every_connection_field(self):
		doc = settings(enabled=1, client_secret="")
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_enabled_needs_https(self):
		doc = settings(enabled=1, site_url="http://example.sharepoint.com/sites/ERPBackups")
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_enabled_with_everything_saves(self):
		doc = settings(enabled=1)
		doc.save()
		self.assertEqual(frappe.db.get_single_value("Offsite Backup Settings", "folder"), "test-site")

	def test_keep_daily_at_least_one(self):
		doc = settings(keep_daily=0)
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_bad_email_rejected(self):
		doc = settings(send_notifications_to="not-an-email")
		self.assertRaises(frappe.ValidationError, doc.save)
