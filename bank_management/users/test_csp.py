from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse


def policy_from(response):
    header = response["Content-Security-Policy-Report-Only"]
    parsed = {}
    for part in header.split(";"):
        words = part.split()
        if words:
            parsed[words[0]] = words[1:]
    return parsed


class ContentSecurityPolicyTests(TestCase):
    def setUp(self):
        self.policy = policy_from(self.client.get(reverse("login")))

    def test_everything_defaults_to_this_site_only(self):
        self.assertEqual(self.policy["default-src"], ["'self'"])

    def test_plugins_and_framing_are_off(self):
        self.assertEqual(self.policy["object-src"], ["'none'"])
        self.assertEqual(self.policy["frame-ancestors"], ["'none'"])

    def test_forms_and_base_tag_stay_on_this_site(self):
        self.assertEqual(self.policy["form-action"], ["'self'"])
        self.assertEqual(self.policy["base-uri"], ["'self'"])

    def test_scripts_never_allow_inline_or_eval(self):
        scripts = self.policy["script-src"]
        self.assertIn("'self'", scripts)
        self.assertNotIn("'unsafe-inline'", scripts)
        self.assertNotIn("'unsafe-eval'", scripts)


class PinnedRequirementsTests(TestCase):
    def test_every_requirement_is_pinned_to_one_version(self):
        path = Path(settings.BASE_DIR).parent / "requirements.txt"
        self.assertTrue(path.exists(), "requirements.txt is missing")
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
        packages = [l for l in lines if l and not l.startswith("#")]
        self.assertTrue(packages)
        for line in packages:
            self.assertIn("==", line, line)
        names = {l.split("==")[0].lower() for l in packages}
        self.assertIn("django", names)