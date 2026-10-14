from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from planning.recurring import ERROR, run_due_payments, summarize


class Command(BaseCommand):
    help = (
        "Pay every recurring payment that is due. "
        "Use --dry-run to see what would happen without changing anything."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would happen. Nothing is paid, saved or sent.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        results = run_due_payments(now=timezone.now(), dry_run=dry_run)

        if dry_run:
            self.stdout.write("DRY RUN - nothing was changed.")
        if not results:
            self.stdout.write("Nothing is due.")
            return

        for result in results:
            amount = result["amount"] if result["amount"] is not None else "-"
            line = f'[{result["outcome"]}] #{result["id"]} {result["name"]} ({result["customer"]}) {amount}'
            if result["reason"]:
                line += f' - {result["reason"]}'
            self.stdout.write(line)

        summary = summarize(results)
        self.stdout.write("Done: " + ", ".join(f"{count} {outcome}" for outcome, count in sorted(summary.items())) + ".")

        if summary.get(ERROR):
            raise CommandError(f"{summary[ERROR]} payment(s) hit an unexpected error. See the log.")