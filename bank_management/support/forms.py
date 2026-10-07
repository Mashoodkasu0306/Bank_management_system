from datetime import timedelta

from django import forms
from django.db.models import Q
from django.utils import timezone

from accounts.models import Account
from transactions.models import Transaction

from .models import SupportCase

DISPUTE_WINDOW_DAYS = 90


def _transaction_label(txn):
    when = timezone.localtime(txn.timestamp).strftime("%d %b %Y")
    note = f" - {txn.remarks[:40]}" if txn.remarks else ""
    return f"{when}: {txn.get_transaction_type_display()} {txn.amount} ({txn.get_status_display()}){note}"


class CaseForm(forms.Form):
    case_type = forms.ChoiceField(choices=SupportCase.TYPE_CHOICES, label="This is a")
    category = forms.ChoiceField(choices=SupportCase.CATEGORY_CHOICES, label="What is it about?")
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(), required=False, label="Account (optional)"
    )
    transaction = forms.ModelChoiceField(
        queryset=Transaction.objects.none(), required=False,
        label="Transaction (needed for a dispute)",
        help_text=f"Only the last {DISPUTE_WINDOW_DAYS} days are shown.",
    )
    subject = forms.CharField(max_length=150)
    description = forms.CharField(
        max_length=2000, widget=forms.Textarea(attrs={"rows": 6, "cols": 60})
    )

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        accounts = Account.objects.filter(customer=customer)
        since = timezone.now() - timedelta(days=DISPUTE_WINDOW_DAYS)
        txns = (
            Transaction.objects.filter(
                Q(from_account__in=accounts) | Q(to_account__in=accounts),
                timestamp__gte=since,
            )
            .distinct()
            .order_by("-timestamp")
        )
        self.fields["account"].queryset = accounts
        self.fields["transaction"].queryset = txns
        self.fields["transaction"].label_from_instance = _transaction_label

    def clean(self):
        data = super().clean()
        txn = data.get("transaction")
        if data.get("case_type") == SupportCase.DISPUTE and txn is None \
                and "transaction" not in self.errors:
            self.add_error("transaction", "Please pick the transaction you are disputing.")
        if txn is not None and data.get("account") is None:
            own = [
                a for a in (txn.from_account, txn.to_account)
                if a is not None and a.customer_id == self.customer.id
            ]
            if own:
                data["account"] = own[0]
        return data


class ReplyForm(forms.Form):
    body = forms.CharField(
        max_length=2000, label="Your reply",
        widget=forms.Textarea(attrs={"rows": 4, "cols": 60}),
    )