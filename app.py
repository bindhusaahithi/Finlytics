import calendar
import csv
import os
import re
from decimal import Decimal, InvalidOperation
from datetime import date
from io import StringIO

from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from mysql.connector import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_connection


app = Flask(__name__)

# For development. Later, store this securely before deployment.
app.secret_key = os.environ.get(
    "FINLYTICS_SECRET_KEY",
    "finlytics-development-secret-key"
)
SCHEMA_READY = False
ALLOWED_CURRENCIES = {
    "USD",
    "INR",
    "GBP",
    "EUR",
    "JPY",
    "CAD",
    "AUD",
}
ALLOWED_TRANSACTION_TYPES = {"income", "expense"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def build_dashboard_redirect(month_value=None):
    if month_value == "all":
        return redirect(url_for("dashboard", month="all"))

    if month_value:
        return redirect(url_for("dashboard", month=month_value))

    return redirect(url_for("dashboard"))


def fetch_categories(cursor):
    cursor.execute(
        """
        SELECT id, name
        FROM categories
        ORDER BY name
        """
    )

    return cursor.fetchall()


def normalize_text(value):
    return (value or "").strip()


def is_valid_email(email):
    return bool(EMAIL_PATTERN.match(email or ""))


def validate_password(password):
    if len(password or "") < 8:
        return "Password must be at least 8 characters long."

    return None


def password_matches(stored_password, provided_password):
    try:
        return check_password_hash(
            stored_password,
            provided_password
        )
    except (ValueError, TypeError):
        return False


def parse_positive_amount(raw_value, field_label):
    try:
        parsed_value = Decimal(str(raw_value))
    except (InvalidOperation, TypeError):
        return None, f"{field_label} must be a valid number."

    if parsed_value <= 0:
        return None, f"{field_label} must be greater than 0."

    return parsed_value, None


def validate_iso_date(raw_value, field_label):
    try:
        return date.fromisoformat(raw_value), None
    except (TypeError, ValueError):
        return None, f"{field_label} must be a valid date."


def build_transaction_form_data(form_data):
    return {
        "amount": normalize_text(form_data.get("amount")),
        "currency": normalize_text(form_data.get("currency")) or "USD",
        "type": normalize_text(form_data.get("type")),
        "category_id": (
            int(form_data.get("category_id"))
            if normalize_text(form_data.get("category_id")).isdigit()
            else None
        ),
        "description": normalize_text(form_data.get("description")),
        "transaction_date": normalize_text(
            form_data.get("transaction_date")
        )
    }


def build_budget_form_data(form_data, fallback_month):
    return {
        "budget_month": (
            normalize_text(form_data.get("budget_month"))
            or fallback_month
        ),
        "currency": normalize_text(form_data.get("currency")) or "USD",
        "category_id": (
            int(form_data.get("category_id"))
            if normalize_text(form_data.get("category_id")).isdigit()
            else None
        ),
        "monthly_limit": normalize_text(
            form_data.get("monthly_limit")
        )
    }


def build_debt_form_data(form_data):
    return {
        "debt_name": normalize_text(form_data.get("debt_name")),
        "lender_name": normalize_text(
            form_data.get("lender_name")
        ),
        "country": normalize_text(form_data.get("country")),
        "currency": normalize_text(form_data.get("currency")) or "USD",
        "original_amount": normalize_text(
            form_data.get("original_amount")
        ),
        "interest_rate": normalize_text(
            form_data.get("interest_rate")
        ),
        "due_date": normalize_text(form_data.get("due_date")),
        "notes": normalize_text(form_data.get("notes"))
    }


def build_debt_payment_form_data(form_data, fallback_date):
    return {
        "amount": normalize_text(form_data.get("amount")),
        "payment_date": (
            normalize_text(form_data.get("payment_date"))
            or fallback_date
        ),
        "notes": normalize_text(form_data.get("notes"))
    }


def get_month_context(month_value=None):
    normalized_month = (month_value or "").strip()

    if normalized_month and normalized_month != "all":
        year_number, month_number = map(
            int,
            normalized_month.split("-")
        )

    else:
        today = date.today()
        year_number = today.year
        month_number = today.month
        normalized_month = f"{year_number:04d}-{month_number:02d}"

    return {
        "value": normalized_month,
        "year": year_number,
        "month_number": month_number,
        "label": f"{calendar.month_name[month_number]} {year_number}",
        "first_day": f"{normalized_month}-01"
    }


def parse_optional_rate(raw_value):
    raw_text = normalize_text(raw_value)

    if not raw_text:
        return None, None

    try:
        parsed_value = Decimal(raw_text)
    except (InvalidOperation, TypeError):
        return None, "Interest rate must be a valid number."

    if parsed_value < 0:
        return None, "Interest rate cannot be negative."

    return parsed_value, None


def format_display_date(raw_value, pattern):
    if hasattr(raw_value, "strftime"):
        return raw_value.strftime(pattern)

    if raw_value in (None, ""):
        return ""

    return str(raw_value)


def get_debt_payment_category_id(cursor):
    cursor.execute(
        """
        SELECT id
        FROM categories
        WHERE name = 'Debt Payment'
        LIMIT 1
        """
    )

    category = cursor.fetchone()

    if category:
        return category["id"] if isinstance(category, dict) else category[0]

    cursor.execute(
        """
        INSERT INTO categories (name)
        VALUES ('Debt Payment')
        """
    )

    return cursor.lastrowid


def fetch_debt_items(cursor, user_id):
    cursor.execute(
        """
        SELECT
            d.id,
            d.debt_name,
            d.lender_name,
            d.country,
            d.currency,
            d.original_amount,
            d.interest_rate,
            d.due_date,
            d.notes,
            COALESCE(SUM(dp.amount), 0) AS paid_amount
        FROM debts AS d
        LEFT JOIN debt_payments AS dp
            ON dp.debt_id = d.id
        WHERE d.user_id = %s
        GROUP BY
            d.id,
            d.debt_name,
            d.lender_name,
            d.country,
            d.currency,
            d.original_amount,
            d.interest_rate,
            d.due_date,
            d.notes
        ORDER BY
            d.currency,
            CASE WHEN d.due_date IS NULL THEN 1 ELSE 0 END,
            d.due_date,
            d.id DESC
        """,
        (user_id,)
    )

    debt_rows = cursor.fetchall()

    cursor.execute(
        """
        SELECT
            dp.id,
            dp.debt_id,
            dp.amount,
            dp.payment_date,
            dp.notes
        FROM debt_payments AS dp
        INNER JOIN debts AS d
            ON d.id = dp.debt_id
        WHERE d.user_id = %s
        ORDER BY dp.payment_date DESC, dp.id DESC
        """,
        (user_id,)
    )

    payment_rows = cursor.fetchall()
    payments_by_debt = {}

    for payment in payment_rows:
        debt_id = payment["debt_id"]
        payments_by_debt.setdefault(debt_id, []).append(
            {
                "id": payment["id"],
                "amount": float(payment["amount"] or 0),
                "payment_date": payment["payment_date"],
                "formatted_date": format_display_date(
                    payment["payment_date"],
                    "%b %d, %Y"
                ),
                "notes": payment["notes"] or ""
            }
        )

    debt_items = []

    for row in debt_rows:
        original_amount = float(row["original_amount"] or 0)
        paid_amount = float(row["paid_amount"] or 0)
        remaining_amount = max(original_amount - paid_amount, 0)
        progress_percentage = (
            (paid_amount / original_amount) * 100
            if original_amount > 0
            else 0
        )
        if remaining_amount <= 0.005:
            status = "healthy"
            status_label = "Cleared"
        else:
            status = "healthy"
            status_label = "Active"

        debt_items.append(
            {
                "id": row["id"],
                "debt_name": row["debt_name"],
                "lender_name": row["lender_name"] or "",
                "country": row["country"] or "",
                "currency": row["currency"],
                "original_amount": original_amount,
                "paid_amount": paid_amount,
                "remaining_amount": remaining_amount,
                "interest_rate": (
                    float(row["interest_rate"])
                    if row["interest_rate"] is not None
                    else None
                ),
                "notes": row["notes"] or "",
                "progress_percentage": progress_percentage,
                "progress_width": min(progress_percentage, 100),
                "status": status,
                "status_label": status_label,
                "payments": payments_by_debt.get(row["id"], [])[:5]
            }
        )

    return debt_items


def build_debt_summaries(debt_items):
    grouped = {}

    for debt in debt_items:
        currency = debt["currency"]

        if currency not in grouped:
            grouped[currency] = {
                "currency": currency,
                "total_debt": 0,
                "total_paid": 0,
                "total_remaining": 0
            }

        grouped[currency]["total_debt"] += debt["original_amount"]
        grouped[currency]["total_paid"] += debt["paid_amount"]
        grouped[currency]["total_remaining"] += debt["remaining_amount"]

    return [
        grouped[currency]
        for currency in sorted(grouped.keys())
    ]


def ensure_database_schema():
    global SCHEMA_READY

    if SCHEMA_READY:
        return

    conn = get_connection()
    cursor = conn.cursor(buffered=True)

    try:
        cursor.execute(
            "SHOW COLUMNS FROM transactions LIKE 'currency'"
        )

        if cursor.fetchone() is None:
            cursor.execute(
                """
                ALTER TABLE transactions
                ADD COLUMN currency VARCHAR(10) NOT NULL
                DEFAULT 'USD'
                """
            )

        cursor.execute(
            "SHOW COLUMNS FROM budgets LIKE 'currency'"
        )

        if cursor.fetchone() is None:
            cursor.execute(
                """
                ALTER TABLE budgets
                ADD COLUMN currency VARCHAR(10) NOT NULL
                DEFAULT 'USD'
                """
            )

        cursor.execute(
            "SHOW COLUMNS FROM budgets LIKE 'budget_month'"
        )

        if cursor.fetchone() is None:
            cursor.execute(
                """
                ALTER TABLE budgets
                ADD COLUMN budget_month DATE NULL
                """
            )

            cursor.execute(
                """
                UPDATE budgets
                SET budget_month = DATE_FORMAT(
                    CURDATE(),
                    '%Y-%m-01'
                )
                WHERE budget_month IS NULL
                """
            )

            cursor.execute(
                """
                ALTER TABLE budgets
                MODIFY COLUMN budget_month DATE NOT NULL
                """
            )

        cursor.execute(
            """
            SHOW INDEX FROM budgets
            WHERE Key_name = 'unique_budget_per_month'
            """
        )

        if cursor.fetchone() is None:
            cursor.execute(
                """
                ALTER TABLE budgets
                ADD CONSTRAINT unique_budget_per_month
                UNIQUE (
                    user_id,
                    category_id,
                    currency,
                    budget_month
                )
                """
            )

        conn.commit()
        SCHEMA_READY = True

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def fetch_budget_items(cursor, user_id, year_number, month_number):
    cursor.execute(
        """
        SELECT
            b.id,
            b.category_id,
            c.name AS category_name,
            b.currency,
            b.monthly_limit,

            COALESCE(
                SUM(
                    CASE
                        WHEN t.type = 'expense' THEN t.amount
                        ELSE 0
                    END
                ),
                0
            ) AS spent_amount

        FROM budgets AS b

        INNER JOIN categories AS c
            ON c.id = b.category_id

        LEFT JOIN transactions AS t
            ON t.user_id = b.user_id
           AND t.category_id = b.category_id
           AND t.currency = b.currency
           AND t.type = 'expense'
           AND YEAR(t.transaction_date) = %s
           AND MONTH(t.transaction_date) = %s

        WHERE b.user_id = %s
          AND YEAR(b.budget_month) = %s
          AND MONTH(b.budget_month) = %s

        GROUP BY
            b.id,
            b.category_id,
            c.name,
            b.currency,
            b.monthly_limit

        ORDER BY
            c.name,
            b.currency
        """,
        (
            year_number,
            month_number,
            user_id,
            year_number,
            month_number
        )
    )

    budget_rows = cursor.fetchall()
    budget_items = []

    for row in budget_rows:
        monthly_limit = float(row["monthly_limit"] or 0)
        spent_amount = float(row["spent_amount"] or 0)
        remaining_amount = max(monthly_limit - spent_amount, 0)
        overspent_amount = max(spent_amount - monthly_limit, 0)

        if monthly_limit > 0:
            progress_percentage = (
                spent_amount / monthly_limit
            ) * 100
        else:
            progress_percentage = 0

        if spent_amount >= monthly_limit and monthly_limit > 0:
            status = "danger"
            status_label = "Budget reached"
            status_message = (
                f"{row['currency']} "
                f"{overspent_amount:.2f} over budget"
                if overspent_amount > 0
                else "Limit reached exactly"
            )
        elif monthly_limit > 0 and progress_percentage >= 80:
            status = "warning"
            status_label = "Near limit"
            status_message = (
                f"{row['currency']} "
                f"{remaining_amount:.2f} left this month"
            )
        else:
            status = "healthy"
            status_label = "On track"
            status_message = (
                f"{row['currency']} "
                f"{remaining_amount:.2f} remaining"
            )

        budget_items.append(
            {
                "id": row["id"],
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "currency": row["currency"],
                "monthly_limit": monthly_limit,
                "spent_amount": spent_amount,
                "remaining_amount": remaining_amount,
                "overspent_amount": overspent_amount,
                "progress_percentage": progress_percentage,
                "progress_width": min(progress_percentage, 100),
                "status": status,
                "status_label": status_label,
                "status_message": status_message
            }
        )

    return budget_items


@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(
        app.static_folder,
        "service-worker.js",
        mimetype="application/javascript"
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = normalize_text(request.form.get("name"))
        email = normalize_text(
            request.form.get("email")
        ).lower()
        password = request.form.get("password", "")

        if not name:
            flash("Please enter your full name.", "error")
            return render_template("register.html")

        if not is_valid_email(email):
            flash("Please enter a valid email address.", "error")
            return render_template("register.html")

        password_error = validate_password(password)

        if password_error:
            flash(password_error, "error")
            return render_template("register.html")

        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO users (name, email, password)
                VALUES (%s, %s, %s)
                """,
                (
                    name,
                    email,
                    generate_password_hash(password)
                )
            )

            conn.commit()
            flash(
                "Account created successfully. You can log in now.",
                "success"
            )
            return redirect(url_for("login"))

        except IntegrityError:
            conn.rollback()
            flash(
                "This email is already registered. Please log in.",
                "error"
            )

        finally:
            cursor.close()
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = normalize_text(
            request.form.get("email")
        ).lower()
        password = request.form.get("password", "")

        if not is_valid_email(email):
            flash("Please enter a valid email address.", "error")
            return render_template("login.html")

        if not password:
            flash("Please enter your password.", "error")
            return render_template("login.html")

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute(
                """
                SELECT id, name, email, password
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()

            if user and password_matches(
                user["password"],
                password
            ):
                authenticated_user = user
            elif user and user["password"] == password:
                cursor.close()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE users
                    SET password = %s
                    WHERE id = %s
                    """,
                    (
                        generate_password_hash(password),
                        user["id"]
                    )
                )
                conn.commit()
                authenticated_user = user
            else:
                authenticated_user = None

        finally:
            cursor.close()
            conn.close()

        if authenticated_user:
            session.clear()
            session["user_id"] = authenticated_user["id"]
            session["user_name"] = authenticated_user["name"]
            flash(
                f"Welcome back, {authenticated_user['name']}!",
                "success"
            )

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    user_id = session["user_id"]

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Get every month that contains transactions.
        cursor.execute(
            """
            SELECT DISTINCT
                YEAR(transaction_date) AS year_number,
                MONTH(transaction_date) AS month_number
            FROM transactions
            WHERE user_id = %s
            ORDER BY year_number DESC, month_number DESC
            """,
            (user_id,)
        )

        month_rows = cursor.fetchall()

        month_options = []

        for row in month_rows:
            year_number = int(row["year_number"])
            month_number = int(row["month_number"])

            month_options.append(
                {
                    "value": f"{year_number:04d}-{month_number:02d}",
                    "label": (
                        f"{calendar.month_name[month_number]} "
                        f"{year_number}"
                    )
                }
            )

        valid_months = {
            option["value"] for option in month_options
        }

        selected_month = request.args.get("month", "").strip()

        # Default to the newest month.
        if not selected_month:
            if month_options:
                selected_month = month_options[0]["value"]
            else:
                selected_month = "all"

        # Protect against an invalid month value.
        if selected_month != "all" and selected_month not in valid_months:
            if month_options:
                selected_month = month_options[0]["value"]
            else:
                selected_month = "all"

        if selected_month == "all":
            selected_period_label = "All Time"
            budget_items = []
            budget_month_value = get_month_context()["value"]

            summary_date_condition = ""
            aliased_date_condition = ""

            query_parameters = (user_id,)

        else:
            selected_year, selected_month_number = map(
                int,
                selected_month.split("-")
            )

            selected_period_label = (
                f"{calendar.month_name[selected_month_number]} "
                f"{selected_year}"
            )

            summary_date_condition = """
                AND YEAR(transaction_date) = %s
                AND MONTH(transaction_date) = %s
            """

            aliased_date_condition = """
                AND YEAR(t.transaction_date) = %s
                AND MONTH(t.transaction_date) = %s
            """

            query_parameters = (
                user_id,
                selected_year,
                selected_month_number
            )

            budget_items = fetch_budget_items(
                cursor,
                user_id,
                selected_year,
                selected_month_number
            )

            budget_month_value = selected_month

        # Calculate income, expenses and balance by currency.
        summary_query = f"""
            SELECT
                currency,

                COALESCE(
                    SUM(
                        CASE
                            WHEN type = 'income' THEN amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS total_income,

                COALESCE(
                    SUM(
                        CASE
                            WHEN type = 'expense' THEN amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS total_expenses

            FROM transactions

            WHERE user_id = %s
            {summary_date_condition}

            GROUP BY currency
            ORDER BY currency
        """

        cursor.execute(summary_query, query_parameters)

        summary_rows = cursor.fetchall()
        summaries = []

        for row in summary_rows:
            total_income = float(row["total_income"] or 0)
            total_expenses = float(row["total_expenses"] or 0)

            summaries.append(
                {
                    "currency": row["currency"],
                    "total_income": total_income,
                    "total_expenses": total_expenses,
                    "balance": total_income - total_expenses
                }
            )

        # Get expense totals by category for the doughnut chart.
        category_query = f"""
            SELECT
                t.currency,
                c.name AS category_name,
                SUM(t.amount) AS category_total

            FROM transactions AS t

            INNER JOIN categories AS c
                ON t.category_id = c.id

            WHERE t.user_id = %s
              AND t.type = 'expense'
              {aliased_date_condition}

            GROUP BY
                t.currency,
                c.id,
                c.name

            ORDER BY
                t.currency,
                category_total DESC
        """

        cursor.execute(category_query, query_parameters)

        category_rows = cursor.fetchall()
        category_data = {}

        for row in category_rows:
            currency = row["currency"]

            if currency not in category_data:
                category_data[currency] = {
                    "labels": [],
                    "values": []
                }

            category_data[currency]["labels"].append(
                row["category_name"]
            )

            category_data[currency]["values"].append(
                float(row["category_total"] or 0)
            )

        # Prepare safe JSON data for Chart.js.
        chart_data = []

        for summary in summaries:
            currency = summary["currency"]

            expense_information = category_data.get(
                currency,
                {
                    "labels": [],
                    "values": []
                }
            )

            chart_data.append(
                {
                    "currency": currency,
                    "income": summary["total_income"],
                    "expenses": summary["total_expenses"],
                    "expense_labels": expense_information["labels"],
                    "expense_values": expense_information["values"],
                    "has_expenses": bool(
                        expense_information["values"]
                    )
                }
            )

        # Get recent transactions for the chosen period.
        transactions_query = f"""
            SELECT
                t.id,
                t.transaction_date,
                c.name AS category_name,
                t.description,
                t.type,
                t.amount,
                t.currency

            FROM transactions AS t

            INNER JOIN categories AS c
                ON t.category_id = c.id

            WHERE t.user_id = %s
            {aliased_date_condition}

            ORDER BY
                t.transaction_date DESC,
                t.id DESC

            LIMIT 20
        """

        cursor.execute(transactions_query, query_parameters)

        recent_transactions = cursor.fetchall()

        for transaction in recent_transactions:
            transaction_date = transaction["transaction_date"]

            if hasattr(transaction_date, "strftime"):
                transaction["formatted_date"] = (
                    transaction_date.strftime("%b %d, %Y")
                )
            else:
                transaction["formatted_date"] = str(
                    transaction_date
                )

            transaction["amount"] = float(
                transaction["amount"] or 0
            )

        debt_items = fetch_debt_items(cursor, user_id)
        debt_summaries = build_debt_summaries(debt_items)

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "dashboard.html",
        user_name=session["user_name"],
        summaries=summaries,
        recent_transactions=recent_transactions,
        month_options=month_options,
        selected_month=selected_month,
        selected_period_label=selected_period_label,
        chart_data=chart_data
        ,
        budget_items=budget_items,
        budget_month_value=budget_month_value,
        debt_items=debt_items[:4],
        debt_summaries=debt_summaries
    )


@app.route("/transactions/export")
def export_transactions_csv():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    selected_month = normalize_text(request.args.get("month"))
    query_parameters = [session["user_id"]]
    date_condition = ""
    month_suffix = "all-time"

    if selected_month and selected_month != "all":
        try:
            selected_year, selected_month_number = map(
                int,
                selected_month.split("-")
            )
        except ValueError:
            flash(
                "Please choose a valid month before exporting.",
                "error"
            )
            return redirect(url_for("dashboard"))
        date_condition = """
            AND YEAR(t.transaction_date) = %s
            AND MONTH(t.transaction_date) = %s
        """
        query_parameters.extend(
            [selected_year, selected_month_number]
        )
        month_suffix = selected_month

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            f"""
            SELECT
                t.transaction_date,
                c.name AS category_name,
                t.description,
                t.type,
                t.currency,
                t.amount
            FROM transactions AS t
            INNER JOIN categories AS c
                ON t.category_id = c.id
            WHERE t.user_id = %s
            {date_condition}
            ORDER BY
                t.transaction_date DESC,
                t.id DESC
            """,
            tuple(query_parameters)
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    csv_output = StringIO()
    csv_writer = csv.writer(csv_output)
    csv_writer.writerow(
        [
            "Date",
            "Category",
            "Description",
            "Type",
            "Currency",
            "Amount"
        ]
    )

    for row in rows:
        transaction_date = row["transaction_date"]
        csv_writer.writerow(
            [
                (
                    transaction_date.strftime("%Y-%m-%d")
                    if hasattr(transaction_date, "strftime")
                    else str(transaction_date)
                ),
                row["category_name"],
                row["description"] or "",
                row["type"],
                row["currency"],
                f"{float(row['amount'] or 0):.2f}"
            ]
        )

    return Response(
        csv_output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                "attachment; "
                f"filename=finlytics-transactions-{month_suffix}.csv"
            )
        }
    )


@app.route("/add-transaction", methods=["GET", "POST"])
def add_transaction():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    current_month = request.values.get("month", "").strip()

    try:
        if request.method == "POST":
            form_transaction = build_transaction_form_data(
                request.form
            )
            categories = fetch_categories(cursor)

            amount, amount_error = parse_positive_amount(
                form_transaction["amount"],
                "Amount"
            )
            transaction_date_value, date_error = validate_iso_date(
                form_transaction["transaction_date"],
                "Transaction date"
            )

            if amount_error:
                flash(amount_error, "error")
            elif (
                form_transaction["currency"]
                not in ALLOWED_CURRENCIES
            ):
                flash("Please select a valid currency.", "error")
            elif (
                form_transaction["type"]
                not in ALLOWED_TRANSACTION_TYPES
            ):
                flash(
                    "Please select a valid transaction type.",
                    "error"
                )
            elif form_transaction["category_id"] is None:
                flash("Please select a category.", "error")
            elif date_error:
                flash(date_error, "error")
            else:
                cursor.execute(
                    """
                    INSERT INTO transactions
                    (
                        user_id,
                        category_id,
                        amount,
                        type,
                        description,
                        transaction_date,
                        currency
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session["user_id"],
                        form_transaction["category_id"],
                        str(amount),
                        form_transaction["type"],
                        form_transaction["description"] or None,
                        transaction_date_value.isoformat(),
                        form_transaction["currency"]
                    )
                )

                conn.commit()
                flash(
                    "Transaction saved successfully.",
                    "success"
                )

                return build_dashboard_redirect(
                    transaction_date_value.strftime("%Y-%m")
                )

            return render_template(
                "add_transaction.html",
                categories=categories,
                transaction=form_transaction,
                form_action=url_for("add_transaction"),
                page_mode="create",
                submit_label="Save Transaction",
                intro_label="New Entry",
                page_title="Add Transaction",
                page_description=(
                    "Add income or expenses to keep your dashboard updated."
                ),
                detail_text="Fill in the details below.",
                side_title="Keep your finances organized",
                side_note=(
                    "Save it fast, then review trends from your home-screen "
                    "dashboard."
                ),
                current_month=current_month
            )

        categories = fetch_categories(cursor)

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "add_transaction.html",
        categories=categories,
        transaction=None,
        form_action=url_for("add_transaction"),
        page_mode="create",
        submit_label="Save Transaction",
        intro_label="New Entry",
        page_title="Add Transaction",
        page_description=(
            "Add income or expenses to keep your dashboard updated."
        ),
        detail_text="Fill in the details below.",
        side_title="Keep your finances organized",
        side_note=(
            "Save it fast, then review trends from your home-screen "
            "dashboard."
        ),
        current_month=current_month
    )


@app.route("/transactions/<int:transaction_id>/edit", methods=["GET", "POST"])
def edit_transaction(transaction_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    selected_month = request.values.get("month", "").strip()

    try:
        cursor.execute(
            """
            SELECT
                id,
                category_id,
                amount,
                type,
                description,
                transaction_date,
                currency
            FROM transactions
            WHERE id = %s
              AND user_id = %s
            """,
            (transaction_id, session["user_id"])
        )

        transaction = cursor.fetchone()

        if not transaction:
            flash("Transaction not found.", "error")
            return build_dashboard_redirect(
                selected_month
            )

        if request.method == "POST":
            form_transaction = build_transaction_form_data(
                request.form
            )
            categories = fetch_categories(cursor)

            amount, amount_error = parse_positive_amount(
                form_transaction["amount"],
                "Amount"
            )
            transaction_date_value, date_error = validate_iso_date(
                form_transaction["transaction_date"],
                "Transaction date"
            )

            if amount_error:
                flash(amount_error, "error")
            elif (
                form_transaction["currency"]
                not in ALLOWED_CURRENCIES
            ):
                flash("Please select a valid currency.", "error")
            elif (
                form_transaction["type"]
                not in ALLOWED_TRANSACTION_TYPES
            ):
                flash(
                    "Please select a valid transaction type.",
                    "error"
                )
            elif form_transaction["category_id"] is None:
                flash("Please select a category.", "error")
            elif date_error:
                flash(date_error, "error")
            else:
                cursor.execute(
                    """
                    UPDATE transactions
                    SET
                        category_id = %s,
                        amount = %s,
                        type = %s,
                        description = %s,
                        transaction_date = %s,
                        currency = %s
                    WHERE id = %s
                      AND user_id = %s
                    """,
                    (
                        form_transaction["category_id"],
                        str(amount),
                        form_transaction["type"],
                        form_transaction["description"] or None,
                        transaction_date_value.isoformat(),
                        form_transaction["currency"],
                        transaction_id,
                        session["user_id"]
                    )
                )

                conn.commit()
                flash(
                    "Transaction updated successfully.",
                    "success"
                )

                return build_dashboard_redirect(
                    transaction_date_value.strftime("%Y-%m")
                )

            transaction = form_transaction

        categories = fetch_categories(cursor)

        transaction["amount"] = float(transaction["amount"] or 0)

        transaction_date = transaction["transaction_date"]

        if hasattr(transaction_date, "strftime"):
            transaction["transaction_date"] = (
                transaction_date.strftime("%Y-%m-%d")
            )
        else:
            transaction["transaction_date"] = str(transaction_date)

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "add_transaction.html",
        categories=categories,
        transaction=transaction,
        form_action=url_for(
            "edit_transaction",
            transaction_id=transaction_id
        ),
        page_mode="edit",
        submit_label="Update Transaction",
        intro_label="Update Entry",
        page_title="Edit Transaction",
        page_description=(
            "Correct an amount, category, date, or description and the "
            "dashboard will refresh automatically."
        ),
        detail_text="Update the details below.",
        side_title="Keep every report accurate",
        side_note=(
            "Fixing a transaction immediately updates your summaries and "
            "charts."
        ),
        current_month=selected_month
    )


@app.route("/transactions/<int:transaction_id>/delete", methods=["POST"])
def delete_transaction(transaction_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT transaction_date
            FROM transactions
            WHERE id = %s
              AND user_id = %s
            """,
            (transaction_id, session["user_id"])
        )

        transaction = cursor.fetchone()

        if not transaction:
            flash("Transaction not found.", "error")
            return build_dashboard_redirect(
                request.form.get("month", "").strip()
            )

        cursor.execute(
            """
            DELETE FROM transactions
            WHERE id = %s
              AND user_id = %s
            """,
            (transaction_id, session["user_id"])
        )

        conn.commit()

        transaction_date = transaction["transaction_date"]

        if hasattr(transaction_date, "strftime"):
            fallback_month = transaction_date.strftime("%Y-%m")
        else:
            fallback_month = str(transaction_date)[:7]

        selected_month = request.form.get("month", "").strip()
        flash("Transaction deleted successfully.", "success")

        return build_dashboard_redirect(selected_month or fallback_month)

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


@app.route("/budget", methods=["GET", "POST"])
def budget():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    selected_month = (
        request.values.get("month", "").strip()
    )

    if selected_month == "all":
        selected_month = ""

    month_context = get_month_context(selected_month)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    budget_form = build_budget_form_data(
        request.values,
        month_context["value"]
    )

    try:
        categories = fetch_categories(cursor)

        if request.method == "POST":
            monthly_limit, limit_error = parse_positive_amount(
                budget_form["monthly_limit"],
                "Monthly budget"
            )
            budget_date_value, month_error = validate_iso_date(
                f"{budget_form['budget_month']}-01",
                "Budget month"
            )

            if (
                budget_form["currency"]
                not in ALLOWED_CURRENCIES
            ):
                flash("Please select a valid currency.", "error")
            elif budget_form["category_id"] is None:
                flash("Please select a category.", "error")
            elif limit_error:
                flash(limit_error, "error")
            elif month_error:
                flash("Please choose a valid budget month.", "error")
            else:
                cursor.execute(
                    """
                    INSERT INTO budgets
                    (
                        user_id,
                        category_id,
                        monthly_limit,
                        currency,
                        budget_month
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        monthly_limit = VALUES(monthly_limit)
                    """,
                    (
                        session["user_id"],
                        budget_form["category_id"],
                        str(monthly_limit),
                        budget_form["currency"],
                        budget_date_value.isoformat()
                    )
                )

                conn.commit()
                flash(
                    "Budget saved successfully.",
                    "success"
                )

                return redirect(
                    url_for(
                        "budget",
                        month=budget_form["budget_month"]
                    )
                )

        budget_items = fetch_budget_items(
            cursor,
            session["user_id"],
            month_context["year"],
            month_context["month_number"]
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

    return render_template(
        "budget.html",
        categories=categories,
        budget_items=budget_items,
        selected_month=month_context["value"],
        selected_period_label=month_context["label"],
        budget_form=budget_form
    )


@app.route("/budgets/<int:budget_id>/delete", methods=["POST"])
def delete_budget(budget_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    selected_month = request.form.get("month", "").strip()

    if selected_month == "all":
        selected_month = ""

    month_context = get_month_context(selected_month)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            DELETE FROM budgets
            WHERE id = %s
              AND user_id = %s
            """,
            (budget_id, session["user_id"])
        )

        if cursor.rowcount == 0:
            flash("Budget not found.", "error")
        else:
            flash("Budget deleted successfully.", "success")

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

    return redirect(
        url_for("budget", month=month_context["value"])
    )


@app.route("/debts")
def debts():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        debt_items = fetch_debt_items(cursor, session["user_id"])
        debt_summaries = build_debt_summaries(debt_items)
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "debts.html",
        user_name=session["user_name"],
        debt_items=debt_items,
        debt_summaries=debt_summaries
    )


@app.route("/add-debt", methods=["GET", "POST"])
def add_debt():
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    debt_form = build_debt_form_data(request.form)
    today_value = date.today().isoformat()

    if request.method == "POST":
        original_amount, amount_error = parse_positive_amount(
            debt_form["original_amount"],
            "Original amount"
        )
        interest_rate, rate_error = parse_optional_rate(
            debt_form["interest_rate"]
        )

        if not debt_form["debt_name"]:
            flash("Please enter a debt name.", "error")
        elif debt_form["currency"] not in ALLOWED_CURRENCIES:
            flash("Please select a valid currency.", "error")
        elif amount_error:
            flash(amount_error, "error")
        elif rate_error:
            flash(rate_error, "error")
        elif (
            debt_form["due_date"]
            and validate_iso_date(
                debt_form["due_date"],
                "Due date"
            )[1]
        ):
            flash("Please choose a valid due date.", "error")
        else:
            due_date_value = (
                validate_iso_date(
                    debt_form["due_date"],
                    "Due date"
                )[0]
                if debt_form["due_date"]
                else None
            )

            conn = get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    """
                    INSERT INTO debts
                    (
                        user_id,
                        debt_name,
                        lender_name,
                        country,
                        currency,
                        original_amount,
                        interest_rate,
                        due_date,
                        notes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session["user_id"],
                        debt_form["debt_name"],
                        debt_form["lender_name"] or None,
                        debt_form["country"] or None,
                        debt_form["currency"],
                        str(original_amount),
                        (
                            str(interest_rate)
                            if interest_rate is not None
                            else None
                        ),
                        (
                            due_date_value.isoformat()
                            if due_date_value
                            else None
                        ),
                        debt_form["notes"] or None
                    )
                )
                conn.commit()
                flash("Debt added successfully.", "success")
                return redirect(url_for("debts"))
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
                conn.close()

    return render_template(
        "add_debt.html",
        debt=debt_form,
        form_action=url_for("add_debt"),
        page_mode="create",
        submit_label="Save Debt",
        page_title="Add Debt",
        page_description=(
            "Track loans, credit balances, and borrowed money in the right "
            "currency."
        ),
        side_title="Debt progress stays clear",
        side_note=(
            "Finlytics will calculate paid, remaining, progress, and status "
            "for every debt automatically."
        ),
        default_payment_date=today_value
    )


@app.route("/debt/<int:debt_id>/edit", methods=["GET", "POST"])
def edit_debt(debt_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                id,
                debt_name,
                lender_name,
                country,
                currency,
                original_amount,
                interest_rate,
                due_date,
                notes
            FROM debts
            WHERE id = %s
              AND user_id = %s
            """,
            (debt_id, session["user_id"])
        )
        debt_row = cursor.fetchone()

        if not debt_row:
            flash("Debt not found.", "error")
            return redirect(url_for("debts"))

        if request.method == "POST":
            debt_form = build_debt_form_data(request.form)
            original_amount, amount_error = parse_positive_amount(
                debt_form["original_amount"],
                "Original amount"
            )
            interest_rate, rate_error = parse_optional_rate(
                debt_form["interest_rate"]
            )

            if not debt_form["debt_name"]:
                flash("Please enter a debt name.", "error")
            elif debt_form["currency"] not in ALLOWED_CURRENCIES:
                flash("Please select a valid currency.", "error")
            elif amount_error:
                flash(amount_error, "error")
            elif rate_error:
                flash(rate_error, "error")
            elif (
                debt_form["due_date"]
                and validate_iso_date(
                    debt_form["due_date"],
                    "Due date"
                )[1]
            ):
                flash("Please choose a valid due date.", "error")
            else:
                due_date_value = (
                    validate_iso_date(
                        debt_form["due_date"],
                        "Due date"
                    )[0]
                    if debt_form["due_date"]
                    else None
                )

                cursor.close()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE debts
                    SET
                        debt_name = %s,
                        lender_name = %s,
                        country = %s,
                        currency = %s,
                        original_amount = %s,
                        interest_rate = %s,
                        due_date = %s,
                        notes = %s
                    WHERE id = %s
                      AND user_id = %s
                    """,
                    (
                        debt_form["debt_name"],
                        debt_form["lender_name"] or None,
                        debt_form["country"] or None,
                        debt_form["currency"],
                        str(original_amount),
                        (
                            str(interest_rate)
                            if interest_rate is not None
                            else None
                        ),
                        (
                            due_date_value.isoformat()
                            if due_date_value
                            else None
                        ),
                        debt_form["notes"] or None,
                        debt_id,
                        session["user_id"]
                    )
                )
                conn.commit()
                flash("Debt updated successfully.", "success")
                return redirect(url_for("debts"))

            debt = debt_form
        else:
            debt = {
                "debt_name": debt_row["debt_name"],
                "lender_name": debt_row["lender_name"] or "",
                "country": debt_row["country"] or "",
                "currency": debt_row["currency"],
                "original_amount": float(
                    debt_row["original_amount"] or 0
                ),
                "interest_rate": (
                    float(debt_row["interest_rate"])
                    if debt_row["interest_rate"] is not None
                    else ""
                ),
                "due_date": format_display_date(
                    debt_row["due_date"],
                    "%Y-%m-%d"
                ),
                "notes": debt_row["notes"] or ""
            }
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "edit_debt.html",
        debt=debt,
        form_action=url_for("edit_debt", debt_id=debt_id),
        page_mode="edit",
        submit_label="Update Debt",
        page_title="Edit Debt",
        page_description=(
            "Update amounts, due date, or lender details and keep the debt "
            "tracker accurate."
        ),
        side_title="Changes update instantly",
        side_note=(
            "Your paid and remaining numbers will refresh from the latest "
            "debt setup."
        )
    )


@app.route("/debt/<int:debt_id>/payment", methods=["GET", "POST"])
def debt_payment(debt_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                d.id,
                d.debt_name,
                d.currency,
                d.original_amount,
                COALESCE(SUM(dp.amount), 0) AS paid_amount
            FROM debts AS d
            LEFT JOIN debt_payments AS dp
                ON dp.debt_id = d.id
            WHERE d.id = %s
              AND d.user_id = %s
            GROUP BY d.id, d.debt_name, d.currency, d.original_amount
            """,
            (debt_id, session["user_id"])
        )
        debt = cursor.fetchone()

        if not debt:
            flash("Debt not found.", "error")
            return redirect(url_for("debts"))

        debt["original_amount"] = float(debt["original_amount"] or 0)
        debt["paid_amount"] = float(debt["paid_amount"] or 0)
        debt["remaining_amount"] = max(
            debt["original_amount"] - debt["paid_amount"],
            0
        )

        payment_form = build_debt_payment_form_data(
            request.form,
            date.today().isoformat()
        )

        if request.method == "POST":
            amount, amount_error = parse_positive_amount(
                payment_form["amount"],
                "Payment amount"
            )
            payment_date_value, payment_date_error = validate_iso_date(
                payment_form["payment_date"],
                "Payment date"
            )

            if amount_error:
                flash(amount_error, "error")
            elif payment_date_error:
                flash(payment_date_error, "error")
            elif debt["remaining_amount"] <= 0:
                flash(
                    "This debt is already cleared. No more payments needed.",
                    "error"
                )
            elif amount > Decimal(str(debt["remaining_amount"])):
                flash(
                    "Payment amount cannot be greater than the remaining debt.",
                    "error"
                )
            else:
                cursor.close()
                cursor = conn.cursor(dictionary=True)
                category_id = get_debt_payment_category_id(cursor)

                cursor.execute(
                    """
                    INSERT INTO transactions
                    (
                        user_id,
                        category_id,
                        amount,
                        type,
                        description,
                        transaction_date,
                        currency
                    )
                    VALUES (%s, %s, %s, 'expense', %s, %s, %s)
                    """,
                    (
                        session["user_id"],
                        category_id,
                        str(amount),
                        (
                            payment_form["notes"]
                            or f"Debt payment for {debt['debt_name']}"
                        ),
                        payment_date_value.isoformat(),
                        debt["currency"]
                    )
                )
                transaction_id = cursor.lastrowid

                cursor.execute(
                    """
                    INSERT INTO debt_payments
                    (
                        debt_id,
                        amount,
                        payment_date,
                        notes,
                        transaction_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        debt_id,
                        str(amount),
                        payment_date_value.isoformat(),
                        payment_form["notes"] or None,
                        transaction_id
                    )
                )
                conn.commit()
                flash(
                    "Debt payment recorded and added to expenses.",
                    "success"
                )
                return redirect(url_for("debts"))
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "debt_payment.html",
        debt=debt,
        payment=payment_form,
        form_action=url_for("debt_payment", debt_id=debt_id)
    )


@app.route("/debt/<int:debt_id>/delete", methods=["POST"])
def delete_debt(debt_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    ensure_database_schema()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            DELETE FROM debts
            WHERE id = %s
              AND user_id = %s
            """,
            (debt_id, session["user_id"])
        )

        if cursor.rowcount == 0:
            flash("Debt not found.", "error")
        else:
            flash(
                "Debt deleted successfully. Linked expense transactions were kept.",
                "success"
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("debts"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/privacy-policy")
def privacy_policy():
    return render_template("privacy_policy.html")


@app.route("/account/delete", methods=["POST"])
def delete_account():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            DELETE FROM users
            WHERE id = %s
            """,
            (user_id,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    session.clear()
    flash(
        "Your account and saved data were deleted successfully.",
        "success"
    )
    return redirect(url_for("register"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
