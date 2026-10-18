# Architecture

## Stack
- Django 6.0.2, Python 3.14, SQLite, timezone Asia/Kolkata.
- Plain Django templates, one stylesheet (static/css/app.css), one small script (static/js/app.js). No React, no Bootstrap.
- Windows and PowerShell. Virtual environment: B_env at the repo root.

## Folders
- bank_management_system/ (repo root): B_env/, bank_management/ (the Django project), docs/
- bank_management/ holds manage.py, the settings folder bank_management/, the apps, static/, templates/ and media/ (uploads, git-ignored).
- Run every command from bank_management/ (the folder with manage.py).

## Apps
- users: login, customers, employees (with department), dashboards, Customer 360, security activity, spending summary.
- bank: banks, branches, assigning employees, employee departments. is_admin and is_admin_or_employee live in bank/views.py.
- accounts: accounts and the daily limit.
- transactions: deposit, withdraw, transfer, approvals, categories, history, branch report.
- loans: loans, repayments, eligibility, documents, foreclosure, renewal.
- services: KYC, ATM cards, cheque books, statements, emergency freeze.
- notifications: Notification model and department routing (notify_staff).
- audit: AuditLog, log_action, login signals, security alerts.
- reports: report pages, CSV and PDF export.
- support: disputes and complaints.
- planning: savings goals, recurring payments, Money Insights.
- core: PWA views (manifest, service worker, offline page).

## Rules built into the code
- Role by record presence: Customer record = customer, Employee record = employee, neither = admin.
- Money uses Decimal. Anything that changes a balance runs in transaction.atomic() with select_for_update().
- Over the daily limit a transaction is saved as PENDING and the Transactions department is alerted.
- Notifications go to one department only; admins receive all.
- Staff and customer actions call log_action; login, failed login and logout are logged by signals.
- Local imports are used where a top-level import would be circular.

## Front end
- templates/base.html is the one shell: sidebar, top bar, back bar, messages, and a single content block.
- Pages are plain tables and forms that the global stylesheet makes look right; newer pages use the component classes in DESIGN.md.
- Partials: templates/partials/virtual_card.html (the ATM card picture).

## PWA
- /manifest.webmanifest, /sw.js and /offline/ are served by core/pwa.py.
- The service worker keeps only static files (CSS, JS, icons) and one public offline page. It never stores pages, balances, documents or anything under /media/. In DEBUG it fetches static files from the network first.

## Testing
- python manage.py test: 724 tests in about 21 seconds.
- A fast password hasher is used only when "test" is in sys.argv.
- users/test_template_tags.py fails if any template tag is split across lines.

## Known gaps
See Phase 14 in TASKS.md.