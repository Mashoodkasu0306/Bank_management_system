"""Rules for support cases. The views only call these functions."""
from django.db import transaction as db_transaction
from django.urls import reverse
from django.utils import timezone

from audit.helpers import log_action
from audit.models import Actions
from notifications.helpers import notify, notify_staff
from users.models import Customer

from .models import SupportCase, SupportMessage

MAX_OPEN_CASES = 10


class CaseError(Exception):
    """A rule was broken. The text is safe to show to the customer."""


def staff_case_path(case):
    # The staff case page is built in step 4C and uses exactly this path.
    return f"/support/staff/cases/{case.id}/"


def open_case(request, customer, case_type, category, subject, description,
              account=None, transaction=None):
    with db_transaction.atomic():
        # Lock the customer so two quick clicks cannot get past the limits below.
        Customer.objects.select_for_update().get(pk=customer.pk)

        open_now = SupportCase.objects.filter(
            customer=customer, status__in=SupportCase.OPEN_STATUSES
        )
        if open_now.count() >= MAX_OPEN_CASES:
            raise CaseError(
                f"You already have {MAX_OPEN_CASES} open cases. "
                "Please wait for the bank to answer some of them."
            )
        if case_type == SupportCase.DISPUTE and transaction is None:
            raise CaseError("A dispute needs a transaction.")
        if transaction is not None and open_now.filter(
            case_type=case_type, transaction=transaction
        ).exists():
            kind_word = "dispute" if case_type == SupportCase.DISPUTE else "complaint"
            raise CaseError(f"You already have an open {kind_word} for this transaction.")

        case = SupportCase.objects.create(
            case_type=case_type, customer=customer, account=account,
            transaction=transaction, category=category,
            subject=subject, description=description,
        )

    kind = case.get_case_type_display()
    log_action(
        Actions.CASE_OPENED, request=request,
        target_type="SUPPORT_CASE", target_id=case.id,
        details=f"{case.reference} {kind}: {subject}"[:500],
    )
    due = timezone.localtime(case.due_at).strftime("%d %b %Y")
    notify(
        customer.user, "SUPPORT_CASE", f"{kind} received ({case.reference})",
        f"We received your {kind.lower()}. The bank will answer in writing by {due}."[:500],
        link=reverse("support_case_detail", args=[case.id]),
        related_type="SUPPORT_CASE", related_id=case.id,
    )
    notify_staff(
        "STAFF_REQUEST", f"New {kind.lower()}: {case.reference}",
        f"{customer.user.username} raised a {kind.lower()}: {subject}. Answer due by {due}."[:500],
        link=staff_case_path(case), department="SUPPORT",
        related_type="SUPPORT_CASE", related_id=case.id,
    )
    return case


def customer_reply(request, case, body):
    with db_transaction.atomic():
        case = SupportCase.objects.select_for_update().get(pk=case.pk)
        if not case.is_open:
            raise CaseError("This case is closed, so replies are turned off.")
        message = SupportMessage.objects.create(
            case=case, author=request.user, from_staff=False, body=body
        )

    log_action(
        Actions.CASE_REPLIED, request=request,
        target_type="SUPPORT_CASE", target_id=case.id,
        details=f"{case.reference}: customer reply"[:500],
    )
    notify_staff(
        "STAFF_REQUEST", f"Customer replied on {case.reference}",
        f"{case.customer.user.username} added a reply to: {case.subject}"[:500],
        link=staff_case_path(case), department="SUPPORT",
        related_type="SUPPORT_CASE", related_id=case.id,
    )
    return message