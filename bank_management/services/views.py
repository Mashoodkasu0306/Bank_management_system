from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction as db_transaction
from django.utils import timezone
from django.http import HttpResponse

from users.models import Employee
from accounts.models import Account
from transactions.models import Transaction
from bank.views import is_admin_or_employee

from .models import (
    KYCVerification, KYCDocument, ATMCardRequest, ChequebookRequest, AccountStatement
)
from .forms import (
    KYCDocumentUploadForm, ATMCardRequestForm, ChequebookRequestForm, AccountStatementForm,
    KYCDocumentVerificationForm, ATMCardApprovalForm, ChequebookApprovalForm
)
from .helpers import (
    get_kyc_requirements,
    check_atm_card_eligibility, check_cheque_book_eligibility,
    get_statement_transactions, calculate_statement_balances,
    generate_statement_pdf, get_preset_date_range,
    require_verified_kyc,
    generate_card_number, generate_cvv, generate_expiry_date, mask_card_number
)
from notifications.helpers import notify, notify_staff


def is_employee(user):
    return user.is_authenticated and Employee.objects.filter(user=user).exists()


# ============================================================================
# KYC VERIFICATION VIEWS - CUSTOMER
# ============================================================================

@login_required
def kyc_dashboard(request):
    if not hasattr(request.user, 'customer'):
        messages.error(request, "Only customers can access KYC services.")
        return redirect('customer_dashboard')

    customer = request.user.customer
    kyc_verification, created = KYCVerification.objects.get_or_create(customer=customer)
    documents = kyc_verification.documents.all()

    mandatory_types, optional_types = get_kyc_requirements(customer)
    doc_status = {}

    for doc_type in mandatory_types + optional_types:
        docs = documents.filter(document_type=doc_type).order_by('-uploaded_at')
        if docs.exists():
            latest = docs.first()
            doc_status[doc_type] = {
                'status': latest.verification_status,
                'uploaded_at': latest.uploaded_at,
                'latest_doc': latest,
                'all_docs': docs,
            }
        else:
            doc_status[doc_type] = {
                'status': 'MISSING',
                'uploaded_at': None,
                'latest_doc': None,
                'all_docs': [],
            }

    is_fully_verified = kyc_verification.is_fully_verified()
    is_missing_income = kyc_verification.is_missing_income_proof()

    return render(request, 'services/kyc_dashboard.html', {
        'kyc_verification': kyc_verification,
        'doc_status': doc_status,
        'is_fully_verified': is_fully_verified,
        'is_missing_income': is_missing_income,
        'mandatory_types': mandatory_types,
        'optional_types': optional_types,
    })


@login_required
def upload_kyc_document(request):
    """
    One KYCDocument row per (customer, document_type) is kept at all times.
    Re-uploading a document type replaces the existing row's file and
    resets it to PENDING for re-review, instead of creating a duplicate —
    this covers both "I uploaded the wrong Aadhaar" and "please update my
    address proof" without ever piling up duplicate pending rows.
    """
    if not hasattr(request.user, 'customer'):
        messages.error(request, "Only customers can upload KYC documents.")
        return redirect('customer_dashboard')

    customer = request.user.customer
    kyc_verification, _ = KYCVerification.objects.get_or_create(customer=customer)

    only_field = request.GET.get('field') or request.POST.get('only_field')

    if request.method == 'POST':
        form = KYCDocumentUploadForm(request.POST, request.FILES, kyc_verification=kyc_verification, only_field=only_field)
        if form.is_valid():
            uploaded_docs = form.get_uploaded_documents()

            with db_transaction.atomic():
                result_docs = []
                for doc_type, file in uploaded_docs:
                    existing = KYCDocument.objects.filter(
                        kyc_verification=kyc_verification,
                        document_type=doc_type,
                    ).first()

                    if existing:
                        # Replace the file and reset for re-review, whatever
                        # its previous status was (pending/verified/rejected).
                        if existing.file:
                            existing.file.delete(save=False)
                        existing.file = file
                        existing.verification_status = 'PENDING'
                        existing.uploaded_at = timezone.now()
                        existing.verified_at = None
                        existing.verified_by = None
                        existing.reviewer_notes = ''
                        existing.rejection_reason = ''
                        existing.save()
                        result_docs.append((existing, 'updated'))
                    else:
                        doc = KYCDocument.objects.create(
                            kyc_verification=kyc_verification,
                            document_type=doc_type,
                            file=file,
                        )
                        result_docs.append((doc, 'uploaded'))

                kyc_verification.update_overall_status()

            summary = ", ".join(f"{d.get_document_type_display()} ({action})" for d, action in result_docs)
            notify_staff(
                "KYC",
                "KYC documents submitted for review",
                f"{request.user.username} submitted {len(result_docs)} document(s): {summary}.",
                link="/services/staff/kyc/pending/"
            )

            messages.success(request, f"{len(result_docs)} document(s) submitted. Awaiting verification.")
            return redirect('kyc_dashboard')
    else:
        form = KYCDocumentUploadForm(kyc_verification=kyc_verification)

    return render(request, 'services/upload_kyc_document.html', {'form': form})


# ============================================================================
# ATM CARD VIEWS - CUSTOMER
# ============================================================================

@login_required
@require_verified_kyc
def request_atm_card(request):
    if not hasattr(request.user, 'customer'):
        messages.error(request, "Only customers can request ATM cards.")
        return redirect('customer_dashboard')

    customer = request.user.customer
    accounts = Account.objects.filter(customer=customer, status="ACTIVE", account_type__in=["SAVINGS", "CURRENT"])

    if request.method == 'POST':
        account_id = request.POST.get('account')
        account = accounts.filter(id=account_id).first()

        if not account:
            messages.error(request, "Select a valid account.")
            return redirect('request_atm_card')

        is_eligible, reason = check_atm_card_eligibility(account)
        if not is_eligible:
            messages.error(request, reason)
            return redirect('request_atm_card')

        form = ATMCardRequestForm(request.POST, account=account)
        if form.is_valid():
            atm_request = form.save(commit=False)
            atm_request.account = account
            atm_request.save()

            notify_staff(
                "ATM_CARD",
                "New ATM card request",
                f"{request.user.username} requested an ATM card for account {account.account_no}.",
                link="/services/staff/atm-card/pending/"
            )

            messages.success(request, "ATM card request submitted. Awaiting approval.")
            return redirect('atm_card_status', request_id=atm_request.id)
    else:
        form = ATMCardRequestForm(account=None)

    return render(request, 'services/request_atm_card.html', {
        'form': form,
        'accounts': accounts,
    })


@login_required
def atm_card_status(request, request_id):
    atm_request = get_object_or_404(ATMCardRequest, id=request_id)

    if atm_request.account.customer.user != request.user:
        messages.error(request, "You do not have permission to view this request.")
        return redirect('customer_dashboard')

    return render(request, 'services/atm_cards.html', {'atm_request': atm_request})


@login_required
def my_atm_cards(request):
    if not hasattr(request.user, 'customer'):
        messages.error(request, "Only customers can view their ATM cards.")
        return redirect('customer_dashboard')

    customer = request.user.customer
    accounts = Account.objects.filter(customer=customer)
    atm_requests = ATMCardRequest.objects.filter(account__in=accounts).order_by('-requested_at')

    return render(request, 'services/atm_cards.html', {'atm_requests': atm_requests})


# ============================================================================
# CHEQUE BOOK VIEWS - CUSTOMER
# ============================================================================

@login_required
@require_verified_kyc
def request_cheque_book(request):
    if not hasattr(request.user, 'customer'):
        messages.error(request, "Only customers can request cheque books.")
        return redirect('customer_dashboard')

    customer = request.user.customer
    accounts = Account.objects.filter(customer=customer, status="ACTIVE", account_type__in=["SAVINGS", "CURRENT"])

    if request.method == 'POST':
        account_id = request.POST.get('account')
        account = accounts.filter(id=account_id).first()

        if not account:
            messages.error(request, "Select a valid account.")
            return redirect('request_cheque_book')

        is_eligible, reason = check_cheque_book_eligibility(account)
        if not is_eligible:
            messages.error(request, reason)
            return redirect('request_cheque_book')

        form = ChequebookRequestForm(request.POST, account=account)
        if form.is_valid():
            cheque_request = form.save(commit=False)
            cheque_request.account = account
            cheque_request.save()

            notify_staff(
                "CHEQUE_BOOK",
                "New cheque book request",
                f"{request.user.username} requested a {cheque_request.leaf_count}-leaf cheque book for account {account.account_no}.",
                link="/services/staff/cheque-book/pending/"
            )

            messages.success(request, "Cheque book request submitted. Awaiting approval.")
            return redirect('cheque_book_status', request_id=cheque_request.id)
    else:
        form = ChequebookRequestForm(account=None)

    return render(request, 'services/cheque_books.html', {
        'form': form,
        'accounts': accounts,
    })


@login_required
def cheque_book_status(request, request_id):
    cheque_request = get_object_or_404(ChequebookRequest, id=request_id)

    if cheque_request.account.customer.user != request.user:
        messages.error(request, "You do not have permission to view this request.")
        return redirect('customer_dashboard')

    my_accounts = None
    if cheque_request.status == 'APPROVED' and cheque_request.cheque_book_fee > 0 and not cheque_request.fee_charged:
        my_accounts = Account.objects.filter(customer=request.user.customer, status='ACTIVE')

    return render(request, 'services/cheque_books.html', {
        'cheque_request': cheque_request,
        'my_accounts': my_accounts,
    })


@login_required
def pay_cheque_book_fee(request, request_id):
    """Step 1: collect account/mode - then show confirmation before actual debit."""
    cheque_request = get_object_or_404(ChequebookRequest, id=request_id, status='APPROVED')

    if cheque_request.account.customer.user != request.user:
        messages.error(request, "You can only pay fees for your own requests.")
        return redirect('customer_dashboard')

    if cheque_request.fee_charged:
        messages.error(request, "This fee has already been paid.")
        return redirect('cheque_book_status', request_id=cheque_request.id)

    if request.method == 'POST':
        my_accounts = Account.objects.filter(customer=request.user.customer, status='ACTIVE')
        mode = request.POST.get('mode_of_transaction', '').strip()
        upi_id = request.POST.get('upi_id', '').strip()
        card_number = request.POST.get('card_number', '').strip()
        card_cvv = request.POST.get('card_cvv', '').strip()
        card_expiry = request.POST.get('card_expiry', '').strip()

        if mode not in ('NETBANKING', 'UPI', 'CARD'):
            messages.error(request, "Please select a mode of transaction.")
            return redirect('cheque_book_status', request_id=cheque_request.id)

        if mode == 'UPI':
            if not upi_id:
                messages.error(request, "Enter a UPI ID.")
                return redirect('cheque_book_status', request_id=cheque_request.id)
            pay_account = my_accounts.filter(balance__gte=cheque_request.cheque_book_fee).order_by('-balance').first()
            if not pay_account:
                pay_account = my_accounts.order_by('-balance').first()
            if not pay_account:
                messages.error(request, "You have no active account to pay from.")
                return redirect('cheque_book_status', request_id=cheque_request.id)

        elif mode == 'CARD':
            account_id = request.POST.get('account_card', '').strip()
            if not card_number or not card_cvv or not card_expiry:
                messages.error(request, "Please fill in card number, CVV, and expiry date.")
                return redirect('cheque_book_status', request_id=cheque_request.id)
            if not account_id.isdigit():
                messages.error(request, "Select a valid account linked to this card.")
                return redirect('cheque_book_status', request_id=cheque_request.id)
            pay_account = my_accounts.filter(id=int(account_id)).first()
            if not pay_account:
                messages.error(request, "Select a valid account of yours to pay from.")
                return redirect('cheque_book_status', request_id=cheque_request.id)

        else:  # NETBANKING
            account_id = request.POST.get('account_netbanking', '').strip()
            if not account_id.isdigit():
                messages.error(request, "Select a valid account of yours to pay from.")
                return redirect('cheque_book_status', request_id=cheque_request.id)
            pay_account = my_accounts.filter(id=int(account_id)).first()
            if not pay_account:
                messages.error(request, "Select a valid account of yours to pay from.")
                return redirect('cheque_book_status', request_id=cheque_request.id)

        return render(request, 'services/confirm_cheque_book_fee.html', {
            'cheque_request': cheque_request,
            'account': pay_account,
            'mode': mode,
            'upi_id': upi_id,
            'card_number': card_number,
        })

    return redirect('cheque_book_status', request_id=cheque_request.id)


@login_required
def confirm_pay_cheque_book_fee(request, request_id):
    """Step 2: the actual debit happens only here, after explicit confirmation."""
    cheque_request = get_object_or_404(ChequebookRequest, id=request_id, status='APPROVED')

    if cheque_request.account.customer.user != request.user:
        messages.error(request, "You can only pay fees for your own requests.")
        return redirect('customer_dashboard')

    if cheque_request.fee_charged:
        messages.error(request, "This fee has already been paid.")
        return redirect('cheque_book_status', request_id=cheque_request.id)

    if request.method != 'POST':
        return redirect('cheque_book_status', request_id=cheque_request.id)

    account_id = request.POST.get('account', '').strip()
    mode = request.POST.get('mode_of_transaction', 'NETBANKING')
    upi_id = request.POST.get('upi_id', '').strip()

    if not account_id.isdigit():
        messages.error(request, "Select a valid account of yours to pay from.")
        return redirect('cheque_book_status', request_id=cheque_request.id)

    my_accounts = Account.objects.filter(customer=request.user.customer, status='ACTIVE')
    pay_account = my_accounts.filter(id=int(account_id)).first()

    if not pay_account:
        messages.error(request, "Select a valid account of yours to pay from.")
        return redirect('cheque_book_status', request_id=cheque_request.id)

    fee = cheque_request.cheque_book_fee

    with db_transaction.atomic():
        account = Account.objects.select_for_update().get(id=pay_account.id, status='ACTIVE')

        if account.balance < fee:
            messages.error(request, "Insufficient balance to pay this fee.")
            return redirect('cheque_book_status', request_id=cheque_request.id)

        account.balance -= fee
        account.save()

        remarks = f"Cheque book fee - {cheque_request.leaf_count} leaves (Request #{cheque_request.id})"
        if mode == 'UPI' and upi_id:
            remarks += f" (UPI: {upi_id})"

        Transaction.objects.create(
            transaction_type='WITHDRAW',
            from_account=account,
            amount=fee,
            mode_of_transaction=mode,
            status='SUCCESS',
            performed_by=request.user,
            remarks=remarks,
            is_loan_related=False,
        )

        cheque_request.fee_charged = True
        cheque_request.status = 'PROCESSING'
        cheque_request.save()

    notify(
        request.user, "CHEQUE_BOOK",
        "Cheque book order placed",
        f"Payment received. Your {cheque_request.leaf_count}-leaf cheque book is now being processed.",
        link=f"/services/cheque-book/{cheque_request.id}/status/"
    )

    messages.success(request, f"Fee of {fee} paid successfully. Your cheque book order is now being processed.")
    return redirect('cheque_book_status', request_id=cheque_request.id)


@login_required
def my_cheque_books(request):
    if not hasattr(request.user, 'customer'):
        messages.error(request, "Only customers can view their cheque book requests.")
        return redirect('customer_dashboard')

    customer = request.user.customer
    accounts = Account.objects.filter(customer=customer)
    cheque_requests = ChequebookRequest.objects.filter(account__in=accounts).order_by('-requested_at')

    return render(request, 'services/cheque_books.html', {'cheque_requests': cheque_requests})


# ============================================================================
# ACCOUNT STATEMENT VIEWS
# ============================================================================

@login_required
def download_account_statement(request, account_id):
    account = get_object_or_404(Account, id=account_id)

    if account.customer.user != request.user and not is_admin_or_employee(request.user):
        messages.error(request, "You do not have permission to access this account.")
        return redirect('customer_dashboard')

    if request.method == 'POST':
        form = AccountStatementForm(request.POST)
        if form.is_valid():
            period = form.cleaned_data['period']

            if period == 'custom':
                start_date = form.cleaned_data['start_date']
                end_date = form.cleaned_data['end_date']
            else:
                start_date, end_date = get_preset_date_range(period)

            pdf_buffer = generate_statement_pdf(account, start_date, end_date, request.user)

            transactions = get_statement_transactions(account, start_date, end_date)
            opening_balance, closing_balance = calculate_statement_balances(account, transactions, start_date)

            AccountStatement.objects.create(
                account=account,
                requested_by=request.user,
                start_date=start_date,
                end_date=end_date,
                transaction_count=transactions.count(),
                opening_balance=opening_balance,
                closing_balance=closing_balance,
            )

            response = HttpResponse(pdf_buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="statement_{account.account_no}_{start_date}_to_{end_date}.pdf"'
            return response
    else:
        form = AccountStatementForm()

    return render(request, 'services/download_statement.html', {
        'form': form,
        'account': account,
    })


# ============================================================================
# STAFF APPROVAL VIEWS
# ============================================================================

@login_required
@user_passes_test(is_admin_or_employee)
def pending_kyc_documents(request):
    """
    Groups pending KYC documents by customer — one row per customer with a
    pending-document count, instead of one row per document. Staff click
    through to review_customer_kyc to see and act on that customer's
    individual documents.
    """
    pending_docs = KYCDocument.objects.filter(verification_status='PENDING').select_related(
        'kyc_verification__customer__user'
    ).order_by('uploaded_at')

    customers_summary = {}
    for doc in pending_docs:
        customer = doc.kyc_verification.customer
        if customer.id not in customers_summary:
            customers_summary[customer.id] = {
                'customer': customer,
                'count': 0,
                'earliest_upload': doc.uploaded_at,
            }
        customers_summary[customer.id]['count'] += 1

    return render(request, 'services/staff/pending_kyc_documents.html', {
        'customers_summary': customers_summary.values(),
    })


@login_required
@user_passes_test(is_admin_or_employee)
def review_customer_kyc(request, customer_id):
    """Shows every pending (and already-reviewed) KYC document for one customer."""
    from users.models import Customer
    customer = get_object_or_404(Customer, id=customer_id)
    documents = KYCDocument.objects.filter(
        kyc_verification__customer=customer
    ).order_by('-uploaded_at')

    return render(request, 'services/staff/review_customer_kyc.html', {
        'customer': customer,
        'documents': documents,
    })


@login_required
@user_passes_test(is_admin_or_employee)
def verify_kyc_document(request, document_id):
    document = get_object_or_404(KYCDocument, id=document_id)

    if document.verification_status != 'PENDING':
        messages.error(request, "This document has already been reviewed.")
        return redirect('pending_kyc_documents')

    if request.method == 'POST':
        form = KYCDocumentVerificationForm(request.POST)
        if form.is_valid():
            status = form.cleaned_data['verification_status']
            notes = form.cleaned_data['reviewer_notes']
            rejection_reason = form.cleaned_data['rejection_reason']

            with db_transaction.atomic():
                document.verification_status = status
                document.verified_at = timezone.now()
                document.verified_by = request.user
                document.reviewer_notes = notes
                if status == 'REJECTED':
                    document.rejection_reason = rejection_reason
                document.save()

                # Update overall KYC status
                document.kyc_verification.update_overall_status()

                # If nothing is left pending for this customer, clear every
                # staff member's "new document" notifications for them —
                # there's nothing left to act on.
                still_pending = KYCDocument.objects.filter(
                    kyc_verification=document.kyc_verification,
                    verification_status='PENDING'
                ).exists()
                if not still_pending:
                    customer_username = document.kyc_verification.customer.user.username
                    from notifications.models import Notification
                    Notification.objects.filter(
                        category='KYC',
                        is_read=False,
                        message__icontains=customer_username,
                    ).filter(
                        title__in=['New KYC document uploaded', 'KYC documents submitted for review']
                    ).update(is_read=True)

            status_text = "verified" if status == 'VERIFIED' else "rejected"

            customer_user = document.kyc_verification.customer.user
            if status == 'VERIFIED':
                notify(
                    customer_user, "KYC",
                    "KYC document verified",
                    f"Your {document.get_document_type_display()} has been verified.",
                    link="/services/kyc/"
                )
            else:
                notify(
                    customer_user, "KYC",
                    "KYC document rejected",
                    f"Your {document.get_document_type_display()} was rejected. Reason: {rejection_reason}",
                    link="/services/kyc/"
                )

            messages.success(request, f"Document {status_text}.")
            return redirect('pending_kyc_documents')
    else:
        form = KYCDocumentVerificationForm()

    return render(request, 'services/staff/verify_kyc_document.html', {
        'document': document,
        'form': form,
    })


@login_required
@user_passes_test(is_admin_or_employee)
def pending_atm_card_requests(request):
    requests_list = ATMCardRequest.objects.filter(status='PENDING').select_related(
        'account__customer__user', 'account__branch'
    ).order_by('requested_at')

    return render(request, 'services/staff/approvals.html', {
        'requests': requests_list,
        'atm_card_request': True,
    })


@login_required
@user_passes_test(is_admin_or_employee)
def approve_atm_card_request(request, request_id):
    atm_request = get_object_or_404(ATMCardRequest, id=request_id)

    if atm_request.status != 'PENDING':
        messages.error(request, "This request has already been processed.")
        return redirect('pending_atm_card_requests')

    if request.method == 'POST':
        form = ATMCardApprovalForm(request.POST)
        if form.is_valid():
            status = form.cleaned_data['approval_status']

            with db_transaction.atomic():
                atm_request.status = status
                atm_request.approved_at = timezone.now()
                atm_request.approved_by = request.user

                customer_user = atm_request.account.customer.user

                if status == 'APPROVED':
                    full_card_number = generate_card_number()
                    cvv = generate_cvv()
                    expiry = generate_expiry_date()

                    atm_request.masked_card_number = mask_card_number(full_card_number)
                    atm_request.expiry_date = expiry
                    atm_request.save()

                    notify(
                        customer_user, "ATM_CARD",
                        "ATM card approved",
                        f"Your ATM card for account {atm_request.account.account_no} has been approved.",
                        link="/services/atm-card/my/"
                    )

                    messages.success(
                        request,
                        f"ATM card approved. Card Number: {full_card_number} | "
                        f"CVV: {cvv} | Expiry: {expiry.strftime('%m/%y')} — "
                        f"note this down now, it will not be shown again."
                    )
                else:
                    atm_request.rejection_reason = form.cleaned_data['rejection_reason']
                    atm_request.save()

                    notify(
                        customer_user, "ATM_CARD",
                        "ATM card request rejected",
                        f"Your ATM card request was rejected. Reason: {atm_request.rejection_reason}",
                        link="/services/atm-card/my/"
                    )

                    messages.success(request, "ATM card request rejected.")

            return redirect('pending_atm_card_requests')
    else:
        form = ATMCardApprovalForm()

    return render(request, 'services/staff/approvals.html', {
        'atm_request': atm_request,
        'form': form,
    })


@login_required
@user_passes_test(is_admin_or_employee)
def pending_cheque_book_requests(request):
    requests_list = ChequebookRequest.objects.filter(status='PENDING').select_related(
        'account__customer__user', 'account__branch'
    ).order_by('requested_at')

    return render(request, 'services/staff/approvals.html', {
        'requests': requests_list,
    })


@login_required
@user_passes_test(is_admin_or_employee)
def approve_cheque_book_request(request, request_id):
    cheque_request = get_object_or_404(ChequebookRequest, id=request_id)

    if cheque_request.status != 'PENDING':
        messages.error(request, "This request has already been processed.")
        return redirect('pending_cheque_book_requests')

    if request.method == 'POST':
        form = ChequebookApprovalForm(request.POST)
        if form.is_valid():
            status = form.cleaned_data['approval_status']

            with db_transaction.atomic():
                cheque_request.approved_at = timezone.now()
                cheque_request.approved_by = request.user

                if status == 'APPROVED':
                    fee = form.cleaned_data['cheque_book_fee']
                    cheque_request.cheque_book_fee = fee

                    if fee > 0:
                        # Fee is NOT deducted here — the customer pays it
                        # themselves via pay_cheque_book_fee. Order stays
                        # pending payment until then.
                        cheque_request.status = 'APPROVED'
                        cheque_request.fee_charged = False
                    else:
                        # No fee due — order can go straight to processing.
                        cheque_request.status = 'PROCESSING'
                        cheque_request.fee_charged = True
                else:
                    cheque_request.status = 'REJECTED'
                    cheque_request.rejection_reason = form.cleaned_data['rejection_reason']

                cheque_request.save()

            customer_user = cheque_request.account.customer.user

            if status == 'APPROVED' and cheque_request.cheque_book_fee > 0:
                notify(
                    customer_user, "CHEQUE_BOOK",
                    "Cheque book request approved - fee due",
                    f"Your cheque book request was approved. Pay {cheque_request.cheque_book_fee} to proceed.",
                    link=f"/services/cheque-book/{cheque_request.id}/status/"
                )
                messages.success(request, f"Request approved. A fee of {cheque_request.cheque_book_fee} is now pending payment from the customer.")
            elif status == 'APPROVED':
                notify(
                    customer_user, "CHEQUE_BOOK",
                    "Cheque book order placed",
                    f"Your cheque book request was approved and is now being processed.",
                    link=f"/services/cheque-book/{cheque_request.id}/status/"
                )
                messages.success(request, "Request approved with no fee — order placed for processing.")
            else:
                notify(
                    customer_user, "CHEQUE_BOOK",
                    "Cheque book request rejected",
                    f"Your cheque book request was rejected. Reason: {cheque_request.rejection_reason}",
                    link=f"/services/cheque-book/{cheque_request.id}/status/"
                )
                messages.success(request, "Cheque book request rejected.")
            return redirect('pending_cheque_book_requests')
    else:
        form = ChequebookApprovalForm()

    return render(request, 'services/staff/approvals.html', {
        'cheque_request': cheque_request,
        'form': form,
    })


# ============================================================================
# ADMIN DASHBOARD INTEGRATION
# ============================================================================

@login_required
@user_passes_test(is_admin_or_employee)
def services_dashboard(request):
    pending_kyc = KYCDocument.objects.filter(verification_status='PENDING').count()
    pending_atm = ATMCardRequest.objects.filter(status='PENDING').count()
    pending_cheque = ChequebookRequest.objects.filter(status='PENDING').count()

    total_kyc_verified = KYCVerification.objects.filter(status='VERIFIED').count()
    total_atm_approved = ATMCardRequest.objects.filter(status='APPROVED').count()
    total_cheque_approved = ChequebookRequest.objects.filter(status='APPROVED').count()

    # Role inference: an Employee record means this viewer is an employee,
    # not an admin — used to point "Back" link at the right dashboard.
    viewer_is_employee = Employee.objects.filter(user=request.user).exists()

    return render(request, 'services/staff/services_dashboard.html', {
        'pending_kyc': pending_kyc,
        'pending_atm': pending_atm,
        'pending_cheque': pending_cheque,
        'total_kyc_verified': total_kyc_verified,
        'total_atm_approved': total_atm_approved,
        'total_cheque_approved': total_cheque_approved,
        'viewer_is_employee': viewer_is_employee,
    })