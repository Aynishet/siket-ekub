# dashboard_server.py
# ============================================================
# SIKET EKUB - WEBAPP + ADMIN DASHBOARD
# PostgreSQL ONLY - COMPLETE FIXED
# ============================================================

import os
import io
import base64
import logging
from datetime import datetime

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

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

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("siket-ekub-dashboard")


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("INTERNAL_DATABASE_URL")
    or os.getenv("POSTGRES_URL")
)

if not DATABASE_URL:
    logger.error("DATABASE_URL is not configured.")


def get_db_connection():
    """Create a PostgreSQL connection."""
    if not DATABASE_URL:
        return None

    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            connect_timeout=10,
        )
        return conn
    except Exception as exc:
        logger.exception("PostgreSQL connection error: %s", exc)
        return None


def safe_close(conn):
    try:
        if conn:
            conn.close()
    except Exception:
        pass


def fetch_one(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_all(cursor):
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


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
        "database_connected": False,
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

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT COUNT(*) AS count FROM users")
        total_members = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) AS count
            FROM payments
            WHERE status = 'approved'
        """)
        paid_users = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1 FROM payments p
                WHERE p.user_id = u.user_id AND p.status = 'approved'
            )
        """)
        unpaid_users = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM payments
            WHERE status = 'approved'
        """)
        total_payment = cursor.fetchone()["total"] or 0

        cursor.execute("""
            SELECT status, COUNT(*) AS count
            FROM payments
            GROUP BY status
            ORDER BY status
        """)
        payment_status_counts = {}
        for row in cursor.fetchall():
            payment_status_counts[row["status"]] = row["count"]

        cursor.execute("SELECT COUNT(*) AS count FROM tickets WHERE status = 'sold'")
        tickets_sold = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) AS count FROM tickets WHERE status = 'pending'")
        tickets_pending = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) AS count FROM tickets WHERE status = 'available'")
        tickets_available = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) AS count FROM tickets WHERE status = 'refunded'")
        tickets_refunded = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT
                p.payment_id,
                p.user_id,
                p.telegram_id,
                p.phone_number,
                p.ticket_id,
                p.ticket_number,
                p.amount,
                p.extracted_ref,
                p.extracted_amount,
                p.extracted_date,
                p.status,
                p.admin_notes,
                p.created_at,
                u.full_name,
                u.phone_number as user_phone
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.user_id
            ORDER BY p.payment_id DESC
            LIMIT 20
        """)
        recent_payments = fetch_all(cursor)

        cursor.execute("""
            SELECT
                u.user_id,
                u.telegram_id,
                u.phone_number,
                u.full_name,
                u.address,
                u.created_at as registration_date,
                COALESCE(u.balance, 0) AS balance,
                COALESCE(u.total_spent, 0) AS total_spent,
                COALESCE(
                    SUM(
                        CASE
                            WHEN p.status = 'approved' THEN p.amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS total_paid,
                COUNT(
                    CASE
                        WHEN p.status = 'approved' THEN 1
                    END
                ) AS payment_count
            FROM users u
            LEFT JOIN payments p ON u.user_id = p.user_id
            GROUP BY u.user_id, u.telegram_id, u.phone_number, u.full_name,
                     u.address, u.created_at, u.balance, u.total_spent
            ORDER BY total_paid DESC
            LIMIT 100
        """)
        members_list = fetch_all(cursor)

        cursor.execute("""
            SELECT
                u.user_id,
                u.telegram_id,
                u.phone_number,
                u.full_name,
                COUNT(DISTINCT t.ticket_id) AS ticket_count,
                COALESCE(
                    SUM(
                        CASE
                            WHEN p.status = 'approved' THEN p.amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS total_paid
            FROM users u
            JOIN tickets t ON u.user_id = t.user_id
            LEFT JOIN payments p ON u.user_id = p.user_id
            WHERE t.status = 'sold'
            GROUP BY u.user_id, u.telegram_id, u.phone_number, u.full_name
            ORDER BY ticket_count DESC
            LIMIT 100
        """)
        ticket_buyers = fetch_all(cursor)

        cursor.execute("""
            SELECT
                DATE(created_at) AS date,
                COUNT(*) AS payments_count,
                COALESCE(SUM(amount), 0) AS total_amount
            FROM payments
            WHERE status = 'approved'
              AND created_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
        daily_stats = fetch_all(cursor)

        return {
            "total_members": total_members,
            "paid_users": paid_users,
            "unpaid_users": unpaid_users,
            "total_payment": float(total_payment or 0),
            "payment_status_counts": payment_status_counts,
            "tickets_sold": tickets_sold,
            "tickets_pending": tickets_pending,
            "tickets_available": tickets_available,
            "tickets_refunded": tickets_refunded,
            "recent_payments": recent_payments,
            "members_list": members_list,
            "ticket_buyers": ticket_buyers,
            "daily_stats": daily_stats,
            "database_connected": True,
            "last_updated": datetime.now().isoformat(),
        }

    except Exception as exc:
        logger.exception("Error getting dashboard metrics: %s", exc)
        return get_empty_metrics()
    finally:
        safe_close(conn)


# ============================================================
# WEBAPP
# ============================================================

@app.route("/")
def serve_webapp():
    try:
        return send_from_directory(BASE_DIR, "index.html")
    except Exception as exc:
        logger.exception("WebApp error: %s", exc)
        return jsonify({"success": False, "error": "WebApp not found"}), 404


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
    except Exception as exc:
        logger.exception("Admin dashboard error: %s", exc)
        return render_template(
            "dashboard.html",
            metrics=get_empty_metrics(),
            server_status="failed",
            error_message=str(exc),
        )


@app.route("/assets/<path:path>")
def serve_assets(path):
    try:
        return send_from_directory(os.path.join(BASE_DIR, "assets"), path)
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 404


# ============================================================
# USER API - COMPLETE FIXED
# ============================================================

@app.route("/api/user/<int:telegram_id>", methods=["GET"])
def api_get_user(telegram_id):
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                "success": False, 
                "error": "Database connection failed"
            }), 500

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get user by telegram_id
        cursor.execute("""
            SELECT
                user_id,
                telegram_id,
                COALESCE(full_name, 'User') AS full_name,
                COALESCE(phone_number, 'N/A') AS phone_number,
                COALESCE(address, 'N/A') AS address,
                COALESCE(balance, 0) AS balance,
                COALESCE(total_spent, 0) AS total_spent,
                created_at AS registration_date,
                language
            FROM users
            WHERE telegram_id = %s
            LIMIT 1
        """, (telegram_id,))
        
        user = cursor.fetchone()
        
        # If user not found, return default data with is_registered=False
        if not user:
            return jsonify({
                "success": True,
                "data": {
                    "telegram_id": telegram_id,
                    "full_name": "User",
                    "phone_number": "N/A",
                    "address": "N/A",
                    "balance": 0,
                    "total_spent": 0,
                    "tickets": [],
                    "payments": [],
                    "ticket_count": 0,
                    "is_registered": False,
                    "registration_date": None
                }
            }), 200

        # Get user tickets
        cursor.execute("""
            SELECT
                ticket_id,
                ticket_number,
                status,
                assigned_at
            FROM tickets
            WHERE telegram_id = %s
            ORDER BY ticket_number
        """, (telegram_id,))
        tickets = fetch_all(cursor)

        # Get user payments
        cursor.execute("""
            SELECT
                payment_id,
                ticket_number,
                COALESCE(amount, 3000) AS amount,
                status,
                extracted_ref,
                created_at AS date
            FROM payments
            WHERE telegram_id = %s
            ORDER BY created_at DESC
            LIMIT 50
        """, (telegram_id,))
        payments = fetch_all(cursor)

        return jsonify({
            "success": True,
            "data": {
                "user_id": user.get("user_id"),
                "telegram_id": user.get("telegram_id"),
                "full_name": user.get("full_name") or "User",
                "phone_number": user.get("phone_number") or "N/A",
                "address": user.get("address") or "N/A",
                "balance": float(user.get("balance") or 0),
                "total_spent": float(user.get("total_spent") or 0),
                "tickets": tickets,
                "payments": payments,
                "ticket_count": len(tickets),
                "registration_date": user.get("registration_date"),
                "is_registered": True
            }
        }), 200

    except Exception as exc:
        logger.exception("Error getting user: %s", exc)
        return jsonify({
            "success": False, 
            "error": str(exc),
            "data": {
                "telegram_id": telegram_id,
                "full_name": "User",
                "phone_number": "N/A",
                "address": "N/A",
                "balance": 0,
                "total_spent": 0,
                "tickets": [],
                "payments": [],
                "ticket_count": 0,
                "is_registered": False
            }
        }), 200
    finally:
        safe_close(conn)


# ============================================================
# CREATE USER
# ============================================================

@app.route("/api/user/create", methods=["POST"])
def api_create_user():
    conn = None
    try:
        data = request.get_json(silent=True) or {}
        telegram_id = data.get("telegram_id")
        phone_number = data.get("phone_number")
        address = data.get("address")
        full_name = data.get("full_name") or "User"

        if not telegram_id:
            return jsonify({"success": False, "error": "Telegram ID is required"}), 400
        if not phone_number:
            return jsonify({"success": False, "error": "Phone number is required"}), 400
        if not address:
            return jsonify({"success": False, "error": "Address is required"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT user_id FROM users WHERE telegram_id = %s LIMIT 1
        """, (telegram_id,))
        existing = cursor.fetchone()

        if existing:
            return jsonify({"success": False, "error": "User already exists"}), 400

        cursor.execute("""
            INSERT INTO users (telegram_id, phone_number, address, full_name, language)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING user_id
        """, (telegram_id, phone_number, address, full_name, "en"))
        user_id = cursor.fetchone()["user_id"]
        conn.commit()

        return jsonify({
            "success": True, 
            "user_id": user_id, 
            "message": "User created successfully"
        })

    except Exception as exc:
        if conn:
            conn.rollback()
        logger.exception("Error creating user: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        safe_close(conn)


# ============================================================
# TICKETS
# ============================================================

@app.route("/api/tickets", methods=["GET"])
def api_get_tickets():
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT ticket_id, ticket_number, status
            FROM tickets
            ORDER BY ticket_number
        """)
        tickets = fetch_all(cursor)

        cursor.execute("SELECT COUNT(*) AS total FROM tickets")
        total_slots = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS available FROM tickets WHERE status = 'available'")
        available = cursor.fetchone()["available"]

        return jsonify({
            "success": True,
            "data": {
                "total_slots": total_slots,
                "available": available,
                "price": 3000,
                "tickets": tickets,
            }
        })

    except Exception as exc:
        logger.exception("Error getting tickets: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        safe_close(conn)


# ============================================================
# RESERVE TICKETS
# ============================================================

@app.route("/api/tickets/assign", methods=["POST"])
def api_assign_ticket():
    conn = None
    try:
        data = request.get_json(silent=True) or {}
        telegram_id = data.get("telegram_id")
        ticket_ids = data.get("ticket_ids") or []

        if not telegram_id:
            return jsonify({"success": False, "error": "Telegram ID is required"}), 400
        if not ticket_ids:
            return jsonify({"success": False, "error": "No tickets selected"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT user_id, phone_number FROM users WHERE telegram_id = %s LIMIT 1
        """, (telegram_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404

        user_id = user["user_id"]
        phone = user["phone_number"]

        assigned = []
        failed = []

        for ticket_id in ticket_ids:
            cursor.execute("""
                UPDATE tickets
                SET status = 'pending', user_id = %s, telegram_id = %s, phone_number = %s
                WHERE ticket_id = %s AND status = 'available'
            """, (user_id, telegram_id, phone, ticket_id))

            if cursor.rowcount == 1:
                assigned.append(ticket_id)
            else:
                failed.append(ticket_id)

        conn.commit()

        return jsonify({
            "success": True,
            "assigned": assigned,
            "failed": failed,
            "message": f"{len(assigned)} tickets reserved, {len(failed)} failed"
        })

    except Exception as exc:
        if conn:
            conn.rollback()
        logger.exception("Error assigning tickets: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        safe_close(conn)


# ============================================================
# CREATE PAYMENT
# ============================================================

@app.route("/api/payments/create", methods=["POST"])
def api_create_payment():
    conn = None
    try:
        data = request.get_json(silent=True) or {}

        telegram_id = data.get("telegram_id")
        ticket_id = data.get("ticket_id")
        extracted_ref = (data.get("extracted_ref") or "").strip()
        raw_sms = (data.get("raw_sms") or extracted_ref or "")
        screenshot_data = (data.get("screenshot_data") or "")

        try:
            extracted_amount = float(data.get("extracted_amount") or 3000)
        except (TypeError, ValueError):
            extracted_amount = 3000

        if not telegram_id:
            return jsonify({"success": False, "error": "Telegram ID is required"}), 400
        if not ticket_id:
            return jsonify({"success": False, "error": "Ticket ID is required"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Get user
        cursor.execute("""
            SELECT user_id, telegram_id, phone_number, full_name
            FROM users
            WHERE telegram_id = %s
            LIMIT 1
        """, (telegram_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"success": False, "error": "User not found. Please register first."}), 404

        user_id = user["user_id"]

        # Lock ticket
        cursor.execute("""
            SELECT ticket_id, ticket_number, status, user_id, telegram_id
            FROM tickets
            WHERE ticket_id = %s
            FOR UPDATE
        """, (ticket_id,))
        ticket = cursor.fetchone()

        if not ticket:
            return jsonify({"success": False, "error": "Ticket not found"}), 404

        ticket_number = ticket["ticket_number"]
        ticket_status = ticket["status"]

        if ticket_status == "available":
            cursor.execute("""
                UPDATE tickets
                SET status = 'pending', user_id = %s, telegram_id = %s, phone_number = %s
                WHERE ticket_id = %s AND status = 'available'
            """, (user_id, telegram_id, user["phone_number"], ticket_id))

            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify({"success": False, "error": "Ticket was just taken by another user"}), 409

        elif ticket_status == "pending" and ticket["user_id"] == user_id:
            pass
        else:
            conn.rollback()
            return jsonify({"success": False, "error": f"Ticket #{ticket_number} is no longer available"}), 409

        # Check duplicate pending payment
        cursor.execute("""
            SELECT payment_id FROM payments
            WHERE ticket_id = %s AND status = 'pending'
            LIMIT 1
        """, (ticket_id,))
        existing_payment = cursor.fetchone()

        if existing_payment:
            conn.rollback()
            return jsonify({
                "success": False,
                "error": "A pending payment already exists for this ticket.",
                "payment_id": existing_payment["payment_id"]
            }), 409

        # Create payment
        cursor.execute("""
            INSERT INTO payments (
                user_id, telegram_id, phone_number, full_name,
                ticket_id, ticket_number, amount,
                raw_sms, extracted_ref, extracted_amount, extracted_date,
                status, screenshot_data
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, CURRENT_TIMESTAMP,
                'pending', %s
            )
            RETURNING payment_id
        """, (
            user_id,
            telegram_id,
            user["phone_number"],
            user["full_name"],
            ticket_id,
            ticket_number,
            extracted_amount,
            raw_sms,
            extracted_ref,
            extracted_amount,
            screenshot_data,
        ))

        payment_id = cursor.fetchone()["payment_id"]
        conn.commit()

        logger.info("Payment %s created for ticket %s", payment_id, ticket_number)

        return jsonify({
            "success": True,
            "payment_id": payment_id,
            "ticket_id": ticket_id,
            "ticket_number": ticket_number,
            "status": "pending",
            "message": "Payment submitted successfully and is waiting for admin approval."
        })

    except Exception as exc:
        if conn:
            conn.rollback()
        logger.exception("ERROR /api/payments/create: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        safe_close(conn)


# ============================================================
# PENDING PAYMENTS
# ============================================================

@app.route("/api/payments/pending", methods=["GET"])
def api_pending_payments():
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT
                p.payment_id,
                p.user_id,
                p.telegram_id,
                p.phone_number,
                p.full_name,
                p.ticket_id,
                p.ticket_number,
                p.amount,
                p.raw_sms,
                p.extracted_ref,
                p.extracted_amount,
                p.extracted_date,
                p.status,
                p.admin_notes,
                p.created_at,
                u.full_name as user_name,
                CASE
                    WHEN p.screenshot_data IS NOT NULL AND p.screenshot_data <> ''
                    THEN TRUE
                    ELSE FALSE
                END AS has_screenshot
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.user_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at ASC
        """)
        payments = fetch_all(cursor)

        return jsonify({
            "success": True,
            "count": len(payments),
            "payments": payments
        })

    except Exception as exc:
        logger.exception("ERROR /api/payments/pending: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        safe_close(conn)


# ============================================================
# PAYMENT SCREENSHOT
# ============================================================

@app.route("/api/payments/<int:payment_id>/screenshot", methods=["GET"])
def api_payment_screenshot(payment_id):
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor()
        cursor.execute("SELECT screenshot_data FROM payments WHERE payment_id = %s", (payment_id,))
        result = cursor.fetchone()

        if not result or not result[0]:
            return jsonify({"success": False, "error": "No screenshot found"}), 404

        screenshot = result[0]

        if isinstance(screenshot, str):
            if "," in screenshot:
                screenshot = screenshot.split(",", 1)[1]
            image_data = base64.b64decode(screenshot)
        else:
            image_data = base64.b64decode(screenshot)

        return send_file(
            io.BytesIO(image_data),
            mimetype="image/jpeg",
            as_attachment=False,
            download_name=f"payment_{payment_id}.jpg"
        )

    except Exception as exc:
        logger.exception("Screenshot error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        safe_close(conn)


# ============================================================
# APPROVE / REJECT PAYMENT
# ============================================================

@app.route("/api/payments/verify", methods=["POST"])
def api_verify_payment():
    conn = None
    try:
        data = request.get_json(silent=True) or {}

        payment_id = data.get("payment_id")
        status = (data.get("status") or "approved").lower()
        admin_id = data.get("admin_id")
        notes = data.get("notes") or ""

        if not payment_id:
            return jsonify({"success": False, "error": "Payment ID is required"}), 400

        if status not in ("approved", "rejected"):
            return jsonify({"success": False, "error": "Status must be approved or rejected"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT
                payment_id, user_id, telegram_id,
                ticket_id, ticket_number, amount, status
            FROM payments
            WHERE payment_id = %s
            FOR UPDATE
        """, (payment_id,))
        payment = cursor.fetchone()

        if not payment:
            conn.rollback()
            return jsonify({"success": False, "error": "Payment not found"}), 404

        if payment["status"] != "pending":
            conn.rollback()
            return jsonify({"success": False, "error": f"Payment is already {payment['status']}"}), 409

        ticket_id = payment["ticket_id"]
        ticket_number = payment["ticket_number"]
        user_id = payment["user_id"]
        amount = float(payment["amount"] or 3000)

        if status == "approved":
            cursor.execute("""
                SELECT ticket_id, status, user_id
                FROM tickets
                WHERE ticket_id = %s
                FOR UPDATE
            """, (ticket_id,))
            ticket = cursor.fetchone()

            if not ticket:
                conn.rollback()
                return jsonify({"success": False, "error": "Ticket not found"}), 404

            if ticket["status"] != "pending" or ticket["user_id"] != user_id:
                conn.rollback()
                return jsonify({"success": False, "error": f"Ticket #{ticket_number} is not pending for this user"}), 409

            cursor.execute("""
                UPDATE tickets
                SET status = 'sold', assigned_at = CURRENT_TIMESTAMP
                WHERE ticket_id = %s AND status = 'pending'
            """, (ticket_id,))

            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify({"success": False, "error": "Could not finalize ticket"}), 409

            cursor.execute("""
                UPDATE payments
                SET status = 'approved', verified_by = %s, verified_at = CURRENT_TIMESTAMP, admin_notes = %s
                WHERE payment_id = %s AND status = 'pending'
            """, (admin_id, notes, payment_id))

            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify({"success": False, "error": "Could not approve payment"}), 409

            cursor.execute("""
                UPDATE users
                SET balance = COALESCE(balance, 0) + %s,
                    total_spent = COALESCE(total_spent, 0) + %s
                WHERE user_id = %s
            """, (amount, amount, user_id))

        else:
            cursor.execute("""
                SELECT status, user_id
                FROM tickets
                WHERE ticket_id = %s
                FOR UPDATE
            """, (ticket_id,))
            ticket = cursor.fetchone()

            if ticket and ticket["status"] == "pending" and ticket["user_id"] == user_id:
                cursor.execute("""
                    UPDATE tickets
                    SET status = 'available', user_id = NULL, telegram_id = NULL,
                        phone_number = NULL, full_name = NULL, assigned_at = NULL
                    WHERE ticket_id = %s AND status = 'pending'
                """, (ticket_id,))

            cursor.execute("""
                UPDATE payments
                SET status = 'rejected', verified_by = %s, verified_at = CURRENT_TIMESTAMP, admin_notes = %s
                WHERE payment_id = %s AND status = 'pending'
            """, (admin_id, notes, payment_id))

            if cursor.rowcount != 1:
                conn.rollback()
                return jsonify({"success": False, "error": "Could not reject payment"}), 409

        conn.commit()

        logger.info("Payment %s -> %s", payment_id, status)

        return jsonify({
            "success": True,
            "payment_id": payment_id,
            "ticket_number": ticket_number,
            "status": status,
            "message": f"Payment #{payment_id} {status} successfully."
        })

    except Exception as exc:
        if conn:
            conn.rollback()
        logger.exception("ERROR /api/payments/verify: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        safe_close(conn)


# ============================================================
# PAYMENT ACCOUNTS
# ============================================================

@app.route("/api/payment_accounts", methods=["GET"])
def api_payment_accounts():
    accounts = [
        {"name": "CBE", "account": "1000786684491"},
        {"name": "Abyssinia", "account": "264517826"},
        {"name": "Telebirr", "account": "0979774444"}
    ]
    return jsonify({"success": True, "data": accounts})


# ============================================================
# PRIZES
# ============================================================

@app.route("/api/prizes", methods=["GET"])
def api_get_prizes():
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT prize_position, prize_name, prize_description, prize_value
            FROM prizes
            WHERE is_active = TRUE
            ORDER BY prize_position
        """)
        prizes = fetch_all(cursor)

        return jsonify({"success": True, "data": prizes})

    except Exception as exc:
        logger.exception("Prize error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        safe_close(conn)


# ============================================================
# REFUND REQUEST
# ============================================================

@app.route("/api/refund_request", methods=["POST"])
def api_refund_request():
    conn = None
    try:
        data = request.get_json(silent=True) or {}
        telegram_id = data.get("telegram_id")
        reason = data.get("reason") or ""

        if not telegram_id:
            return jsonify({"success": False, "error": "Telegram ID is required"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500

        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT user_id, telegram_id, phone_number, balance
            FROM users
            WHERE telegram_id = %s
            LIMIT 1
        """, (telegram_id,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404

        balance = float(user["balance"] or 0)

        if balance <= 0:
            return jsonify({"success": False, "error": "No balance to refund"}), 400

        cursor.execute("""
            SELECT payment_id, ticket_id, ticket_number, amount
            FROM payments
            WHERE telegram_id = %s AND status = 'approved'
            ORDER BY created_at DESC
            LIMIT 1
        """, (telegram_id,))
        payment = cursor.fetchone()

        if not payment:
            return jsonify({"success": False, "error": "No approved payment was found."}), 400

        amount = min(balance, float(payment["amount"] or 0))

        cursor.execute("""
            INSERT INTO refunds (
                user_id, telegram_id, phone_number,
                ticket_id, ticket_number, payment_id,
                refund_amount, refund_reason, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        """, (
            user["user_id"],
            user["telegram_id"],
            user["phone_number"],
            payment["ticket_id"],
            payment["ticket_number"],
            payment["payment_id"],
            amount,
            reason,
        ))

        conn.commit()

        return jsonify({"success": True, "message": "Refund request submitted"})

    except Exception as exc:
        if conn:
            conn.rollback()
        logger.exception("Refund error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        safe_close(conn)


# ============================================================
# METRICS
# ============================================================

@app.route("/api/metrics", methods=["GET"])
def api_metrics():
    return jsonify(get_dashboard_metrics())


@app.route("/api/refresh", methods=["GET"])
def refresh_database_data():
    return jsonify({"status": "success", "data": get_dashboard_metrics()})


# ============================================================
# STATUS
# ============================================================

@app.route("/api/status", methods=["GET"])
def api_status():
    conn = get_db_connection()
    if not conn:
        return jsonify({
            "status": "running",
            "database_connected": False,
            "timestamp": datetime.now().isoformat()
        }), 503

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return jsonify({
            "status": "running",
            "database_connected": True,
            "database": "PostgreSQL",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as exc:
        return jsonify({
            "status": "running",
            "database_connected": False,
            "error": str(exc),
            "timestamp": datetime.now().isoformat()
        }), 503
    finally:
        safe_close(conn)


# ============================================================
# HEALTH
# ============================================================

@app.route("/health", methods=["GET"])
def health_check():
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "unhealthy", "database": "disconnected"}), 503

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return jsonify({"status": "healthy", "database": "connected", "database_type": "PostgreSQL"})
    except Exception as exc:
        return jsonify({"status": "unhealthy", "database": "error", "error": str(exc)}), 503
    finally:
        safe_close(conn)


# ============================================================
# EXPORT REPORTS
# ============================================================

@app.route("/api/export/<report_type>", methods=["GET"])
def export_report(report_type):
    try:
        metrics = get_dashboard_metrics()

        if report_type == "members":
            data = []
            for member in metrics["members_list"]:
                data.append({
                    "Full Name": member.get("full_name") or "N/A",
                    "Telegram ID": member.get("telegram_id"),
                    "Phone Number": member.get("phone_number"),
                    "Balance": float(member.get("balance") or 0),
                    "Total Paid": float(member.get("total_paid") or 0),
                    "Payment Count": member.get("payment_count") or 0,
                })
            filename = f"members_report_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

        elif report_type == "tickets":
            data = []
            for buyer in metrics["ticket_buyers"]:
                data.append({
                    "Name": buyer.get("full_name") or "N/A",
                    "Phone": buyer.get("phone_number") or "N/A",
                    "Telegram ID": buyer.get("telegram_id"),
                    "Tickets": buyer.get("ticket_count") or 0,
                    "Total Paid": float(buyer.get("total_paid") or 0),
                })
            filename = f"ticket_buyers_report_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

        elif report_type == "financial":
            data = []
            for payment in metrics["recent_payments"]:
                data.append({
                    "Payment ID": payment.get("payment_id"),
                    "Reference": payment.get("extracted_ref") or "N/A",
                    "Amount": float(payment.get("amount") or 0),
                    "Status": payment.get("status"),
                    "Ticket": payment.get("ticket_number"),
                    "Telegram ID": payment.get("telegram_id"),
                    "Date": payment.get("created_at"),
                })
            filename = f"financial_report_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

        else:
            return jsonify({
                "success": False,
                "error": "Invalid report type. Use members, tickets, or financial."
            }), 400

        df = pd.DataFrame(data)
        output = io.BytesIO()
        df.to_excel(output, index=False, engine="openpyxl")
        output.seek(0)

        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename,
        )

    except Exception as exc:
        logger.exception("Export error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ============================================================
# APPLICATION OBJECT
# ============================================================

application = app


# ============================================================
# START SERVER
# ============================================================

def start_dashboard():
    logger.info("📊 Starting Siket Ekub Dashboard...")
    logger.info("🌐 Admin: /admin")
    logger.info("🌐 WebApp: /")
    logger.info("🗄️ Database: PostgreSQL")

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    start_dashboard()
