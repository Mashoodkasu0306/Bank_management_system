"""Recurring payments. This is the only place that moves money for them.

The staff button and the run_recurring command both call run_due_payments(), so they
cannot behave differently. Rules in short:
- A payment is paid once per run, then moved to its first date after today (missed dates
  are skipped, never paid in a burst).
- The payment row is locked and re-checked, so running twice never pays twice.
- The checks and their order match the customer's own transfer page.
- A failure is recorded, the customer is told, and the schedule still moves on.
  After MAX_FAILURES failures in a row the payment is paused.
"""
import calendar
import logging
from collections import Counter
from datetime import date, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction as db_transaction
from django.utils import timezone

from accounts.models import Account
from audit.alerts import check_large_transfer
from audit.helpers import log_action
from audit.models import Actions
from notifications.helpers import notify, notify_pending_transaction
from services.freeze import customer_has_active_freeze
from transactions.models import Transaction

from .models import RecurringPayment

logger = logging.getLogger(__name__)

PAID = "PAID"
PENDING = "PENDING"
FAILED = "FAILED"
ENDED = "ENDED"
ERROR = "ERROR"

MAX_FAILURES = 3
SYSTEM_USERNAME = "recurring-payments"


# ---------------------------------------------------------------- schedule

def next_run_after(payment, current):
    """The scheduled date that follows `current`."""
    if payment.frequency == RecurringPayment.WEEKLY:
        return current + timedelta(days=7)
    year = current.year + current.month // 12
    month = current.month % 12 + 1
    anchor = payment.anchor_day or current.day
    return date(year, month, min(anchor, calendar.monthrange(year, month)[1]))


def _advance(payment, today):
    """Moves next_run_date to the first scheduled date after today.
    Returns how many earlier scheduled dates were skipped."""
    upcoming = next_run_after(payment, payment.next_run_date)
    skipped = 0
    while upcoming <= today:
        if upcoming < today:
            skipped += 1
        upcoming = next_run_after(payment, upcoming)
    payment.next_run_date = upcoming
    return skipped


# ---------------------------------------------------------------- the rules

def _kyc_ok(customer):
    try:
        return customer.kyc_verification.is_fully_verified()
    except ObjectDoesNotExist:
        return False


def _decide(payment, from_acc, to_acc):
    """What would happen to this payment right now. Changes nothing.
    Returns (PAID | PENDING | FAILED, reason)."""
    from transactions.views import get_today_debit_total  # local import avoids a circle

    customer = payment.customer
    if customer_has_active_freeze(customer):
        return FAILED, "Your accounts are under an emergency freeze."
    if not _kyc_ok(customer):
        return FAILED, "KYC verification is not complete."
    if from_acc.customer_id != customer.id:
        return FAILED, "The source account no longer belongs to you."
    if from_acc.account_type not in ("SAVINGS", "CURRENT"):
        return FAILED, "Source account type cannot make payments."
    if from_acc.status != "ACTIVE":
        return FAILED, "Source account is not active."
    if to_acc.status != "ACTIVE":
        return FAILED, "Destination account is not active."
    if from_acc.id == to_acc.id:
        return FAILED, "Source and destination are the same account."
    if get_today_debit_total(from_acc) + payment.amount > from_acc.daily_limit:
        return PENDING, "Exceeds the daily limit; sent for approval."
    if from_acc.balance < payment.amount:
        return FAILED, "Insufficient balance."
    return PAID, ""


# ---------------------------------------------------------------- one payment

def _result(payment, outcome, reason=""):
    return {
        "id": payment.id,
        "name": payment.name,
        "customer": payment.customer.user.get_username(),
        "amount": payment.amount,
        "outcome": outcome,
        "reason": reason,
    }


def _make_txn(payment, from_acc, to_acc, status, remarks):
    return Transaction.objects.create(
        transaction_type="TRANSFER",
        from_account=from_acc,
        to_account=to_acc,
        amount=payment.amount,
        mode_of_transaction="NETBANKING",
        status=status,
        performed_by=payment.customer.user,
        remarks=remarks,
        category=payment.category,
    )


def _last_result(outcome, payment, reason, skipped, today):
    if outcome == PAID:
        text = f"Paid {payment.amount} on {today}"
    elif outcome == PENDING:
        text = "Sent for approval (over the daily limit)"
    else:
        text = f"Failed: {reason}"
    if skipped:
        text += f" ({skipped} missed payment{'s' if skipped != 1 else ''} skipped)"
    return text[:200]


def _process(payment_id, today, now):
    """Runs one payment inside one database transaction. Returns (result, info)."""
    with db_transaction.atomic():
        payment = RecurringPayment.objects.select_for_update().get(id=payment_id)
        if payment.status != RecurringPayment.ACTIVE or payment.next_run_date > today:
            return None, None  # someone else already ran it

        if payment.end_date and payment.next_run_date > payment.end_date:
            payment.status = RecurringPayment.ENDED
            payment.last_result = "Ended: past its end date."
            payment.save(update_fields=["status", "last_result", "updated_at"])
            return _result(payment, ENDED, "Past its end date."), None

        locked = {
            account.id: account
            for account in Account.objects.select_for_update().filter(
                id__in=[payment.from_account_id, payment.to_account_id]
            ).order_by("id")
        }
        from_acc = locked[payment.from_account_id]
        to_acc = locked[payment.to_account_id]

        outcome, reason = _decide(payment, from_acc, to_acc)
        if outcome == PAID:
            from_acc.balance -= payment.amount
            to_acc.balance += payment.amount
            from_acc.save()
            to_acc.save()
            txn = _make_txn(
                payment, from_acc, to_acc, "SUCCESS",
                f"Recurring: {payment.name} ({from_acc.account_no} -> {to_acc.account_no})",
            )
        elif outcome == PENDING:
            txn = _make_txn(
                payment, from_acc, to_acc, "PENDING",
                f"Exceeds daily limit ({from_acc.daily_limit}); awaiting approval | Recurring: {payment.name}",
            )
        else:
            txn = _make_txn(
                payment, from_acc, to_acc, "FAILED", f"Recurring: {payment.name} failed - {reason}"
            )

        skipped = _advance(payment, today)
        if outcome == FAILED:
            payment.consecutive_failures += 1
        else:
            payment.consecutive_failures = 0

        if outcome == FAILED and payment.consecutive_failures >= MAX_FAILURES:
            payment.status = RecurringPayment.PAUSED
            reason = f"{reason} Paused after {MAX_FAILURES} failed attempts in a row."
        elif payment.end_date and payment.next_run_date > payment.end_date:
            payment.status = RecurringPayment.ENDED

        payment.last_run_at = now
        payment.last_result = _last_result(outcome, payment, reason, skipped, today)
        payment.save(update_fields=[
            "next_run_date", "status", "consecutive_failures",
            "last_run_at", "last_result", "updated_at",
        ])

    info = {
        "payment": payment, "outcome": outcome, "reason": reason,
        "txn": txn, "from_acc": from_acc, "to_acc": to_acc,
    }
    return _result(payment, outcome, reason), info


def _after(info, run_by):
    """Audit lines and notifications. Done after the money is safely saved."""
    payment = info["payment"]
    outcome = info["outcome"]
    reason = info["reason"]
    from_acc = info["from_acc"]
    to_acc = info["to_acc"]
    customer_user = payment.customer.user
    username = "" if run_by else SYSTEM_USERNAME
    details = f"{payment.name}: {payment.amount} {from_acc.account_no} -> {to_acc.account_no}"
    link = f"/transactions/history/{from_acc.id}/"

    if outcome == PAID:
        log_action(
            Actions.RECURRING_PAID, actor=run_by, username=username,
            target_type="RECURRING_PAYMENT", target_id=payment.id, details=details,
        )
        notify(
            customer_user, "TRANSACTION", "Recurring payment made",
            f"{payment.amount} was sent from {from_acc.account_no} to {to_acc.account_no} ({payment.name}).",
            link=link,
        )
        if to_acc.customer_id != payment.customer_id:
            notify(
                to_acc.customer.user, "TRANSACTION", "Money received",
                f"{payment.amount} was credited to your account {to_acc.account_no} from {from_acc.account_no}.",
                link=f"/transactions/history/{to_acc.id}/",
            )
        check_large_transfer(from_acc, payment.amount)
    elif outcome == PENDING:
        log_action(
            Actions.RECURRING_PENDING, actor=run_by, username=username,
            target_type="RECURRING_PAYMENT", target_id=payment.id, details=details,
        )
        notify_pending_transaction(info["txn"])
        notify(
            customer_user, "TRANSACTION", "Recurring payment awaiting approval",
            f"{payment.name}: {payment.amount} is over the daily limit and was sent for approval.",
            link=link,
        )
    else:
        log_action(
            Actions.RECURRING_FAILED, actor=run_by, username=username,
            target_type="RECURRING_PAYMENT", target_id=payment.id, details=f"{details} - {reason}",
        )
        notify(
            customer_user, "TRANSACTION", "Recurring payment failed",
            f"{payment.name}: {reason}", link=link,
        )


def _preview(payment_id, today):
    payment = RecurringPayment.objects.select_related(
        "customer__user", "from_account", "to_account"
    ).get(id=payment_id)
    if payment.end_date and payment.next_run_date > payment.end_date:
        return _result(payment, ENDED, "Past its end date.")
    outcome, reason = _decide(payment, payment.from_account, payment.to_account)
    return _result(payment, outcome, reason)


# ---------------------------------------------------------------- the entry point

def run_due_payments(now=None, dry_run=False, run_by=None):
    """Pays every active recurring payment that is due. `now` must be a timezone-aware time.
    run_by: the staff user who started the run (None for the scheduled command).
    With dry_run=True nothing is written; the results show what would happen.
    Returns a list of result dicts: id, name, customer, amount, outcome, reason."""
    now = now or timezone.now()
    today = timezone.localtime(now).date()

    due_ids = list(
        RecurringPayment.objects.filter(
            status=RecurringPayment.ACTIVE, next_run_date__lte=today
        ).order_by("next_run_date", "id").values_list("id", flat=True)
    )

    results = []
    for payment_id in due_ids:
        try:
            if dry_run:
                result = _preview(payment_id, today)
                info = None
            else:
                result, info = _process(payment_id, today, now)
        except Exception as exc:  # one bad payment must not stop the others
            logger.exception("Recurring payment %s failed unexpectedly", payment_id)
            result = {
                "id": payment_id, "name": "", "customer": "", "amount": None,
                "outcome": ERROR, "reason": f"Unexpected error: {exc}",
            }
            info = None

        if info is not None:
            try:
                _after(info, run_by)
            except Exception:
                logger.exception("Recurring payment %s: audit or notification failed", payment_id)
        if result is not None:
            results.append(result)
    return results


def summarize(results):
    """Counts per outcome, for example {"PAID": 2, "FAILED": 1}."""
    return dict(Counter(result["outcome"] for result in results))