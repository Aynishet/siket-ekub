# dashboard_server.py
# ============================================================
# SIKET EKUB - WEB APP + ADMIN DASHBOARD SERVER
# PostgreSQL Version
#
# Main flow:
#
# WebApp
#   ↓
# /api/payments/create
#   ↓
# Ticket: available -> pending
# Payment:            -> pending
#   ↓
# /admin
#   ↓
# Payment Pending / Approval
#   ↓
# APPROVE:
#   Payment -> approved
#   Ticket  -> sold
#   Balance updated
#
# REJECT:
#   Payment -> rejected
#   Ticket  -> available
#
# ============================================================

import io
import os
import base64
from datetime import datetime

import pandas as pd
import psycopg2
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
)

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")


# ============================================================
# DATABASE
# ============================================================

def get_db_connection():
    """Create a PostgreSQL database connection."""
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"PostgreSQL connection error: {e}")
        return None


def fetchone_dict(cursor):
    """Return one PostgreSQL row as a dictionary."""
    row = cursor.fetchone()

    if row is None:
        return None

    columns = [desc[0] for desc in cursor.description]

    return dict(zip(columns, row))


def fetchall_dict(cursor):
    """Return all PostgreSQL rows as dictionaries."""
    rows = cursor.fetchall()

    if not rows:
        return []

    columns = [desc[0] for desc in cursor.description]

    return [
        dict(zip(columns, row))
        for row in rows
    ]


# ============================================================
# EMPTY METRICS
# ============================================================

def get_empty_metrics():
    return {
        "total_members": 0,
        "paid_users": 0,
        "unpaid_users": 0,
        "total_payment": 0,
        "payment_status_counts": {},
        "tickets_sold": 0,
        "tickets_pending": 0,
        "tickets_available": 0,
        "tickets_refunded": 0,
        "recent_payments": [],
        "members_list": [],
        "ticket_buyers": [],
        "daily_stats": [],
        "db_exists": False,
        "database_type": "PostgreSQL",
        "last_updated": datetime.now().isoformat(),
    }


# ============================================================
# DASHBOARD METRICS
# ============================================================

def get_dashboard_metrics():

    conn = None

    try:
        conn = get_db_connection()

        if not conn:
            return get_empty_metrics()

        cursor = conn.cursor()

        # ----------------------------------------------------
        # TOTAL MEMBERS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM users
        """)

        result = fetchone_dict(cursor)

        total_members = result["count"] if result else 0

        # ----------------------------------------------------
        # PAID USERS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) AS count
            FROM payments
            WHERE status = 'approved'
        """)

        result = fetchone_dict(cursor)

        paid_users = result["count"] if result else 0

        # ----------------------------------------------------
        # UNPAID USERS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1
                FROM payments p
                WHERE p.user_id = u.user_id
                  AND p.status = 'approved'
            )
        """)

        result = fetchone_dict(cursor)

        unpaid_users = result["count"] if result else 0

        # ----------------------------------------------------
        # TOTAL APPROVED PAYMENT
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COALESCE(
                SUM(extracted_amount), 0
            ) AS total
            FROM payments
            WHERE status = 'approved'
        """)

        result = fetchone_dict(cursor)

        total_payment = result["total"] if result else 0

        # ----------------------------------------------------
        # PAYMENT STATUS COUNTS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                status,
                COUNT(*) AS count
            FROM payments
            GROUP BY status
            ORDER BY status
        """)

        rows = fetchall_dict(cursor)

        payment_status_counts = {
            row["status"]: row["count"]
            for row in rows
        }

        # ----------------------------------------------------
        # TICKETS SOLD
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM tickets
            WHERE status = 'sold'
        """)

        result = fetchone_dict(cursor)

        tickets_sold = result["count"] if result else 0

        # ----------------------------------------------------
        # TICKETS PENDING
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM tickets
            WHERE status = 'pending'
        """)

        result = fetchone_dict(cursor)

        tickets_pending = result["count"] if result else 0

        # ----------------------------------------------------
        # TICKETS AVAILABLE
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM tickets
            WHERE status = 'available'
        """)

        result = fetchone_dict(cursor)

        tickets_available = result["count"] if result else 0

        # ----------------------------------------------------
        # TICKETS REFUNDED
        # ----------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM tickets
            WHERE status = 'refunded'
        """)

        result = fetchone_dict(cursor)

        tickets_refunded = result["count"] if result else 0

        # ----------------------------------------------------
        # RECENT PAYMENTS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                p.payment_id,
                p.user_id,
                p.telegram_id,
                p.phone_number,
                p.ticket_id,
                p.ticket_number,
                p.extracted_ref,
                p.extracted_amount,
                p.extracted_date,
                p.status,
                p.created_at,
                u.full_name
            FROM payments p
            LEFT JOIN users u
                ON p.user_id = u.user_id
            ORDER BY p.payment_id DESC
            LIMIT 20
        """)

        recent_payments = fetchall_dict(cursor)

        # ----------------------------------------------------
        # MEMBERS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                u.user_id,
                u.telegram_id,
                u.phone_number,
                u.full_name,
                u.address,
                u.registration_date,
                COALESCE(u.balance, 0) AS balance,

                COALESCE(
                    SUM(
                        CASE
                            WHEN p.status = 'approved'
                            THEN p.extracted_amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS total_paid,

                COUNT(
                    CASE
                        WHEN p.status = 'approved'
                        THEN 1
                    END
                ) AS payment_count

            FROM users u

            LEFT JOIN payments p
                ON u.user_id = p.user_id

            GROUP BY
                u.user_id,
                u.telegram_id,
                u.phone_number,
                u.full_name,
                u.address,
                u.registration_date,
                u.balance

            ORDER BY total_paid DESC

            LIMIT 50
        """)

        members_list = fetchall_dict(cursor)

        # ----------------------------------------------------
        # TICKET BUYERS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                u.user_id,
                u.telegram_id,
                u.phone_number,
                u.full_name,

                COUNT(DISTINCT t.ticket_id)
                    AS ticket_count,

                COALESCE(
                    SUM(
                        DISTINCT CASE
                            WHEN p.status = 'approved'
                            THEN p.extracted_amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS total_paid

            FROM users u

            JOIN tickets t
                ON u.user_id = t.user_id

            LEFT JOIN payments p
                ON u.user_id = p.user_id

            WHERE t.status = 'sold'

            GROUP BY
                u.user_id,
                u.telegram_id,
                u.phone_number,
                u.full_name

            ORDER BY ticket_count DESC

            LIMIT 50
        """)

        ticket_buyers = fetchall_dict(cursor)

        # ----------------------------------------------------
        # DAILY PAYMENT STATISTICS
        # PostgreSQL syntax
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                DATE(created_at) AS date,
                COUNT(*) AS payments_count,
                COALESCE(
                    SUM(extracted_amount), 0
                ) AS total_amount

            FROM payments

            WHERE status = 'approved'
              AND created_at >= CURRENT_DATE - INTERVAL '7 days'

            GROUP BY DATE(created_at)

            ORDER BY date DESC
        """)

        daily_stats = fetchall_dict(cursor)

        return {
            "total_members": total_members,
            "paid_users": paid_users,
            "unpaid_users": unpaid_users,
            "total_payment": total_payment,
            "payment_status_counts": payment_status_counts,

            "tickets_sold": tickets_sold,
            "tickets_pending": tickets_pending,
            "tickets_available": tickets_available,
            "tickets_refunded": tickets_refunded,

            "recent_payments": recent_payments,
            "members_list": members_list,
            "ticket_buyers": ticket_buyers,
            "daily_stats": daily_stats,

            "db_exists": True,
            "database_type": "PostgreSQL",
            "last_updated": datetime.now().isoformat(),
        }

    except Exception as e:

        print(f"ERROR get_dashboard_metrics: {e}")

        return get_empty_metrics()

    finally:

        if conn:
            conn.close()


# ============================================================
# WEB APP
# ============================================================

@app.route("/")
def serve_webapp():

    try:
        return send_from_directory(
            BASE_DIR,
            "index.html"
        )

    except Exception as e:

        print(f"WebApp error: {e}")

        return (
            f"WebApp not found. Error: {e}",
            404
        )


@app.route("/webapp")
@app.route("/webapp/")
def webapp_alt():

    return serve_webapp()


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@app.route("/admin/")
def admin_dashboard():

    try:

        metrics = get_dashboard_metrics()

        return render_template(
            "dashboard.html",
            metrics=metrics,
            server_status="running",
        )

    except Exception as e:

        print(f"Dashboard error: {e}")

        return render_template(
            "dashboard.html",
            metrics=get_empty_metrics(),
            server_status="failed",
            error_message=str(e),
        )


# ============================================================
# STATIC ASSETS
# ============================================================

@app.route("/assets/<path:path>")
def serve_assets(path):

    try:

        return send_from_directory(
            os.path.join(BASE_DIR, "assets"),
            path
        )

    except Exception as e:

        return (
            f"Asset not found: {path}. Error: {e}",
            404
        )


# ============================================================
# USER API
# ============================================================

@app.route(
    "/api/user/<int:telegram_id>",
    methods=["GET"]
)
def api_get_user(telegram_id):

    conn = None

    try:

        conn = get_db_connection()

        if not conn:
            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        # ----------------------------------------------------
        # USER
        # ----------------------------------------------------

        cursor.execute("""
            SELECT *
            FROM users
            WHERE telegram_id = %s
            LIMIT 1
        """, (telegram_id,))

        user = fetchone_dict(cursor)

        if not user:

            return jsonify({
                "success": False,
                "error": "User not found"
            }), 404

        # ----------------------------------------------------
        # TICKETS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                ticket_id,
                ticket_number,
                status,
                assigned_at
            FROM tickets
            WHERE telegram_id = %s
              AND status = 'sold'
            ORDER BY assigned_at DESC
        """, (telegram_id,))

        tickets = fetchall_dict(cursor)

        # ----------------------------------------------------
        # PAYMENTS
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                payment_id,
                ticket_number,
                extracted_amount AS amount,
                status,
                created_at AS date
            FROM payments
            WHERE telegram_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        """, (telegram_id,))

        payments = fetchall_dict(cursor)

        return jsonify({
            "success": True,
            "data": {
                "user_id": user.get("user_id"),
                "telegram_id": user.get("telegram_id"),
                "phone_number": user.get("phone_number"),
                "address": user.get("address"),
                "full_name": user.get("full_name"),
                "balance": user.get("balance") or 0,
                "total_spent": user.get("total_spent") or 0,
                "registration_date": user.get(
                    "registration_date"
                ),
                "tickets": tickets,
                "payments": payments,
            }
        })

    except Exception as e:

        print(f"ERROR /api/user: {e}")

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# CREATE USER
# ============================================================

@app.route(
    "/api/user/create",
    methods=["POST"]
)
def api_create_user():

    conn = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        telegram_id = data.get("telegram_id")

        if not telegram_id:

            return jsonify({
                "success": False,
                "error": "Telegram ID is required"
            }), 400

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        # Check existing user

        cursor.execute("""
            SELECT user_id
            FROM users
            WHERE telegram_id = %s
            LIMIT 1
        """, (telegram_id,))

        existing = cursor.fetchone()

        if existing:

            return jsonify({
                "success": False,
                "error": "User already exists"
            }), 400

        # Insert

        cursor.execute("""
            INSERT INTO users (
                telegram_id,
                phone_number,
                address,
                full_name,
                language
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s
            )
            RETURNING user_id
        """, (
            telegram_id,
            data.get("phone_number"),
            data.get("address"),
            data.get("full_name") or "User",
            data.get("language") or "en",
        ))

        user_id = cursor.fetchone()[0]

        conn.commit()

        return jsonify({
            "success": True,
            "user_id": user_id,
            "message": "User created successfully"
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(f"ERROR /api/user/create: {e}")

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# TICKETS
# ============================================================

@app.route(
    "/api/tickets",
    methods=["GET"]
)
def api_get_tickets():

    conn = None

    try:

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        # ----------------------------------------------------
        # Ticket type
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                type_id,
                name,
                description,
                total_slots,
                price
            FROM ticket_types
            WHERE is_active = TRUE
            ORDER BY type_id
            LIMIT 1
        """)

        ticket_type = fetchone_dict(cursor)

        if not ticket_type:

            return jsonify({
                "success": False,
                "error": "No active ticket type found"
            }), 404

        # ----------------------------------------------------
        # Tickets
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                ticket_id,
                ticket_number,
                status
            FROM tickets
            WHERE type_id = %s
            ORDER BY ticket_number
        """, (
            ticket_type["type_id"],
        ))

        tickets = fetchall_dict(cursor)

        return jsonify({
            "success": True,
            "data": {
                "type_id": ticket_type["type_id"],
                "name": ticket_type["name"],
                "description": ticket_type["description"],
                "total_slots": ticket_type["total_slots"],
                "price": ticket_type["price"],
                "tickets": tickets,
            }
        })

    except Exception as e:

        print(f"ERROR /api/tickets: {e}")

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# TICKET ASSIGN / RESERVE
#
# IMPORTANT:
# The payment creation endpoint below also reserves tickets.
# This endpoint is retained for compatibility with the
# existing WebApp.
# ============================================================

@app.route(
    "/api/tickets/assign",
    methods=["POST"]
)
def api_assign_ticket():

    conn = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        telegram_id = data.get("telegram_id")
        ticket_ids = data.get("ticket_ids") or []

        if not telegram_id:

            return jsonify({
                "success": False,
                "error": "Telegram ID is required"
            }), 400

        if not ticket_ids:

            return jsonify({
                "success": False,
                "error": "No tickets selected"
            }), 400

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                user_id,
                phone_number
            FROM users
            WHERE telegram_id = %s
            LIMIT 1
        """, (telegram_id,))

        user = fetchone_dict(cursor)

        if not user:

            return jsonify({
                "success": False,
                "error": "User not found"
            }), 404

        assigned = []
        failed = []

        for ticket_id in ticket_ids:

            cursor.execute("""
                UPDATE tickets
                SET
                    status = 'pending',
                    user_id = %s,
                    telegram_id = %s,
                    phone_number = %s
                WHERE ticket_id = %s
                  AND status = 'available'
            """, (
                user["user_id"],
                telegram_id,
                user["phone_number"],
                ticket_id,
            ))

            if cursor.rowcount == 1:

                assigned.append(ticket_id)

            else:

                failed.append(ticket_id)

        conn.commit()

        return jsonify({
            "success": True,
            "assigned": assigned,
            "failed": failed,
            "message": (
                f"{len(assigned)} tickets reserved, "
                f"{len(failed)} failed"
            )
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(f"ERROR /api/tickets/assign: {e}")

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# CREATE PAYMENT
# ============================================================

@app.route(
    "/api/payments/create",
    methods=["POST"]
)
def api_create_payment():

    conn = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        telegram_id = data.get("telegram_id")
        ticket_id = data.get("ticket_id")

        extracted_ref = (
            data.get("extracted_ref") or ""
        ).strip()

        raw_sms = (
            data.get("raw_sms")
            or extracted_ref
        )

        screenshot_data = (
            data.get("screenshot_data") or ""
        )

        try:
            extracted_amount = float(
                data.get("extracted_amount") or 0
            )
        except (TypeError, ValueError):

            return jsonify({
                "success": False,
                "error": "Invalid payment amount"
            }), 400

        # ----------------------------------------------------
        # Validation
        # ----------------------------------------------------

        if not telegram_id:

            return jsonify({
                "success": False,
                "error": "Telegram ID is required"
            }), 400

        if not ticket_id:

            return jsonify({
                "success": False,
                "error": "Ticket ID is required"
            }), 400

        if extracted_amount <= 0:

            return jsonify({
                "success": False,
                "error": "Invalid payment amount"
            }), 400

        if not extracted_ref and not screenshot_data:

            return jsonify({
                "success": False,
                "error": (
                    "Transaction reference or "
                    "receipt is required"
                )
            }), 400

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        # ----------------------------------------------------
        # USER
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                user_id,
                telegram_id,
                phone_number,
                full_name
            FROM users
            WHERE telegram_id = %s
            LIMIT 1
        """, (telegram_id,))

        user = fetchone_dict(cursor)

        if not user:

            conn.rollback()

            return jsonify({
                "success": False,
                "error": (
                    "User not found. "
                    "Please register first."
                )
            }), 404

        # ----------------------------------------------------
        # LOCK TICKET
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                ticket_id,
                ticket_number,
                status,
                user_id,
                telegram_id,
                type_id
            FROM tickets
            WHERE ticket_id = %s
            FOR UPDATE
        """, (ticket_id,))

        ticket = fetchone_dict(cursor)

        if not ticket:

            conn.rollback()

            return jsonify({
                "success": False,
                "error": "Ticket not found"
            }), 404

        # ----------------------------------------------------
        # Ticket availability
        #
        # Normally it should be available.
        #
        # If the existing WebApp already called
        # /api/tickets/assign, allow the same user's
        # pending ticket to continue.
        # ----------------------------------------------------

        if ticket["status"] == "pending":

            if (
                ticket["user_id"] != user["user_id"]
            ):

                conn.rollback()

                return jsonify({
                    "success": False,
                    "error": (
                        f"Ticket #{ticket['ticket_number']} "
                        "is already reserved"
                    )
                }), 409

        elif ticket["status"] == "available":

            cursor.execute("""
                UPDATE tickets
                SET
                    status = 'pending',
                    user_id = %s,
                    telegram_id = %s,
                    phone_number = %s
                WHERE ticket_id = %s
                  AND status = 'available'
            """, (
                user["user_id"],
                telegram_id,
                user["phone_number"],
                ticket_id,
            ))

            if cursor.rowcount != 1:

                conn.rollback()

                return jsonify({
                    "success": False,
                    "error": (
                        "Ticket was just taken "
                        "by another user"
                    )
                }), 409

        else:

            conn.rollback()

            return jsonify({
                "success": False,
                "error": (
                    f"Ticket #{ticket['ticket_number']} "
                    f"is {ticket['status']}"
                )
            }), 409

        # ----------------------------------------------------
        # CHECK FOR EXISTING PENDING PAYMENT
        # ----------------------------------------------------

        cursor.execute("""
            SELECT payment_id
            FROM payments
            WHERE ticket_id = %s
              AND status = 'pending'
            LIMIT 1
        """, (ticket_id,))

        existing_payment = cursor.fetchone()

        if existing_payment:

            conn.rollback()

            return jsonify({
                "success": False,
                "error": (
                    "A payment for this ticket "
                    "is already pending approval"
                )
            }), 409

        # ----------------------------------------------------
        # GET TICKET PRICE
        # ----------------------------------------------------

        cursor.execute("""
            SELECT price
            FROM ticket_types
            WHERE type_id = %s
            LIMIT 1
        """, (
            ticket["type_id"],
        ))

        ticket_type = cursor.fetchone()

        if ticket_type:

            ticket_price = float(
                ticket_type[0] or 0
            )

            # ------------------------------------------------
            # Amount validation
            #
            # Do not reject if the database price is zero.
            # This allows existing installations where the
            # price has not been configured yet.
            # ------------------------------------------------

            if (
                ticket_price > 0
                and abs(
                    extracted_amount - ticket_price
                ) > 0.01
            ):

                conn.rollback()

                return jsonify({
                    "success": False,
                    "error": (
                        f"Payment amount must be "
                        f"{ticket_price:.2f} ETB"
                    )
                }), 400

        # ----------------------------------------------------
        # CREATE PAYMENT
        # ----------------------------------------------------

        cursor.execute("""
            INSERT INTO payments (
                user_id,
                telegram_id,
                phone_number,
                ticket_id,
                ticket_number,
                raw_sms,
                extracted_ref,
                extracted_amount,
                extracted_date,
                status,
                screenshot_data
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                CURRENT_TIMESTAMP,
                'pending',
                %s
            )
            RETURNING payment_id
        """, (
            user["user_id"],
            telegram_id,
            user["phone_number"],
            ticket_id,
            ticket["ticket_number"],
            raw_sms,
            extracted_ref,
            extracted_amount,
            screenshot_data,
        ))

        payment_id = cursor.fetchone()[0]

        # ----------------------------------------------------
        # COMMIT
        # ----------------------------------------------------

        conn.commit()

        print(
            f"PAYMENT CREATED: "
            f"payment_id={payment_id}, "
            f"ticket={ticket['ticket_number']}, "
            f"user={telegram_id}"
        )

        return jsonify({
            "success": True,
            "payment_id": payment_id,
            "ticket_id": ticket_id,
            "ticket_number": ticket["ticket_number"],
            "status": "pending",
            "message": (
                "Payment submitted successfully "
                "and is waiting for admin approval."
            )
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            f"ERROR /api/payments/create: {e}"
        )

        return jsonify({
            "success": False,
            "error": "Payment submission failed"
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# PENDING PAYMENTS
# ============================================================

@app.route(
    "/api/payments/pending",
    methods=["GET"]
)
def api_pending_payments():

    conn = None

    try:

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                p.payment_id,
                p.user_id,
                p.telegram_id,
                p.phone_number,
                p.ticket_id,
                p.ticket_number,
                p.raw_sms,
                p.extracted_ref,
                p.extracted_amount,
                p.extracted_date,
                p.status,
                p.screenshot_data,
                p.created_at,
                u.full_name

            FROM payments p

            LEFT JOIN users u
                ON p.user_id = u.user_id

            WHERE p.status = 'pending'

            ORDER BY p.created_at ASC
        """)

        payments = fetchall_dict(cursor)

        # Do not send large base64 image in list.

        for payment in payments:

            payment["has_screenshot"] = bool(
                payment.get("screenshot_data")
            )

            payment.pop(
                "screenshot_data",
                None
            )

        return jsonify({
            "success": True,
            "count": len(payments),
            "payments": payments,
        })

    except Exception as e:

        print(
            f"ERROR /api/payments/pending: {e}"
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# PAYMENT SCREENSHOT
# ============================================================

@app.route(
    "/api/payments/<int:payment_id>/screenshot",
    methods=["GET"]
)
def api_payment_screenshot(payment_id):

    conn = None

    try:

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        cursor.execute("""
            SELECT screenshot_data
            FROM payments
            WHERE payment_id = %s
        """, (payment_id,))

        result = cursor.fetchone()

        if not result or not result[0]:

            return jsonify({
                "success": False,
                "error": "No screenshot found"
            }), 404

        raw_data = result[0]

        # Handle data URL format:
        #
        # data:image/jpeg;base64,XXXX
        #
        # or:
        #
        # XXXX

        if isinstance(raw_data, memoryview):

            raw_data = raw_data.tobytes()

        if isinstance(raw_data, bytes):

            image_data = raw_data

        else:

            raw_data = str(raw_data)

            if "," in raw_data and raw_data.startswith(
                "data:"
            ):

                raw_data = raw_data.split(
                    ",",
                    1
                )[1]

            image_data = base64.b64decode(
                raw_data
            )

        return send_file(
            io.BytesIO(image_data),
            mimetype="image/jpeg",
            as_attachment=False,
            download_name=(
                f"payment_{payment_id}.jpg"
            ),
        )

    except Exception as e:

        print(
            f"ERROR screenshot: {e}"
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# VERIFY PAYMENT
# ============================================================

@app.route(
    "/api/payments/verify",
    methods=["POST"]
)
def api_verify_payment():

    conn = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        payment_id = data.get("payment_id")

        status = (
            data.get("status")
            or "approved"
        ).lower()

        admin_id = data.get("admin_id")

        notes = (
            data.get("notes")
            or ""
        )

        # ----------------------------------------------------
        # Validation
        # ----------------------------------------------------

        if not payment_id:

            return jsonify({
                "success": False,
                "error": "Payment ID is required"
            }), 400

        if status not in (
            "approved",
            "rejected"
        ):

            return jsonify({
                "success": False,
                "error": (
                    "Status must be "
                    "approved or rejected"
                )
            }), 400

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        # ----------------------------------------------------
        # LOCK PAYMENT
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                payment_id,
                user_id,
                telegram_id,
                ticket_id,
                ticket_number,
                extracted_amount,
                status

            FROM payments

            WHERE payment_id = %s

            FOR UPDATE
        """, (payment_id,))

        payment = fetchone_dict(cursor)

        if not payment:

            conn.rollback()

            return jsonify({
                "success": False,
                "error": "Payment not found"
            }), 404

        if payment["status"] != "pending":

            conn.rollback()

            return jsonify({
                "success": False,
                "error": (
                    f"Payment is already "
                    f"{payment['status']}"
                )
            }), 409

        # ====================================================
        # APPROVE
        # ====================================================

        if status == "approved":

            # ------------------------------------------------
            # Lock ticket
            # ------------------------------------------------

            cursor.execute("""
                SELECT
                    ticket_id,
                    ticket_number,
                    status,
                    user_id

                FROM tickets

                WHERE ticket_id = %s

                FOR UPDATE
            """, (
                payment["ticket_id"],
            ))

            ticket = fetchone_dict(cursor)

            if not ticket:

                conn.rollback()

                return jsonify({
                    "success": False,
                    "error": "Ticket not found"
                }), 404

            # ------------------------------------------------
            # Ticket must belong to payment user
            # ------------------------------------------------

            if (
                ticket["user_id"]
                != payment["user_id"]
            ):

                conn.rollback()

                return jsonify({
                    "success": False,
                    "error": (
                        "Ticket ownership "
                        "does not match payment"
                    )
                }), 409

            # ------------------------------------------------
            # Ticket must be pending
            # ------------------------------------------------

            if ticket["status"] != "pending":

                conn.rollback()

                return jsonify({
                    "success": False,
                    "error": (
                        f"Ticket #{ticket['ticket_number']} "
                        f"is {ticket['status']}, "
                        "not pending"
                    )
                }), 409

            # ------------------------------------------------
            # Ticket -> SOLD
            # ------------------------------------------------

            cursor.execute("""
                UPDATE tickets
                SET
                    status = 'sold',
                    assigned_at = CURRENT_TIMESTAMP

                WHERE ticket_id = %s
                  AND status = 'pending'
            """, (
                payment["ticket_id"],
            ))

            if cursor.rowcount != 1:

                conn.rollback()

                return jsonify({
                    "success": False,
                    "error": (
                        "Could not finalize ticket"
                    )
                }), 409

            # ------------------------------------------------
            # Payment -> APPROVED
            # ------------------------------------------------

            cursor.execute("""
                UPDATE payments
                SET
                    status = 'approved',
                    verified_by = %s,
                    verified_at = CURRENT_TIMESTAMP,
                    admin_notes = %s

                WHERE payment_id = %s
                  AND status = 'pending'
            """, (
                admin_id,
                notes,
                payment_id,
            ))

            if cursor.rowcount != 1:

                conn.rollback()

                return jsonify({
                    "success": False,
                    "error": (
                        "Could not approve payment"
                    )
                }), 409

            # ------------------------------------------------
            # Update USER BALANCE
            # ------------------------------------------------

            amount = float(
                payment["extracted_amount"] or 0
            )

            cursor.execute("""
                UPDATE users

                SET
                    balance =
                        COALESCE(balance, 0)
                        + %s,

                    total_spent =
                        COALESCE(total_spent, 0)
                        + %s

                WHERE user_id = %s
            """, (
                amount,
                amount,
                payment["user_id"],
            ))

        # ====================================================
        # REJECT
        # ====================================================

        else:

            # ------------------------------------------------
            # Return ticket to available
            # ------------------------------------------------

            cursor.execute("""
                UPDATE tickets

                SET
                    status = 'available',
                    user_id = NULL,
                    telegram_id = NULL,
                    phone_number = NULL,
                    assigned_at = NULL

                WHERE ticket_id = %s
                  AND status = 'pending'
            """, (
                payment["ticket_id"],
            ))

            # ------------------------------------------------
            # Payment -> REJECTED
            # ------------------------------------------------

            cursor.execute("""
                UPDATE payments

                SET
                    status = 'rejected',
                    verified_by = %s,
                    verified_at = CURRENT_TIMESTAMP,
                    admin_notes = %s

                WHERE payment_id = %s
                  AND status = 'pending'
            """, (
                admin_id,
                notes,
                payment_id,
            ))

            if cursor.rowcount != 1:

                conn.rollback()

                return jsonify({
                    "success": False,
                    "error": (
                        "Could not reject payment"
                    )
                }), 409

        # ----------------------------------------------------
        # COMMIT
        # ----------------------------------------------------

        conn.commit()

        print(
            f"PAYMENT VERIFIED: "
            f"id={payment_id}, "
            f"status={status}"
        )

        return jsonify({
            "success": True,
            "payment_id": payment_id,
            "ticket_number": (
                payment["ticket_number"]
            ),
            "status": status,
            "message": (
                f"Payment #{payment_id} "
                f"{status} successfully."
            ),
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            f"ERROR /api/payments/verify: {e}"
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# PAYMENT ACCOUNTS
# ============================================================

@app.route(
    "/api/payment_accounts",
    methods=["GET"]
)
def api_payment_accounts():

    accounts = [
        {
            "name": "CBE",
            "account": "1000786684491",
        },
        {
            "name": "Abyssinia",
            "account": "264517826",
        },
        {
            "name": "Telebirr",
            "account": "0979774444",
        },
    ]

    return jsonify({
        "success": True,
        "data": accounts,
    })


# ============================================================
# PRIZES
# ============================================================

@app.route(
    "/api/prizes",
    methods=["GET"]
)
def api_get_prizes():

    conn = None

    try:

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                prize_position,
                prize_name,
                prize_description,
                prize_value

            FROM prizes

            WHERE is_active = TRUE

            ORDER BY prize_position
        """)

        prizes = fetchall_dict(cursor)

        return jsonify({
            "success": True,
            "data": prizes,
        })

    except Exception as e:

        print(
            f"ERROR /api/prizes: {e}"
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# REFUND REQUEST
# ============================================================

@app.route(
    "/api/refund_request",
    methods=["POST"]
)
def api_refund_request():

    conn = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        telegram_id = data.get(
            "telegram_id"
        )

        reason = (
            data.get("reason")
            or ""
        )

        if not telegram_id:

            return jsonify({
                "success": False,
                "error": "Telegram ID is required"
            }), 400

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "success": False,
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor()

        # ----------------------------------------------------
        # User
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                user_id,
                telegram_id,
                phone_number,
                balance

            FROM users

            WHERE telegram_id = %s

            LIMIT 1
        """, (
            telegram_id,
        ))

        user = fetchone_dict(cursor)

        if not user:

            return jsonify({
                "success": False,
                "error": "User not found"
            }), 404

        balance = float(
            user["balance"] or 0
        )

        if balance <= 0:

            return jsonify({
                "success": False,
                "error": (
                    "No balance available "
                    "for refund"
                )
            }), 400

        # ----------------------------------------------------
        # Find latest approved payment
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                payment_id,
                ticket_id,
                ticket_number,
                extracted_amount

            FROM payments

            WHERE telegram_id = %s
              AND status = 'approved'

            ORDER BY created_at DESC

            LIMIT 1
        """, (
            telegram_id,
        ))

        payment = fetchone_dict(cursor)

        if not payment:

            return jsonify({
                "success": False,
                "error": (
                    "No approved payment "
                    "found for refund"
                )
            }), 400

        refund_amount = min(
            float(
                payment["extracted_amount"] or 0
            ),
            balance,
        )

        # ----------------------------------------------------
        # Create refund
        # ----------------------------------------------------

        cursor.execute("""
            INSERT INTO refunds (
                user_id,
                telegram_id,
                phone_number,
                ticket_id,
                ticket_number,
                payment_id,
                refund_amount,
                refund_reason,
                status
            )

            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'pending'
            )

            RETURNING refund_id
        """, (
            user["user_id"],
            user["telegram_id"],
            user["phone_number"],
            payment["ticket_id"],
            payment["ticket_number"],
            payment["payment_id"],
            refund_amount,
            reason,
        ))

        refund_id = cursor.fetchone()[0]

        conn.commit()

        return jsonify({
            "success": True,
            "refund_id": refund_id,
            "message": (
                "Refund request submitted"
            ),
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            f"ERROR /api/refund_request: {e}"
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# METRICS
# ============================================================

@app.route(
    "/api/metrics",
    methods=["GET"]
)
def api_metrics():

    try:

        return jsonify(
            get_dashboard_metrics()
        )

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# REFRESH
# ============================================================

@app.route(
    "/api/refresh",
    methods=["GET"]
)
def refresh_database_data():

    try:

        metrics = get_dashboard_metrics()

        return jsonify({
            "status": "success",
            "data": metrics,
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500


# ============================================================
# DATABASE STATUS
# ============================================================

@app.route(
    "/api/status",
    methods=["GET"]
)
def api_status():

    conn = None

    try:

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "status": "error",
                "database": "disconnected",
                "database_type": "PostgreSQL",
                "timestamp": datetime.now().isoformat(),
            }), 500

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                current_database() AS database_name,
                current_schema() AS schema_name
        """)

        db_info = fetchone_dict(cursor)

        return jsonify({
            "status": "running",
            "database": "connected",
            "database_type": "PostgreSQL",
            "database_name": (
                db_info["database_name"]
                if db_info else None
            ),
            "schema": (
                db_info["schema_name"]
                if db_info else None
            ),
            "timestamp": datetime.now().isoformat(),
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "database": "disconnected",
            "database_type": "PostgreSQL",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route(
    "/health",
    methods=["GET"]
)
def health_check():

    conn = None

    try:

        conn = get_db_connection()

        if not conn:

            return jsonify({
                "status": "unhealthy",
                "database": "disconnected",
                "database_type": "PostgreSQL",
            }), 500

        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1"
        )

        cursor.fetchone()

        return jsonify({
            "status": "healthy",
            "database": "connected",
            "database_type": "PostgreSQL",
        })

    except Exception as e:

        return jsonify({
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e),
        }), 500

    finally:

        if conn:
            conn.close()


# ============================================================
# EXPORT REPORTS
# ============================================================

@app.route(
    "/api/export/<report_type>",
    methods=["GET"]
)
def export_report(report_type):

    try:

        metrics = get_dashboard_metrics()

        # ----------------------------------------------------
        # MEMBERS
        # ----------------------------------------------------

        if report_type == "members":

            data = []

            for member in metrics.get(
                "members_list",
                []
            ):

                data.append({
                    "Full Name":
                        member.get(
                            "full_name"
                        ) or "N/A",

                    "Telegram ID":
                        member.get(
                            "telegram_id"
                        ) or "N/A",

                    "Phone Number":
                        member.get(
                            "phone_number"
                        ) or "N/A",

                    "Address":
                        member.get(
                            "address"
                        ) or "N/A",

                    "Balance":
                        float(
                            member.get(
                                "balance",
                                0
                            ) or 0
                        ),

                    "Total Paid":
                        float(
                            member.get(
                                "total_paid",
                                0
                            ) or 0
                        ),

                    "Payment Count":
                        member.get(
                            "payment_count",
                            0
                        ),
                })

            df = pd.DataFrame(data)

            filename = (
                "members_report_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                ".xlsx"
            )

        # ----------------------------------------------------
        # TICKETS
        # ----------------------------------------------------

        elif report_type == "tickets":

            data = []

            for buyer in metrics.get(
                "ticket_buyers",
                []
            ):

                data.append({
                    "Name":
                        buyer.get(
                            "full_name"
                        ) or "N/A",

                    "Telegram ID":
                        buyer.get(
                            "telegram_id"
                        ) or "N/A",

                    "Phone":
                        buyer.get(
                            "phone_number"
                        ) or "N/A",

                    "Tickets":
                        buyer.get(
                            "ticket_count",
                            0
                        ),

                    "Total Paid":
                        float(
                            buyer.get(
                                "total_paid",
                                0
                            ) or 0
                        ),
                })

            df = pd.DataFrame(data)

            filename = (
                "ticket_buyers_report_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                ".xlsx"
            )

        # ----------------------------------------------------
        # FINANCIAL
        # ----------------------------------------------------

        elif report_type == "financial":

            data = []

            for payment in metrics.get(
                "recent_payments",
                []
            ):

                data.append({
                    "Payment ID":
                        payment.get(
                            "payment_id"
                        ),

                    "Ticket":
                        payment.get(
                            "ticket_number"
                        ),

                    "Telegram ID":
                        payment.get(
                            "telegram_id"
                        ),

                    "Reference":
                        payment.get(
                            "extracted_ref"
                        ) or "N/A",

                    "Amount":
                        float(
                            payment.get(
                                "extracted_amount",
                                0
                            ) or 0
                        ),

                    "Status":
                        payment.get(
                            "status"
                        ) or "N/A",

                    "Date":
                        payment.get(
                            "created_at"
                        ) or "N/A",
                })

            df = pd.DataFrame(data)

            filename = (
                "financial_report_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                ".xlsx"
            )

        else:

            return jsonify({
                "success": False,
                "error": (
                    "Invalid report type. "
                    "Use members, tickets, "
                    "or financial."
                )
            }), 400

        # ----------------------------------------------------
        # CREATE EXCEL
        # ----------------------------------------------------

        output = io.BytesIO()

        df.to_excel(
            output,
            index=False,
            engine="openpyxl"
        )

        output.seek(0)

        return send_file(
            output,
            mimetype=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:

        print(
            f"ERROR export: {e}"
        )

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============================================================
# APPLICATION OBJECT
# ============================================================

application = app


# ============================================================
# START SERVER
# ============================================================

def start_dashboard():

    print(
        "================================================"
    )

    print(
        "📊 SIKET EKUB ADMIN DASHBOARD"
    )

    print(
        "================================================"
    )

    print(
        "Database: PostgreSQL"
    )

    print(
        "WebApp:   http://0.0.0.0:8080/"
    )

    print(
        "Admin:    http://0.0.0.0:8080/admin"
    )

    print(
        "Health:   http://0.0.0.0:8080/health"
    )

    print(
        "Status:   http://0.0.0.0:8080/api/status"
    )

    print(
        "================================================"
    )

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    start_dashboard()
