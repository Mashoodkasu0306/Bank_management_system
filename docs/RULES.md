# Rules

## How we work (you and Claude)
1. Explain everything in simple words.
2. Every code change comes with: file path, action (ADD or REPLACE), full code, apply steps, verify steps and test steps.
3. Edit files with scripted writes: [System.IO.File]::WriteAllText(...) as UTF-8 without BOM. For an existing file use a small Python script that checks each spot is found exactly once and keeps the line endings. Do not trust the editor to save (it has saved empty files).
4. Always look at the real file (Get-Content) before patching it. Never assume it matches an earlier draft.
5. After a change: py_compile, python manage.py check, template compile check, python manage.py test, git status. Paste the output and wait for the prompt before the next command.
6. Test in the browser before pushing. Run the full test suite before every commit.
7. Never edit a test only to make it pass. A failing test means the code or the wording changed; decide which one is right.
8. Commit small with a clear message. Never commit secrets, db.sqlite3, uploaded files (media/) or B_env/.
9. Run commands from bank_management/ (the folder with manage.py), not from bank_management/bank_management/.
10. Pasted terminal output wraps long lines and can drop spaces. Odd missing spaces in a paste are not always in the file.

## Code rules
- Money is Decimal, never float. Balance changes run inside transaction.atomic() with select_for_update().
- Check the role on the server in every view. A customer may only see or change their own records: any query that uses an id from the URL must also filter by the logged-in customer.
- Staff actions and customer actions write an audit entry (log_action).
- Use local imports where a top-level import would be circular.
- Check the model before using a field name. Keep existing field and URL names.
- Show messages with Django messages; base.html displays them.

## Template rules
- Every {% tag %} and {{ variable }} stays on one line.
- Write the rupee sign as &#8377; and use HTML entities for special characters.
- Progress bars keep the exact text width:{{ value }}% (no space); tests look for it.
- Reuse the classes in DESIGN.md before adding new CSS.

## Security rules
- Secrets (SECRET_KEY, passwords, keys) live in environment variables or a git-ignored .env file.
- Never store a full card number or CVV. Store only the last 4 digits and the expiry.
- Uploaded files are private: check type and contents, and serve them only through a view that checks the logged-in user.
- The service worker never caches pages, balances, documents or anything under /media/.
- Turn DEBUG off and set ALLOWED_HOSTS before any public deploy.