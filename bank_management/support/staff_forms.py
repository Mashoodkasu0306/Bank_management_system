from django import forms

from .models import SupportCase


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[(SupportCase.ACCEPTED, "Accept"), (SupportCase.REJECTED, "Reject")],
        widget=forms.RadioSelect, label="Decision",
    )
    note = forms.CharField(
        min_length=10, max_length=2000, label="Written answer for the customer",
        widget=forms.Textarea(attrs={"rows": 5, "cols": 60}),
        help_text="The customer sees this exactly as written. Explain the reason.",
    )