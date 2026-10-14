from django import forms
from django.db.models import Q
from django.utils import timezone

from accounts.models import Account
from .models import SavingsGoal

MAX_ACTIVE_GOALS = 10


class SavingsGoalForm(forms.ModelForm):
    class Meta:
        model = SavingsGoal
        fields = ["account", "name", "target_amount", "target_date"]
        labels = {
            "account": "Account to track",
            "name": "Goal name",
            "target_amount": "Target amount",
            "target_date": "Target date (optional)",
        }
        help_texts = {
            "account": "Progress follows this account's balance. No money is moved or locked.",
        }
        widgets = {
            "target_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer
        self.instance.customer = customer  # lets the model check the account is theirs

        allowed = Q(customer=customer, status="ACTIVE", account_type__in=["SAVINGS", "CURRENT"])
        if self.instance.pk:
            allowed = allowed | Q(pk=self.instance.account_id)  # keep the current one visible
        self.fields["account"].queryset = Account.objects.filter(allowed).order_by("account_no")
        self.fields["account"].label_from_instance = (
            lambda account: f"{account.account_no} - {account.get_account_type_display()}"
        )

    def clean_target_date(self):
        target_date = self.cleaned_data.get("target_date")
        if target_date and "target_date" in self.changed_data and target_date < timezone.localdate():
            raise forms.ValidationError("The target date cannot be in the past.")
        return target_date

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk:
            active = SavingsGoal.objects.filter(
                customer=self.customer, status=SavingsGoal.ACTIVE
            ).count()
            if active >= MAX_ACTIVE_GOALS:
                raise forms.ValidationError(
                    f"You can have at most {MAX_ACTIVE_GOALS} active goals. Archive one first."
                )
        return cleaned