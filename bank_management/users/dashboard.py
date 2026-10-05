from django.urls import reverse

# Every block on the employee dashboard: key -> (title, [(url name, link text), ...])
SECTIONS = {
    "bank": ("Bank Structure", [
        ("bank_list", "View Banks"),
        ("branch_list", "View Branches"),
    ]),
    "customers": ("Customer Management", [
        ("register_customer", "Register New Customer"),
        ("customer_list", "View All Customers"),
    ]),
    "accounts": ("Accounts", [
        ("create_account", "Open New Account"),
        ("account_list", "View All Accounts"),
    ]),
    "transactions": ("Transactions", [
        ("deposit", "Deposit"),
        ("withdraw", "Withdraw"),
        ("transfer", "Transfer"),
        ("my_transactions", "My Transactions"),
        ("employee_search_customer_transactions", "Search Customer Transactions"),
        ("pending_transactions", "Pending Approvals"),
        ("branch_report", "My Branch Report"),
    ]),
    "loans": ("Loans", [
        ("pending_loans", "Pending Loan Applications"),
        ("all_loans", "All Loans"),
        ("pending_foreclosures", "Pending Foreclosure Requests"),
    ]),
    "kyc": ("KYC", [
        ("pending_kyc_documents", "Pending KYC Documents"),
    ]),
    "cards": ("Cards and Services", [
        ("services_dashboard", "Services Dashboard"),
        ("pending_atm_card_requests", "Pending ATM Card Requests"),
        ("pending_cheque_book_requests", "Pending Cheque Book Requests"),
    ]),
    # Shown only to the Customer Support department (it is not in DEFAULT_ORDER).
    "support": ("Customer Support", [
        ("frozen_customers", "Emergency Freezes"),
    ]),
}

DEFAULT_ORDER = ["bank", "customers", "accounts", "transactions", "loans", "kyc", "cards"]

# The blocks each department sees first. Nothing is hidden, only reordered.
FIRST_FOR_DEPARTMENT = {
    "TRANSACTIONS": ["transactions"],
    "LOANS": ["loans"],
    "KYC": ["kyc"],
    "ACCOUNT_OPENING": ["customers", "accounts"],
    "CARDS_SERVICES": ["cards"],
    "SUPPORT": ["support"],
}


def dashboard_sections(department):
    """The dashboard blocks in order: the department's own blocks first."""
    first = FIRST_FOR_DEPARTMENT.get(department, [])
    order = first + [key for key in DEFAULT_ORDER if key not in first]
    result = []
    for key in order:
        title, links = SECTIONS[key]
        result.append({
            "key": key,
            "title": title,
            "mine": key in first,
            "links": [{"url": reverse(name), "label": label} for name, label in links],
        })
    return result
