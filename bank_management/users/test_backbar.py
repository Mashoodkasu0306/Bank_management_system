from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class BackBarTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser("back_admin", "b@example.com", "pass12345")
        self.client.force_login(user)

    def test_no_back_bar_on_the_dashboard(self):
        html = self.client.get(reverse("admin_dashboard")).content.decode()
        self.assertNotIn("data-back", html)

    def test_back_bar_on_other_pages(self):
        html = self.client.get(reverse("notifications_list")).content.decode()
        self.assertIn("data-back", html)
        self.assertIn("Dashboard</a>", html)

    def test_no_back_bar_when_logged_out(self):
        self.client.logout()
        html = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("data-back", html)