from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse


class ShellTests(TestCase):
    def test_base_template_compiles(self):
        get_template("base.html")

    def test_static_files_are_found(self):
        self.assertIsNotNone(finders.find("css/app.css"))
        self.assertIsNotNone(finders.find("js/app.js"))

    def test_login_page_is_mobile_ready_and_has_no_sidebar(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('name="viewport"', html)
        self.assertIn("app-anon", html)
        self.assertNotIn('class="sidebar"', html)

    def test_admin_sees_sidebar_with_admin_links(self):
        user = get_user_model().objects.create_superuser("shell_admin", "a@example.com", "pass12345")
        self.client.force_login(user)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('class="sidebar"', html)
        self.assertIn("Audit Log", html)
        self.assertIn("Employee Departments", html)