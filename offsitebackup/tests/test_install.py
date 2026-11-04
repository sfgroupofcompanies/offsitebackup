import frappe
from frappe.tests.utils import FrappeTestCase


class TestInstall(FrappeTestCase):
	def test_app_is_installed(self):
		self.assertIn("offsitebackup", frappe.get_installed_apps())

	def test_module_is_registered(self):
		self.assertTrue(frappe.db.exists("Module Def", "Offsite Backup"))
