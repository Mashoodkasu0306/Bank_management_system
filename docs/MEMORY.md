# Memory

Facts and decisions to remember. Update this file whenever something important changes.

## Environment
- Django 6.0.2, Python 3.14, SQLite, Windows PowerShell. Virtual env: B_env at the repo root.
- Project folder: bank_management_system/bank_management (has manage.py). Run commands there.
- GitHub: Mashoodkasu0306/Bank_management_system, branch main.

## Test data
- Admin: Mashood. Employees: emp_test3 (Transactions), emp_test4 (KYC), Emp_1, Emp_2.
- Customers: customer_1 to customer_4. Bank: State Bank of Example (SBI001), branch Antophill. Account numbers look like SBI001-SBI-MUM-001-000001.

## Decisions
- Roles come from which record a user has, not from a role field.
- Emergency freeze can only be lifted by Customer Support staff or admin, with a written note. A single card freeze stays with the customer.
- Support cases are a record plus a written decision. No refund button; refunds are done by hand with the deposit tools.
- Savings goals only track progress against the account balance. They never lock money.
- Recurring payments run when staff press "Run due payments" or run manage.py run_recurring. No background scheduler.
- KYC: ID proof, PAN and address proof are mandatory; income proof is only needed for a loan.
- Front end: plain Django templates plus one stylesheet. No React, no Bootstrap.
- The service worker never caches pages or /media/.

## Gotchas
- The code editor can save empty files and can split template tags across lines. Write files with scripts and check with Get-Content.
- A test fails if a template tag is split across lines (users/test_template_tags.py).
- users/test_spending_pages.py needs the exact text width:100% (no space) in the spending bars.
- The fast password hasher is only active when "test" is in sys.argv.
- A pasted terminal can drop spaces at line wraps; the file may be fine.
- The planning test traceback "Recurring payment 1 failed unexpectedly ... boom" is a deliberate test, not a failure.
- Uploaded files in bank_management/media must stay out of git.

## Commit trail (newest last)
- b67d78b Money Insights page
- e75a911 responsive shell, dashboards, back bar
- 2336676 transactions, loans, services pages, virtual ATM card, faster branch report
- ecc261c support, planning, bank, account, reports, audit, admin pages
- 7ab35f8 PWA: manifest, service worker, icons, offline page, install button
- Later: balance totals rounded to two decimals; docs folder; media removed from git (Phase 14 starts)