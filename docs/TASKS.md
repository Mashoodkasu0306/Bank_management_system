# Tasks

## Done
- Phases 1-8: Bank/Branch/Employee hierarchy, customers, accounts, transactions, daily limits with approvals, admin dashboard, branch report, customer self-service transfer.
- Phase 9: Loans (EMI and lump sum, eligibility, documents, DPD, foreclosure, renewal).
- Phase 10: KYC, ATM cards, cheque books, PDF statements, notifications.
- Phase 11: Audit log, security alerts, file-content checks on uploads.
- Phase 12: Reports (CSV and PDF).
- Smart banking steps: departments and department notifications, card controls and emergency freeze, security activity page, support cases, Customer 360, transaction categories and spending summary, savings goals, recurring payments, Money Insights.
- Phase 13: responsive redesign of every page, dashboards, virtual ATM card, back bar, installable PWA. 724 tests pass.

## Phase 14 - Production readiness (the "20 things" checklist, in Django terms)
Legend: [x] done, [~] partly, [ ] to do, [n/a] does not apply.

### 14A Secrets and settings
- [ ] 1 Hide keys: move SECRET_KEY, DEBUG, ALLOWED_HOSTS and database settings to environment variables (.env, git-ignored). Make a NEW SECRET_KEY because the old one was in git.
- [~] 2 Purge git secrets: stop tracking bank_management/media (4 files found); scan history for secrets; remove files from history if the repo is public.
- [n/a] 3 Public DB key: a Supabase idea. In Django the database login stays on the server only.
- [~] 19 Force HTTPS: SECURE_SSL_REDIRECT, HSTS and secure cookies, switched on by an environment variable so local development still works.

### 14B Who can see what
- [~] 4 Row-level security: Django has none, so the same idea is "every query is filtered to the owner". Add automated tests that customer A cannot open customer B's account, loan, card, case or documents.
- [~] 6 Server-side auth: views already check login and role. Add a test that visits every URL as a stranger and expects a redirect (except login, manifest, sw.js, offline, static).
- [ ] 7 Lock record access: serve uploaded KYC and loan documents only through a view that checks the owner or staff. Today they use direct /media/ links.
- [~] 8 Block field tampering: the server decides status, amounts and roles; never trust hidden fields or POST values. Review views that read request.POST directly.
- [~] 5 Encrypt sensitive data: HTTPS in transit; store only the last 4 digits of a card (check test data); keep KYC files out of the web root; database and disk encryption come from the host.

### 14C Login and input safety
- [x] 10 Hash passwords: Django uses PBKDF2. The fast hasher runs only during tests. Still to do: password rules when staff register a customer.
- [~] 11 Rate limit login: failed logins are detected and alerted today. Add a real lockout after repeated failures.
- [ ] 12 Bot protection: after the lockout, add a simple check (honeypot or captcha) on login and register.
- [x] 13 Parameterize queries: the Django ORM does this. Check that no raw SQL exists.
- [~] 14 Validate all input: amounts must be positive and within range; dates and text lengths checked by forms or validators.
- [x] 15 Escape user content: Django templates escape by default. Check that |safe and mark_safe are never used on user text.
- [~] 16 Restrict file uploads: KYC and loan documents already check type and contents. Add size limits everywhere and store files safely.
- [n/a] 17 Trim API responses: there is no JSON API; only the manifest and the service worker.

### 14D Headers, sessions, dependencies
- [ ] 9 Secure session cookies: Secure, HttpOnly, SameSite, and a short idle timeout.
- [ ] 18 Security headers: X-Content-Type-Options, X-Frame-Options, Referrer-Policy, a Content-Security-Policy and HSTS.
- [ ] 20 Scan dependencies: pip-audit, and a pinned requirements.txt.

### 14E Deploy
- [ ] Production web server (gunicorn), static files server (WhiteNoise), real database (PostgreSQL), logging, backups, a short deploy guide.

## Backlog
- Phone test through a temporary HTTPS tunnel (test accounts only).
- ATM card expiry date and CVV fields (needs a model change and a migration).
- Card preview on the customer dashboard.
- Decide whether Cards and Services staff may lift an emergency freeze.
- .gitattributes to stop the line-ending warnings.