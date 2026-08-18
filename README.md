# 🏦 Bank Management System

A full-featured Bank Management System built with **Django**, simulating real-world banking operations — multi-branch structure, customer accounts, transactions, loans, and banking services — with role-based access for Customers, Employees, and Admins.

## 🚀 Features

- **Authentication & Roles** — secure login/logout with role-based dashboards (Customer, Employee, Admin)
- **Bank Structure** — multi-branch hierarchy (Bank → Branch → Employee)
- **Customer Management** — registration, KYC status, profile updates, deactivation
- **Account System** — Savings, Current & Fixed Deposit accounts with auto-generated account numbers and balance tracking
- **Transactions** — deposit, withdraw, and transfer with atomic database operations to prevent balance corruption
- **Loan Management** — apply, approve/reject, and track Home, Personal & Car loans
- **Banking Services** — ATM card requests, cheque book requests, account statements, KYC verification
- **Security & Audit** — transaction logs, activity logs, basic fraud protection
- **Reports** — total customers, deposits, loans, and transaction summaries
- **Responsive UI** — Bootstrap/Tailwind-based dashboards with cards and tables

## 🗂️ Project Structure

```
bank_management/
│
├── users/          # Authentication & role management
├── bank/            # Bank & branch data
├── accounts/         # Bank accounts (Savings, Current, FD)
├── transactions/      # Deposits, withdrawals, transfers
├── loans/            # Loan applications & approvals
├── services/          # ATM, cheque book, statements, KYC
└── core/              # Shared utilities
```

## 🧑‍💼 User Roles

| Role | Capabilities |
|------|---------------|
| **Customer** | View accounts & balances, transfer money, view transaction history, apply for loans, request services |
| **Employee** | Register/manage customers, create accounts, approve transactions & loans, view reports |
| **Admin** | Full control over the bank system |

## 🛠️ Tech Stack

- **Backend:** Django (Python)
- **Database:** SQL (via Django ORM)
- **Frontend:** HTML, Bootstrap/Tailwind CSS
- **Architecture:** Multi-app Django project with role-based access control

## 📦 Setup & Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd bank_management

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Apply migrations
python manage.py migrate

# Create a superuser (admin)
python manage.py createsuperuser

# Run the development server
python manage.py runserver
```

## 📌 Project Status

This project is under active development, being built out phase by phase — from core authentication and bank structure through accounts, transactions, loans, services, security/audit, reporting, and a production-ready release.

## 📄 License

Add your license of choice here (e.g., MIT).
