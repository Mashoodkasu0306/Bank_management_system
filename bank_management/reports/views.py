from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from audit.helpers import log_action
from audit.models import Actions
from bank.models import Branch
from users.models import Customer, Employee

from . import loan_services, services
from .exports import csv_response
from .pdf import pdf_response

DEFAULT_RANGE_DAYS = 30
ROWS_ON_PAGE = 100


def _get_scope(user):
    """Returns (role, own_branch). Roles are found by which record exists."""
    if Customer.objects.filter(user=user).exists():
        return None, None
    employee = Employee.objects.filter(user=user).select_related("branch").first()
    if employee is not None:
        return "employee", employee.branch
    return "admin", None


def _read_date(raw):
    if not raw:
        return None
    try:
        return parse_date(raw)
    except ValueError:
        return None


def _read_range(request):
    raw_start = request.GET.get("start", "").strip()
    raw_end = request.GET.get("end", "").strip()
    start = _read_date(raw_start)
    end = _read_date(raw_end)
    if (raw_start and start is None) or (raw_end and end is None):
        messages.error(request, "A date was not valid, so the default was used for it.")

    if end is None:
        end = timezone.localdate()
    if start is None:
        start = end - timedelta(days=DEFAULT_RANGE_DAYS - 1)

    if start > end:
        messages.error(request, "The start date was after the end date, so the two were swapped.")
        start, end = end, start

    if (end - start).days > services.MAX_RANGE_DAYS:
        messages.error(
            request,
            f"The date range is limited to {services.MAX_RANGE_DAYS} days, so the start date was moved.",
        )
        start = end - timedelta(days=services.MAX_RANGE_DAYS)
    return start, end


def _failed_csv_rows(failed):
    rows = []
    for t in failed:
        rows.append([
            timezone.localtime(t.timestamp).strftime("%Y-%m-%d %H:%M"),
            t.get_transaction_type_display(),
            t.from_account.account_no if t.from_account else "",
            t.to_account.account_no if t.to_account else "",
            t.amount,
            t.get_mode_of_transaction_display(),
            t.performed_by.get_username() if t.performed_by else "",
            t.remarks,
        ])
    return rows


def _build_export(kind, start, end, branch, role):
    """Returns (title, file_prefix, headers, rows) for a CSV download, or None."""
    if kind == "totals":
        days, grand = services.totals_by_day(start, end, branch)
        headers = [
            "Date", "Deposits (count)", "Deposits (amount)",
            "Withdrawals (count)", "Withdrawals (amount)",
            "Transfers (count)", "Transfers (amount)",
        ]
        rows = [
            [d["day"], d["deposit_count"], d["deposit_total"], d["withdraw_count"],
             d["withdraw_total"], d["transfer_count"], d["transfer_total"]]
            for d in days
        ]
        rows.append([
            "Total", grand["deposit_count"], grand["deposit_total"], grand["withdraw_count"],
            grand["withdraw_total"], grand["transfer_count"], grand["transfer_total"],
        ])
        return "Transactions by day", "transactions_by_day", headers, rows

    if kind == "failed":
        headers = ["Date", "Type", "From account", "To account", "Amount", "Mode", "Performed by", "Remarks"]
        rows = _failed_csv_rows(services.failed_transactions(start, end, branch))
        return "Failed transactions", "failed_transactions", headers, rows

    if kind == "accounts":
        headers = ["Account no", "Customer", "Type", "Branch", "Status", "Opened on"]
        rows = [
            [a.account_no, a.customer.user.get_username(), a.get_account_type_display(),
             a.branch.name, a.get_status_display(), a.open_date]
            for a in services.new_accounts(start, end, branch)
        ]
        return "New accounts", "new_accounts", headers, rows

    if kind == "customers":
        headers = ["Username", "Name", "Joined on", "Customer type", "KYC status"]
        rows = [
            [c.user.get_username(), c.user.get_full_name(),
             timezone.localtime(c.user.date_joined).date(),
             c.get_customer_type_display(), c.get_kyc_status_display()]
            for c in services.new_customers(start, end, branch)
        ]
        return "New customers", "new_customers", headers, rows

    if kind == "branches" and role == "admin":
        headers = [
            "Branch", "Branch code", "Transactions", "Deposits", "Withdrawals",
            "Transfers", "New accounts", "New customers", "Active loans", "Overdue amount",
        ]
        rows = [
            [r["branch"].name, r["branch"].branch_code, r["txn_count"], r["deposit_total"],
             r["withdraw_total"], r["transfer_total"], r["new_accounts"], r["new_customers"],
             r["active_loans"], r["overdue_amount"]]
            for r in loan_services.branch_summary_with_loans(start, end)
        ]
        return "Branch-wise summary", "branch_summary", headers, rows

    if kind == "loans":
        headers = ["Measure", "Count", "Amount"]
        return "Loan summary", "loan_summary", headers, loan_services.loan_summary_rows(start, end, branch)

    if kind == "overdue":
        headers = ["Age of overdue installments", "Installments", "Loans", "Amount overdue"]
        return "Overdue installments by age", "overdue_by_age", headers, loan_services.overdue_summary_rows(branch)

    if kind == "overdue_detail":
        headers = [
            "Loan no", "Customer", "Account no", "Installment no",
            "Due date", "Days late", "Amount due", "Age bucket",
        ]
        return "Overdue installments detail", "overdue_detail", headers, loan_services.overdue_detail_rows(branch)

    return None


@login_required
def reports_home(request):
    role, own_branch = _get_scope(request.user)
    if role is None:
        messages.error(request, "You do not have permission to view reports.")
        return redirect("customer_dashboard")
    if role == "employee" and own_branch is None:
        messages.error(request, "You are not assigned to a branch yet.")
        return redirect("employee_dashboard")

    start, end = _read_range(request)

    branches = []
    selected_branch = own_branch
    if role == "admin":
        branches = Branch.objects.order_by("name")
        raw_branch = request.GET.get("branch", "").strip()
        selected_branch = branches.filter(id=int(raw_branch)).first() if raw_branch.isdigit() else None

    export = request.GET.get("export", "").strip()
    if export == "pdf":
        response = pdf_response(start, end, selected_branch, role)
        log_action(
            Actions.REPORT_EXPORTED, request=request, target_type="REPORT",
            details=f"Full report (PDF), {start} to {end}, {selected_branch.name if selected_branch else 'All branches'}",
        )
        return response
    if export:
        # The branch summary always covers every branch, whatever branch is chosen.
        export_branch = None if export == "branches" else selected_branch
        built = _build_export(export, start, end, export_branch, role)
        if built is not None:
            title, prefix, headers, rows = built
            label = export_branch.name if export_branch else "All branches"
            response = csv_response(f"{prefix}_{start}_{end}.csv", headers, rows)
            log_action(
                Actions.REPORT_EXPORTED, request=request, target_type="REPORT",
                details=f"{title} (CSV), {start} to {end}, {label}",
            )
            return response

    branch_label = selected_branch.name if selected_branch else "All branches"
    params = {"start": start, "end": end}
    if role == "admin" and selected_branch:
        params["branch"] = selected_branch.id

    days, grand = services.totals_by_day(start, end, selected_branch)
    failed = services.failed_transactions(start, end, selected_branch)
    accounts_qs = services.new_accounts(start, end, selected_branch)

    loan_status_rows, loan_total = loan_services.loan_status_counts(selected_branch)
    overdue_rows, overdue_total = loan_services.overdue_by_bucket(selected_branch)

    return render(request, "reports/reports_home.html", {
        "role": role,
        "start": start,
        "end": end,
        "qs": urlencode(params),
        "branches": branches,
        "selected_branch": selected_branch,
        "branch_label": branch_label,
        "days": days,
        "grand": grand,
        "failed_total": failed.count(),
        "failed_rows": failed[:ROWS_ON_PAGE],
        "failed_limit": ROWS_ON_PAGE,
        "new_accounts_count": accounts_qs.count(),
        "new_accounts_rows": accounts_qs[:ROWS_ON_PAGE],
        "new_customers_count": services.new_customers(start, end, selected_branch).count(),
        "branch_rows": loan_services.branch_summary_with_loans(start, end) if role == "admin" else [],
        "rows_limit": ROWS_ON_PAGE,
        "loan_status_rows": loan_status_rows,
        "loan_total": loan_total,
        "loan_outstanding": loan_services.loan_outstanding(selected_branch),
        "loan_money": loan_services.loan_money(start, end, selected_branch),
        "overdue_rows": overdue_rows,
        "overdue_total": overdue_total,
    })