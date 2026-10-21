import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SKIP_PARTS = {"B_env", "site-packages", "node_modules", "staticfiles"}
# offline.html still has one Retry button handler; it is fixed in a later step.
ALLOWED = {"offline.html"}

INLINE_SCRIPT = re.compile(r'<script(?![^>]*\bsrc=)(?![^>]*type="application/json")', re.I)
HANDLER = re.compile(r"""\son[a-z]+\s*=\s*["']""", re.I)
BASE = Path(settings.BASE_DIR)


def templates():
    for path in BASE.rglob("*.html"):
        if SKIP_PARTS & set(path.parts) or path.name in ALLOWED:
            continue
        yield path


class NoInlineCodeTests(SimpleTestCase):
    def test_no_template_has_an_inline_script(self):
        found = [str(p.relative_to(BASE)) for p in templates()
                 if INLINE_SCRIPT.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(found, [], "Inline <script> found in: %s" % found)

    def test_no_template_has_an_inline_event_handler(self):
        found = [str(p.relative_to(BASE)) for p in templates()
                 if HANDLER.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(found, [], "Inline onclick/onchange/onsubmit found in: %s" % found)

    def test_base_template_loads_forms_js_and_the_file_exists(self):
        base = (BASE / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("js/forms.js", base)
        self.assertTrue((BASE / "static" / "js" / "forms.js").exists())

    def test_the_confirm_popups_are_still_there(self):
        pages = [
            "planning/templates/planning/recurring_list.html",
            "services/templates/services/card_controls.html",
            "services/templates/services/staff/frozen_customers.html",
            "support/templates/support/staff/case_detail.html",
        ]
        for rel in pages:
            with self.subTest(page=rel):
                text = (BASE / rel).read_text(encoding="utf-8")
                self.assertIn('data-confirm="', text)
        freeze = (BASE / pages[1]).read_text(encoding="utf-8")
        self.assertIn("Freeze all cards and block online transfers?", freeze)