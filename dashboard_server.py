# dashboard_server.py - Updated with WebApp at root
import csv
import io
import os
import sqlite3
import sys
import json
import base64
from datetime import datetime
from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory, redirect
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

DB_NAME = os.path.join(BASE_DIR, 'instance', 'siket_ekub.db')

def get_db_connection():
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

def row_to_dict(row):
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}

def get_empty_metrics():
    return {
        "total_members": 0,
        "paid_users": 0,
        "unpaid_users": 0,
        "total_payment": 0,
        "payment_status_counts": {},
        "tickets_sold": 0,
        "tickets_available": 0,
        "tickets_refunded": 0,
        "recent_payments": [],
        "members_list": [],
        "ticket_buyers": [],
        "daily_stats": [],
        "db_exists": os.path.exists(DB_NAME),
        "last_updated": datetime.now().isoformat()
    }

def get_dashboard_metrics():
    try:
        conn = get_db_connection()
        if not conn:
            return get_empty_metrics()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM users")
        result = cursor.fetchone()
        total_members = result["count"] if result else 0

        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) as count 
            FROM payments 
            WHERE status = 'approved'
        """)
        result = cursor.fetchone()
        paid_users = result["count"] if result else 0

        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM users 
            WHERE user_id NOT IN (
                SELECT DISTINCT user_id FROM payments WHERE status = 'approved'
            )
        """)
        result = cursor.fetchone()
        unpaid_users = result["count"] if result else 0

        cursor.execute("""
            SELECT COALESCE(SUM(extracted_amount), 0) as total 
            FROM payments 
            WHERE status = 'approved'
        """)
        result = cursor.fetchone()
        total_payment = result["total"] if result else 0.0

        cursor.execute("""
            SELECT status, COUNT(*) as count 
            FROM payments 
            GROUP BY status
        """)
        payment_status_counts = {}
        for row in cursor.fetchall():
            payment_status_counts[row["status"]] = row["count"]

        cursor.execute("SELECT COUNT(*) as count FROM tickets WHERE status = 'sold'")
        result = cursor.fetchone()
        tickets_sold = result["count"] if result else 0

        cursor.execute("SELECT COUNT(*) as count FROM tickets WHERE status = 'available'")
        result = cursor.fetchone()
        tickets_available = result["count"] if result else 0

        cursor.execute("SELECT COUNT(*) as count FROM tickets WHERE status = 'refunded'")
        result = cursor.fetchone()
        tickets_refunded = result["count"] if result else 0

        cursor.execute("""
            SELECT p.payment_id, p.extracted_ref, u.telegram_id, u.phone_number, u.full_name,
                   p.extracted_amount, p.extracted_date, p.status, p.created_at,
                   t.ticket_number, p.screenshot_data
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.user_id
            LEFT JOIN tickets t ON p.ticket_id = t.ticket_id
            ORDER BY p.payment_id DESC
            LIMIT 10
        """)
        recent_payments = [row_to_dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT 
                u.user_id,
                u.telegram_id,
                u.phone_number,
                u.full_name,
                u.address,
                u.registration_date,
                COALESCE(u.balance, 0) as balance,
                COALESCE(SUM(CASE WHEN p.status = 'approved' THEN p.extracted_amount ELSE 0 END), 0) as total_paid,
                COUNT(CASE WHEN p.status = 'approved' THEN 1 END) as payment_count
            FROM users u
            LEFT JOIN payments p ON u.user_id = p.user_id
            GROUP BY u.user_id
            ORDER BY total_paid DESC
            LIMIT 50
        """)
        members_list = [row_to_dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT 
                u.telegram_id,
                u.phone_number,
                u.full_name,
                COUNT(t.ticket_id) as ticket_count,
                COALESCE(SUM(p.extracted_amount), 0) as total_paid
            FROM users u
            JOIN tickets t ON u.user_id = t.user_id
            LEFT JOIN payments p ON u.user_id = p.user_id AND p.status = 'approved'
            WHERE t.status = 'sold'
            GROUP BY u.user_id
            ORDER BY ticket_count DESC
            LIMIT 50
        """)
        ticket_buyers = [row_to_dict(row) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as payments_count,
                COALESCE(SUM(extracted_amount), 0) as total_amount
            FROM payments
            WHERE status = 'approved'
            AND created_at >= DATE('now', '-7 days')
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
        daily_stats = [row_to_dict(row) for row in cursor.fetchall()]

        conn.close()

        return {
            "total_members": total_members,
            "paid_users": paid_users,
            "unpaid_users": unpaid_users,
            "total_payment": total_payment,
            "payment_status_counts": payment_status_counts,
            "tickets_sold": tickets_sold,
            "tickets_available": tickets_available,
            "tickets_refunded": tickets_refunded,
            "recent_payments": recent_payments,
            "members_list": members_list,
            "ticket_buyers": ticket_buyers,
            "daily_stats": daily_stats,
            "db_exists": os.path.exists(DB_NAME),
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"Error getting metrics: {e}")
        return get_empty_metrics()

# =====================================================
# FLASK ROUTES - WebApp at Root, Admin at /admin
# =====================================================

@app.route('/')
def serve_webapp():
    """Serve the main WebApp at root URL"""
    try:
        return send_from_directory('.', 'index.html')
    except Exception as e:
        print(f"Error serving webapp: {e}")
        return "WebApp not found", 404

@app.route('/webapp')
@app.route('/webapp/')
def webapp_alt():
    """Alternative webapp route"""
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin_dashboard():
    """Serve the admin dashboard at /admin"""
    try:
        metrics = get_dashboard_metrics()
        return render_template(
            "dashboard.html", 
            metrics=metrics, 
            server_status="running"
        )
    except Exception as e:
        print(f"Dashboard error: {e}")
        return render_template(
            "dashboard.html", 
            metrics=get_empty_metrics(), 
            server_status="failed", 
            error_message=str(e)
        )

@app.route('/assets/<path:path>')
def serve_assets(path):
    """Serve static assets"""
    return send_from_directory('assets', path)

# =====================================================
# API ROUTES
# =====================================================

@app.route("/api/metrics", methods=["GET"])
def api_metrics():
    try:
        metrics = get_dashboard_metrics()
        return jsonify(metrics)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/refresh", methods=["GET"])
def refresh_database_data():
    try:
        metrics = get_dashboard_metrics()
        return jsonify({"status": "success", "data": metrics})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "status": "running",
        "database_exists": os.path.exists(DB_NAME),
        "database_size": os.path.getsize(DB_NAME) if os.path.exists(DB_NAME) else 0,
        "timestamp": datetime.now().isoformat()
    })

@app.route("/health", methods=["GET"])
def health_check():
    try:
        conn = get_db_connection()
        if conn:
            conn.cursor().execute("SELECT 1 FROM users LIMIT 1")
            conn.close()
            return jsonify({'status': 'healthy', 'database': 'connected'})
        else:
            return jsonify({'status': 'unhealthy', 'database': 'disconnected'}), 500
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route("/api/export/<report_type>", methods=["GET"])
def export_report(report_type):
    try:
        metrics = get_dashboard_metrics()
        
        if report_type == "members":
            data = []
            for member in metrics.get('members_list', []):
                data.append({
                    'Full Name': member.get('full_name') or 'N/A',
                    'Telegram ID': member.get('telegram_id', 'N/A'),
                    'Phone Number': member.get('phone_number', 'N/A'),
                    'Balance': f"{member.get('balance', 0):.2f}",
                    'Total Paid': f"{member.get('total_paid', 0):.2f}",
                    'Payment Count': member.get('payment_count', 0)
                })
            df = pd.DataFrame(data)
            filename = f"members_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        elif report_type == "tickets":
            data = []
            for buyer in metrics.get('ticket_buyers', []):
                data.append({
                    'Name': buyer.get('full_name') or 'N/A',
                    'Phone': buyer.get('phone_number', 'N/A'),
                    'Tickets': buyer.get('ticket_count', 0),
                    'Total Paid': f"{buyer.get('total_paid', 0):.2f}"
                })
            df = pd.DataFrame(data)
            filename = f"ticket_buyers_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        elif report_type == "financial":
            data = []
            for payment in metrics.get('recent_payments', []):
                data.append({
                    'Ref': payment.get('extracted_ref') or 'N/A',
                    'Amount': f"{payment.get('extracted_amount', 0):.2f}",
                    'Status': payment.get('status', 'N/A'),
                    'Date': payment.get('created_at', 'N/A')
                })
            df = pd.DataFrame(data)
            filename = f"financial_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        else:
            return jsonify({"error": "Invalid report type. Use: members, tickets, or financial"}), 400
        
        output = io.BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"Export error: {e}")
        return jsonify({"error": str(e)}), 500

# =====================================================
# PAYMENT SCREENSHOT API ROUTES
# =====================================================

@app.route('/api/payments/pending', methods=['GET'])
def api_pending_payments():
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT p.payment_id, p.telegram_id, p.ticket_number, p.extracted_amount, 
                       p.created_at, p.status, u.full_name, u.phone_number,
                       p.screenshot_data
                FROM payments p
                JOIN users u ON p.user_id = u.user_id
                WHERE p.status = 'pending'
                ORDER BY p.created_at ASC
            """)
            columns = [description[0] for description in cursor.description]
            payments = [dict(zip(columns, row)) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            cursor.execute("""
                SELECT p.payment_id, p.telegram_id, p.ticket_number, p.extracted_amount, 
                       p.created_at, p.status, u.full_name, u.phone_number
                FROM payments p
                JOIN users u ON p.user_id = u.user_id
                WHERE p.status = 'pending'
                ORDER BY p.created_at ASC
            """)
            columns = [description[0] for description in cursor.description]
            payments = [dict(zip(columns, row)) for row in cursor.fetchall()]
            for payment in payments:
                payment['has_screenshot'] = False
        
        conn.close()
        return jsonify({'success': True, 'payments': payments})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/payments/<int:payment_id>/screenshot', methods=['GET'])
def api_payment_screenshot(payment_id):
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor()
        cursor.execute(
            "SELECT screenshot_data FROM payments WHERE payment_id = ?",
            (payment_id,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if not result or not result[0]:
            return jsonify({'error': 'No screenshot found'}), 404
        
        image_data = base64.b64decode(result[0])
        return send_file(
            io.BytesIO(image_data),
            mimetype='image/png',
            as_attachment=False,
            download_name=f'payment_{payment_id}.png'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/payments/verify', methods=['POST'])
def api_verify_payment():
    try:
        data = request.json
        payment_id = data.get('payment_id')
        status = data.get('status', 'approved')
        admin_id = data.get('admin_id', 1)
        notes = data.get('notes', '')
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE payments 
            SET status = ?, verified_by = ?, verified_at = CURRENT_TIMESTAMP, admin_notes = ?
            WHERE payment_id = ? AND status = 'pending'
        """, (status, admin_id, notes, payment_id))
        
        if cursor.rowcount > 0:
            if status == 'approved':
                cursor.execute("""
                    UPDATE users 
                    SET balance = COALESCE(balance, 0) + (
                        SELECT extracted_amount FROM payments WHERE payment_id = ?
                    )
                    WHERE user_id = (
                        SELECT user_id FROM payments WHERE payment_id = ?
                    )
                """, (payment_id, payment_id))
            conn.commit()
            conn.close()
            return jsonify({'success': True})
        
        conn.close()
        return jsonify({'error': 'Payment not found or already processed'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

application = app

def start_dashboard():
    print("📊 Starting Admin Dashboard Server...")
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)

if __name__ == "__main__":
    start_dashboard()
