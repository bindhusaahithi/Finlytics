# Finlytics

Finlytics is a mobile-first personal finance dashboard built with Flask and MySQL. It helps users track income, expenses, budgets, debts, and repayment progress in a colorful app-style interface designed for both portfolio presentation and real-world usability.

## Highlights

- User registration, login, logout, and session-based authentication
- Secure password hashing with Werkzeug
- Multi-currency support including `USD`, `INR`, `GBP`, `EUR`, `JPY`, `CAD`, and `AUD`
- Income and expense tracking with edit and delete actions
- Monthly and all-time dashboard filtering
- Auto-calculated income, expenses, and balance summaries
- Chart.js analytics for income vs expenses and expense categories
- Monthly budgets with progress tracking and delete support
- Debt tracker with payment history and automatic payment transaction logging
- CSV export for transactions
- Success and error flash messages
- Privacy policy and in-app delete account flow
- Mobile-style UI with manifest and service worker support

## Tech Stack

- Python
- Flask
- MySQL
- HTML
- CSS
- JavaScript
- Chart.js
- Gunicorn

## Main Screens

- Register
- Login
- Dashboard
- Add Transaction
- Set Monthly Budget
- Debt Tracker
- Record Debt Payment
- Privacy Policy

## Project Structure

```text
Finlytics/
├── app.py
├── database.py
├── database.sql
├── requirements.txt
├── Procfile
├── render.yaml
├── static/
│   ├── app-icon.svg
│   ├── app.js
│   ├── dashboard.css
│   ├── manifest.json
│   ├── service-worker.js
│   └── style.css
└── templates/
    ├── add_debt.html
    ├── add_transaction.html
    ├── budget.html
    ├── dashboard.html
    ├── debt_payment.html
    ├── debts.html
    ├── edit_debt.html
    ├── login.html
    ├── privacy_policy.html
    └── register.html
```

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/bindhusaahithi/Finlytics.git
cd Finlytics
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file or export variables in your shell using the values from `.env.example`.

Supported configuration:

- `FINLYTICS_SECRET_KEY`
- `DATABASE_URL`

Or individual database variables:

- `DB_HOST`
- `DB_PORT`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`

### 5. Create the database schema

Run the SQL inside [`database.sql`](database.sql) in MySQL Workbench or your MySQL client.

### 6. Start the Flask app

```bash
python3 app.py
```

Then open:

```text
http://127.0.0.1:5001
```

## Deployment

This repository includes:

- `Procfile` for Gunicorn
- `render.yaml` for Render deployment
- `.env.example` for environment setup

To deploy, connect the repository to Render, provide your MySQL connection details, and set the required environment variables.

## Why This Project Stands Out

Finlytics is a strong portfolio project for:

- Data Analyst roles
- Python and Flask roles
- SQL and database-focused roles
- Dashboard and analytics projects
- Product-oriented full-stack portfolios

It demonstrates backend logic, relational database design, analytics presentation, CRUD workflows, multi-currency handling, and mobile-focused interface design in one project.

## Future Improvements

- Public deployment with HTTPS
- Add Home Screen install flow on iPhone
- Convert to an iOS wrapper using Capacitor
- TestFlight testing
- App Store preparation

## Author

Built by Bindhu Saahithi.
