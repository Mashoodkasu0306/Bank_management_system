# Product Requirements - Apex Core Banking (Bank Management System)

## Purpose
A Django banking system built as a learning and portfolio project. It shows real-world Django patterns: roles, money movement, approvals, audit, reports, and a mobile-friendly installable (PWA) interface.

## Users and roles
Roles are found by which record a user has (there is no role field):
- Customer record = customer. Neither record = admin (superuser).
- Customer: own accounts, transfers, loans, ATM cards, KYC, cheque books, support cases, savings goals, recurring payments, Money Insights.
- Employee: belongs to one branch and one department (Transactions, Loans, KYC, Cards and Services, Customer Support, Account Opening). Sees the tools of their own department first.
- Admin: everything, plus banks, branches, employee assignment, audit log, security alerts and reports for all branches.

## Features (built)
- Hierarchy: Bank -> Branch -> Employee -> Customer -> Account.
- Accounts: Savings, Current, Loan; daily limit and "remaining today".
- Transactions: deposit, withdraw, transfer, customer self-service transfer. Above the daily limit a transaction becomes PENDING and needs staff approval. Categories and a monthly Spending Summary.
- Loans: EMI and lump-sum repayment, amortization schedule, soft eligibility check, documents, DPD buckets, foreclosure, renewal (2 percent fee), staff approval.
- KYC: ID proof, PAN and address proof are mandatory; income proof is only needed for a loan. KYC gates loans, ATM cards, cheque books and self-service transfers.
- Cards: debit only; only a masked number is stored; freeze one card, set a daily card limit, emergency freeze of everything (lifted only by Customer Support or admin, with a written note).
- Cheque books (fee paid by the customer) and PDF account statements.
- Support cases: disputes and complaints with deadlines, messages and a written decision. No refund is made by the app.
- Notifications: bell and tabbed center; each department receives only its own alerts, admins receive all.
- Audit and security: audit log of staff and customer actions; security alerts (5 failed logins in 15 minutes, a transfer more than 5 times the usual).
- Reports: transactions by day and type, failed transactions, new customers and accounts, loans (status, outstanding, payouts and repayments, overdue by age), branch summary. CSV and PDF; every export is audited.
- Customer 360 (staff, read-only, audited), Savings goals (tracking only), Recurring payments (staff "Run due payments" button or manage.py run_recurring), Money Insights (safe to spend, cash flow, goals, loans).
- Front end: responsive shell for phone and PC; installable PWA with an offline page.

## Not in scope
AI features, open banking, UPI integration, biometrics, Kafka, card payments, automatic refunds.

## Success looks like
- All tests pass (724 at the end of Phase 13).
- Every page works on phone and PC.
- No secrets and no customer files in git.
- The Phase 14 security checklist in TASKS.md is finished.