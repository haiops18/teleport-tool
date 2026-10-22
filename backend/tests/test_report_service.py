import unittest
from app.services.report_service import safe_excel, status_of
class ReportServiceTests(unittest.TestCase):
    def test_status_mapping(self):
        self.assertEqual(status_of('SAFE'),'SAFE'); self.assertEqual(status_of('WARNING'),'WARNING'); self.assertEqual(status_of('UNREACHABLE'),'UNKNOWN')
    def test_excel_formula_injection(self):
        for value in ('=1+1','+cmd','-cmd','@cmd'): self.assertTrue(safe_excel(value).startswith("'"))
        self.assertEqual(safe_excel('java -jar app.jar'),'java -jar app.jar')
