from django.test import TestCase

from users.employee_stats import employee_kpis


class EmployeeKpiTests(TestCase):
    def test_all_five_cards_with_zero_counts_on_empty_database(self):
        cards = employee_kpis("")
        self.assertEqual([c["key"] for c in cards], ["transactions", "loans", "kyc", "atm", "cheque"])
        self.assertTrue(all(c["value"] == 0 for c in cards))

    def test_own_department_cards_come_first(self):
        self.assertEqual(employee_kpis("KYC")[0]["key"], "kyc")
        self.assertEqual(employee_kpis("LOANS")[0]["key"], "loans")
        first_two = [c["key"] for c in employee_kpis("CARDS_SERVICES")[:2]]
        self.assertEqual(first_two, ["atm", "cheque"])

    def test_cards_link_to_their_queues(self):
        urls = {c["key"]: c["url"] for c in employee_kpis("")}
        self.assertEqual(urls["transactions"], "/transactions/pending/")
        self.assertEqual(urls["loans"], "/loans/pending/")
        self.assertEqual(urls["kyc"], "/services/staff/kyc/pending/")