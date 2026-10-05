import os
import re

from django.conf import settings
from django.test import SimpleTestCase

UNCLOSED = re.compile(r"\{\{[^}]*$|\{%[^%]*$")


class TemplateTagsOnOneLineTestCase(SimpleTestCase):
    """Django template tags cannot span lines. An editor that re-wraps long lines can break
    them, and the page then shows the raw {{ ... }} text instead of the value."""

    def test_no_template_tag_is_split_across_lines(self):
        base = str(settings.BASE_DIR)
        problems = []
        for folder, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules")]
            for name in files:
                if not name.endswith(".html"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    for number, line in enumerate(f, 1):
                        if UNCLOSED.search(line):
                            problems.append(
                                f"{os.path.relpath(path, base)}:{number}: {line.strip()[:80]}"
                            )
        self.assertEqual(problems, [], "Split template tags found:\n" + "\n".join(problems))
