from django import forms
from django.core.exceptions import ValidationError

from .models import KYCDocument, ATMCardRequest, ChequebookRequest


# ============================================================================
# KYC FORMS
# ============================================================================

class KYCDocumentUploadForm(forms.Form):
    """
    Lets a customer upload all applicable KYC documents in ONE submission,
    so staff get a single consolidated notification instead of one per file.
    Each field is optional individually (a customer may already have some
    verified, or income proof may not apply yet) but at least one is required.
    """
    id_proof = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'}),
        label="Government ID (Aadhaar/Passport)"
    )
    pan = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'}),
        label="PAN Card"
    )
    address_proof = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'}),
        label="Address Proof (Aadhaar/Passport/DL/Voter ID/Utility Bill)"
    )
    income_proof = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png'}),
        label="Income Proof (optional - only needed for loan applications)"
    )

    FIELD_TO_DOCUMENT_TYPE = {
        'id_proof': 'ID_PROOF',
        'pan': 'PAN',
        'address_proof': 'ADDRESS_PROOF',
        'income_proof': 'INCOME_PROOF',
    }

    def __init__(self, *args, **kwargs):
        self.kyc_verification = kwargs.pop('kyc_verification', None)
        only_field = kwargs.pop('only_field', None)
        super().__init__(*args, **kwargs)

        if only_field and only_field in self.FIELD_TO_DOCUMENT_TYPE:
            # Restrict the form to a single field, e.g. when the customer
            # clicked "Upload New Document" for one specific document type.
            for field_name in list(self.fields.keys()):
                if field_name != only_field:
                    del self.fields[field_name]
            self.fields[only_field].required = True

    def clean(self):
        cleaned_data = super().clean()
        has_any_file = any(cleaned_data.get(field) for field in self.fields)
        if not has_any_file:
            raise ValidationError("Please upload at least one document.")

        for field in self.fields:
            file = cleaned_data.get(field)
            if file and file.size > 5 * 1024 * 1024:
                raise ValidationError(f"{self.fields[field].label}: file size must not exceed 5MB.")

        return cleaned_data

    def get_uploaded_documents(self):
        """Returns list of (document_type, file) tuples for every field that was filled in."""
        result = []
        for field, doc_type in self.FIELD_TO_DOCUMENT_TYPE.items():
            if field not in self.fields:
                continue
            file = self.cleaned_data.get(field)
            if file:
                result.append((doc_type, file))
        return result


# ============================================================================
# ATM CARD REQUEST FORM
# ============================================================================

class ATMCardRequestForm(forms.ModelForm):
    class Meta:
        model = ATMCardRequest
        fields = ['delivery_address']
        widgets = {
            'delivery_address': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': 'Enter your complete delivery address'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.account = kwargs.pop('account', None)
        super().__init__(*args, **kwargs)


# ============================================================================
# CHEQUE BOOK REQUEST FORM
# ============================================================================

class ChequebookRequestForm(forms.ModelForm):
    class Meta:
        model = ChequebookRequest
        fields = ['leaf_count', 'delivery_address']
        widgets = {
            'leaf_count': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'delivery_address': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': 'Enter your complete delivery address'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.account = kwargs.pop('account', None)
        super().__init__(*args, **kwargs)


# ============================================================================
# ACCOUNT STATEMENT FORM
# ============================================================================

class AccountStatementForm(forms.Form):
    PERIOD_CHOICES = [
        ('last_30', 'Last 30 days'),
        ('last_90', 'Last 90 days'),
        ('last_180', 'Last 6 months'),
        ('last_365', 'Last 1 year'),
        ('custom', 'Custom date range'),
    ]

    period = forms.ChoiceField(
        choices=PERIOD_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial='last_30',
        label="Select Period"
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label="Start Date (custom range only)"
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        label="End Date (custom range only)"
    )

    def clean(self):
        cleaned_data = super().clean()
        period = cleaned_data.get('period')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if period == 'custom':
            if not start_date or not end_date:
                raise ValidationError("Please provide both start and end dates for custom range.")
            if start_date > end_date:
                raise ValidationError("Start date must be before or equal to end date.")
            if (end_date - start_date).days > 365:
                raise ValidationError("Date range cannot exceed 1 year (365 days).")
            from django.utils import timezone
            if end_date > timezone.localdate():
                raise ValidationError("End date cannot be in the future.")

        return cleaned_data


# ============================================================================
# STAFF APPROVAL FORMS
# ============================================================================

class KYCDocumentVerificationForm(forms.Form):
    VERIFICATION_CHOICES = [('VERIFIED', 'Approve'), ('REJECTED', 'Reject')]

    verification_status = forms.ChoiceField(
        choices=VERIFICATION_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label="Verification Status"
    )
    reviewer_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        label="Reviewer Notes"
    )
    rejection_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        label="Rejection Reason (if rejecting)"
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('verification_status') == 'REJECTED' and not cleaned_data.get('rejection_reason'):
            raise ValidationError("Please provide a rejection reason if rejecting this document.")
        return cleaned_data


class ATMCardApprovalForm(forms.Form):
    """Card number/CVV/expiry are auto-generated on approval (services.helpers)."""
    APPROVAL_CHOICES = [('APPROVED', 'Approve'), ('REJECTED', 'Reject')]

    approval_status = forms.ChoiceField(
        choices=APPROVAL_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label="Approval Status"
    )
    rejection_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        label="Rejection Reason (if rejecting)"
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('approval_status') == 'REJECTED' and not cleaned_data.get('rejection_reason'):
            raise ValidationError("Please provide a rejection reason if rejecting this request.")
        return cleaned_data


class ChequebookApprovalForm(forms.Form):
    APPROVAL_CHOICES = [('APPROVED', 'Approve'), ('REJECTED', 'Reject')]

    approval_status = forms.ChoiceField(
        choices=APPROVAL_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label="Approval Status"
    )
    cheque_book_fee = forms.DecimalField(
        required=False, max_digits=10, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00'}),
        label="Cheque Book Fee (if approving)"
    )
    rejection_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        label="Rejection Reason (if rejecting)"
    )

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('approval_status')
        fee = cleaned_data.get('cheque_book_fee')
        if status == 'REJECTED' and not cleaned_data.get('rejection_reason'):
            raise ValidationError("Please provide a rejection reason if rejecting this request.")
        if status == 'APPROVED':
            if fee is None:
                raise ValidationError("Please provide the cheque book fee (can be 0 if free).")
            if fee < 0:
                raise ValidationError("Fee cannot be negative.")
        return cleaned_data