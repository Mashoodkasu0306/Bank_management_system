from django.contrib.auth.models import User
from django.test import TestCase

from notifications.helpers import notify, notify_staff
from notifications.models import Notification
from services.tests import make_bank_branch, make_customer, make_employee


class NotificationLabelTestCase(TestCase):
    def setUp(self):
        self.bank, self.branch = make_bank_branch()
        self.user, self.customer = make_customer(username="ali")
        self.emp_user, self.employee = make_employee(self.branch)

    def test_notify_saves_the_label(self):
        notify(self.user, "KYC", "Title", "Message", related_type="KYC", related_id=7)
        n = Notification.objects.get()
        self.assertEqual(n.related_type, "KYC")
        self.assertEqual(n.related_id, 7)

    def test_notify_without_label_leaves_it_empty(self):
        notify(self.user, "TRANSACTION", "Title", "Message")
        n = Notification.objects.get()
        self.assertEqual(n.related_type, "")
        self.assertIsNone(n.related_id)

    def test_notify_staff_saves_the_label_for_every_staff_member(self):
        User.objects.create_superuser(username="boss", password="x", email="boss@test.com")
        notify_staff("STAFF_REQUEST", "Title", "Message", related_type="KYC", related_id=3)
        notes = Notification.objects.all()
        self.assertEqual(notes.count(), 2)  # one employee + one superuser
        for n in notes:
            self.assertEqual(n.related_type, "KYC")
            self.assertEqual(n.related_id, 3)

    def test_label_tells_similar_usernames_apart_but_text_search_cannot(self):
        make_customer(username="alina")
        notify_staff("STAFF_REQUEST", "KYC pending", "Documents pending for ali",
                     related_type="KYC", related_id=1)
        notify_staff("STAFF_REQUEST", "KYC pending", "Documents pending for alina",
                     related_type="KYC", related_id=2)

        # The old way: searching the text for "ali" wrongly finds BOTH.
        self.assertEqual(Notification.objects.filter(message__icontains="ali").count(), 2)
        # The new way: the label finds exactly one.
        self.assertEqual(
            Notification.objects.filter(related_type="KYC", related_id=1).count(), 1
        )