from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from audit.models import Actions, AuditLog
from notifications.models import Notification

from .models import SupportCase, SupportMessage
from .test_customer_pages import COMPLAINT, make_customer, make_employee

NOTE = "We checked the records and this is our written answer."


class StaffCasePagesTests(TestCase):
    def setUp(self):
        self.customer = make_customer("cust_one")
        make_employee("support_a", "SUPPORT")
        make_employee("support_b", "SUPPORT")
        make_employee("kyc_emp", "KYC")
        User.objects.create_superuser("boss", "boss@test.com", "pass12345")
        self.case = SupportCase.objects.create(
            customer=self.customer, case_type="COMPLAINT", category="SERVICE",
            subject="Slow branch", description="I waited two hours.",
        )

    def login(self, username):
        self.client.logout()
        self.client.login(username=username, password="pass12345")

    def url(self, name):
        return reverse(name, args=[self.case.id])

    def decide(self, decision="ACCEPTED", note=NOTE):
        return self.client.post(
            self.url("support_staff_decide"), {"decision": decision, "note": note}
        )

    def audit_count(self, action):
        return AuditLog.objects.filter(action=action).count()

    def customer_notices(self):
        return Notification.objects.filter(
            recipient=self.customer.user, category="SUPPORT_CASE", related_id=self.case.id
        )

    # ---- who may use the staff pages ----
    def test_customer_cannot_open_staff_pages(self):
        self.login("cust_one")
        self.assertEqual(self.client.get(reverse("support_staff_cases")).status_code, 302)
        self.assertEqual(self.client.get(self.url("support_staff_case")).status_code, 302)

    def test_other_department_cannot_open_staff_pages(self):
        self.login("kyc_emp")
        self.assertEqual(self.client.get(reverse("support_staff_cases")).status_code, 302)
        self.assertEqual(self.client.get(self.url("support_staff_case")).status_code, 302)

    def test_support_employee_and_admin_can_open_queue(self):
        for name in ("support_a", "boss"):
            self.login(name)
            response = self.client.get(reverse("support_staff_cases"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Slow branch")
            self.assertContains(response, "cust_one")

    def test_support_employee_can_open_case_page(self):
        self.login("support_a")
        response = self.client.get(self.url("support_staff_case"))
        self.assertContains(response, "I waited two hours.")

    def test_other_department_cannot_decide(self):
        self.login("kyc_emp")
        self.decide()
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, SupportCase.OPEN)

    # ---- picking up ----
    def test_pick_up_assigns_and_audits(self):
        self.login("support_a")
        self.client.post(self.url("support_staff_pick_up"))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, SupportCase.IN_REVIEW)
        self.assertEqual(self.case.assigned_to.username, "support_a")
        self.assertEqual(self.audit_count(Actions.CASE_PICKED_UP), 1)

    def test_pick_up_needs_post(self):
        self.login("support_a")
        self.assertEqual(self.client.get(self.url("support_staff_pick_up")).status_code, 405)

    def test_second_employee_cannot_take_over(self):
        self.login("support_a")
        self.client.post(self.url("support_staff_pick_up"))
        self.login("support_b")
        self.client.post(self.url("support_staff_pick_up"))
        self.case.refresh_from_db()
        self.assertEqual(self.case.assigned_to.username, "support_a")

    def test_only_mine_filter(self):
        self.login("support_a")
        self.client.post(self.url("support_staff_pick_up"))
        mine = self.client.get(reverse("support_staff_cases") + "?mine=1")
        self.assertContains(mine, "Slow branch")
        self.login("support_b")
        theirs = self.client.get(reverse("support_staff_cases") + "?mine=1")
        self.assertNotContains(theirs, "Slow branch")

    # ---- replying ----
    def test_reply_is_saved_audited_and_customer_told(self):
        self.login("support_a")
        self.client.post(self.url("support_staff_reply"), {"body": "We are checking."})
        message = SupportMessage.objects.get(case=self.case)
        self.assertTrue(message.from_staff)
        self.assertEqual(self.audit_count(Actions.CASE_REPLIED), 1)
        self.assertEqual(self.customer_notices().count(), 1)
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, SupportCase.IN_REVIEW)
        self.assertEqual(self.case.assigned_to.username, "support_a")

    def test_cannot_reply_on_decided_case(self):
        self.case.status = SupportCase.ACCEPTED
        self.case.save()
        self.login("support_a")
        self.client.post(self.url("support_staff_reply"), {"body": "Too late"})
        self.assertEqual(SupportMessage.objects.filter(case=self.case).count(), 0)

    # ---- deciding ----
    def test_accept_saves_decision_audits_and_tells_customer(self):
        self.login("support_a")
        self.decide("ACCEPTED")
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, SupportCase.ACCEPTED)
        self.assertEqual(self.case.decision_note, NOTE)
        self.assertEqual(self.case.decided_by.username, "support_a")
        self.assertIsNotNone(self.case.decided_at)
        self.assertEqual(self.audit_count(Actions.CASE_ACCEPTED), 1)
        self.assertEqual(self.customer_notices().count(), 1)

    def test_reject_saves_decision_and_audits(self):
        self.login("support_a")
        self.decide("REJECTED")
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, SupportCase.REJECTED)
        self.assertEqual(self.audit_count(Actions.CASE_REJECTED), 1)
        self.assertEqual(self.customer_notices().count(), 1)

    def test_short_note_is_refused(self):
        self.login("support_a")
        self.decide("ACCEPTED", note="short")
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, SupportCase.OPEN)
        self.assertEqual(self.audit_count(Actions.CASE_ACCEPTED), 0)

    def test_a_case_cannot_be_decided_twice(self):
        self.login("support_a")
        self.decide("ACCEPTED")
        self.login("support_b")
        self.decide("REJECTED", note="A different answer that should not be saved.")
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, SupportCase.ACCEPTED)
        self.assertEqual(self.case.decision_note, NOTE)
        self.assertEqual(self.audit_count(Actions.CASE_REJECTED), 0)

    def test_decision_clears_staff_alerts(self):
        self.client.login(username="cust_one", password="pass12345")
        self.client.post(reverse("support_raise_case"), COMPLAINT)
        new_case = SupportCase.objects.exclude(pk=self.case.pk).get()
        alerts = Notification.objects.filter(
            category="STAFF_REQUEST", related_type="SUPPORT_CASE", related_id=new_case.id
        )
        self.assertGreater(alerts.filter(is_read=False).count(), 0)
        self.login("support_a")
        self.client.post(
            reverse("support_staff_decide", args=[new_case.id]),
            {"decision": "ACCEPTED", "note": NOTE},
        )
        self.assertEqual(alerts.filter(is_read=False).count(), 0)

    def test_customer_sees_the_answer_but_not_the_staff_name(self):
        self.login("support_a")
        self.decide("REJECTED")
        self.login("cust_one")
        response = self.client.get(reverse("support_case_detail", args=[self.case.id]))
        self.assertContains(response, NOTE)
        self.assertNotContains(response, "support_a")