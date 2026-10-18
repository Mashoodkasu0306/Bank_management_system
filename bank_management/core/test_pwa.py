import json

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class PwaTests(TestCase):
    def test_manifest_describes_an_installable_app(self):
        response = self.client.get(reverse("pwa_manifest"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("manifest+json", response["Content-Type"])
        data = json.loads(response.content)
        self.assertEqual(data["name"], "Apex Core Banking")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual({icon["sizes"] for icon in data["icons"]}, {"192x192", "512x512"})

    def test_service_worker_is_served_for_the_whole_site(self):
        response = self.client.get(reverse("pwa_service_worker"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response["Content-Type"])
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("no-cache", response["Cache-Control"])
        self.assertEqual(reverse("pwa_service_worker"), "/sw.js")

    def test_service_worker_leaves_private_files_alone(self):
        body = self.client.get(reverse("pwa_service_worker")).content.decode()
        self.assertIn("/media/", body)
        self.assertIn("/offline/", body)
        self.assertIn("never stores pages", body)

    def test_offline_page_is_public_and_has_no_account_details(self):
        response = self.client.get(reverse("pwa_offline"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("You are offline", html)
        self.assertNotIn('class="sidebar"', html)

    def test_icons_exist(self):
        for name in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
            self.assertIsNotNone(finders.find("pwa/" + name), name)

    def test_pages_link_the_manifest(self):
        html = self.client.get(reverse("login")).content.decode()
        self.assertIn('rel="manifest"', html)
        self.assertIn("apple-touch-icon", html)