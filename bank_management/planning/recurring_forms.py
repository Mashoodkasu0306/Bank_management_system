from datetime import timedelta

from django import forms
from django.utils import timezone

from accounts.models import Account
from .models import RecurringPayment

MAX_RECURRING_PAYMENTS = 10  # active or paused ones per customer


class RecurringPaymentForm(forms.ModelForm):
    to_account_no = forms.CharField(label="Pay to account number", max_length=30)
    start_date = forms.DateField(
        label="First payment date",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    class Meta:
        model = RecurringPayment
        fields = ["from_account", "name", "amount", "category", "frequency", "end_date"]
        labels = {
            "from_account": "Pay from",
            "name": "Name (for example Rent)",
            "amount": "Amount each time",
            "category": "Category",
            "frequency": "How often",
            "end_date": "Last payment date (optional)",
        }
        widgets = {
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        self.instance.customer = customer  # lets the model check the source account is theirs

        self.fields["from_account"].queryset = Account.objects.filter(
            customer=customer, status="ACTIVE", account_type__in=["SAVINGS", "CURRENT"]
        ).order_by("account_no")
        self.fields["from_account"].label_from_instance = (
            lambda account: f"{account.account_no} - {account.get_account_type_display()}"
        )
        self.order_fields([
            "from_account", "to_account_no", "name", "amount", "category",
            "frequency", "start_date", "end_date",
        ])

    def clean_start_date(self):
        start = self.cleaned_data.get("start_date")
        today = timezone.localdate()
        if start and start < today:
            raise forms.ValidationError("The first payment date cannot be in the past.")
        if start and start > today + timedelta(days=366):
            raise forms.ValidationError("The first payment date must be within the next year.")
        return start

    def clean(self):
        cleaned = super().clean()
        from_account = cleaned.get("from_account")
        number = (cleaned.get("to_account_no") or "").strip()
        amount = cleaned.get("amount")
        start = cleaned.get("start_date")

        to_account = None
        if number:
            to_account = Account.objects.filter(account_no=number, status="ACTIVE").first()
            if to_account is None:
                self.add_error("to_account_no", "No active account with that number.")
            elif from_account and to_account.id == from_account.id:
                self.add_error("to_account_no", "Choose a different account from the one you pay from.")
                to_account = None

        if from_account and amount is not None and amount > from_account.daily_limit:
            self.add_error(
                "amount",
                f"This is above the daily limit of {from_account.daily_limit} on that account, "
                "so every payment would need staff approval.",
            )

        live = RecurringPayment.objects.filter(
            customer=self.customer,
            status__in=[RecurringPayment.ACTIVE, RecurringPayment.PAUSED],
        ).count()
        if live >= MAX_RECURRING_PAYMENTS:
            self.add_error(
                None,
                f"You can have at most {MAX_RECURRING_PAYMENTS} recurring payments. Cancel one first.",
            )

        # The model's own checks run after this and read these two values.
        if to_account is not None:
            self.instance.to_account = to_account
        if start:
            self.instance.set_start(start)
        return cleaned