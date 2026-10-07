"""Staff actions on support cases. The views only call these functions."""
from django.db import transaction as db_transaction
from django.urls import reverse
from django.utils import timezone

from audit.helpers import log_action
from audit.models import Actions
from notifications.helpers import notify
from notifications.models import Notification

from .models import SupportCase, SupportMessage
from .services import CaseError


def _lock_open_case(case_id):
    case = SupportCase.objects.select_for_update().get(pk=case_id)
    if not case.is_open:
        raise CaseError("This case has already been decided.")
    return case


def _take_if_free(case, user):
    """If nobody has the case yet, the person acting on it takes it."""
    if case.assigned_to_id is None:
        case.assigned_to = user
        case.status = SupportCase.IN_REVIEW
        case.save(update_fields=["assigned_to", "status"])


def _tell_customer(case, title, message):
    notify(
        case.customer.user, "SUPPORT_CASE", title[:150], message[:500],
        link=reverse("support_case_detail", args=[case.id]),
        related_type="SUPPORT_CASE", related_id=case.id,
    )


def pick_up_case(request, case_id):
    with db_transaction.atomic():
        case = _lock_open_case(case_id)
        if case.assigned_to_id and case.assigned_to_id != request.user.id:
            raise CaseError(f"This case is already being handled by {case.assigned_to.username}.")
        case.assigned_to = request.user
        case.status = SupportCase.IN_REVIEW
        case.save(update_fields=["assigned_to", "status"])
    log_action(
        Actions.CASE_PICKED_UP, request=request,
        target_type="SUPPORT_CASE", target_id=case.id,
        details=f"{case.reference}: picked up"[:500],
    )
    return case


def reply_as_staff(request, case_id, body):
    with db_transaction.atomic():
        case = _lock_open_case(case_id)
        _take_if_free(case, request.user)
        message = SupportMessage.objects.create(
            case=case, author=request.user, from_staff=True, body=body
        )
    log_action(
        Actions.CASE_REPLIED, request=request,
        target_type="SUPPORT_CASE", target_id=case.id,
        details=f"{case.reference}: staff reply"[:500],
    )
    _tell_customer(
        case, f"The bank replied ({case.reference})",
        f"The bank added a reply to your case: {case.subject}",
    )
    return message


def decide_case(request, case_id, decision, note):
    if decision not in (SupportCase.ACCEPTED, SupportCase.REJECTED):
        raise CaseError("Please choose accept or reject.")
    with db_transaction.atomic():
        case = _lock_open_case(case_id)
        case.status = decision
        case.decided_at = timezone.now()
        case.decided_by = request.user
        case.decision_note = note
        if case.assigned_to_id is None:
            case.assigned_to = request.user
        case.save()

    accepted = decision == SupportCase.ACCEPTED
    log_action(
        Actions.CASE_ACCEPTED if accepted else Actions.CASE_REJECTED, request=request,
        target_type="SUPPORT_CASE", target_id=case.id,
        details=f"{case.reference}: {note}"[:500],
    )
    # The staff alerts for this case are done with, so clear them for everyone.
    Notification.objects.filter(
        category="STAFF_REQUEST", related_type="SUPPORT_CASE",
        related_id=case.id, is_read=False,
    ).update(is_read=True)
    kind = case.get_case_type_display().lower()
    word = "accepted" if accepted else "rejected"
    _tell_customer(
        case, f"Your {kind} was {word} ({case.reference})",
        f"The bank has answered your {kind}. Open the case to read the written answer.",
    )
    return case