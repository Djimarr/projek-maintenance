import sqlite3
import os
import requests 
import pandas as pd
from flask import Flask, render_template, g, send_from_directory, request, redirect, url_for
from collections import defaultdict
from datetime import datetime

DATABASE = 'maintenance.db'
IMAGE_DIR = 'images'
UPLOAD_FOLDER = 'uploads'
TELEGRAM_BOT_TOKEN = "7625689953:AAHNg2vnEexzW3qG3fVVmrW3fIXAV7RkdSk" # Token Bot Anda

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app = Flask(__name__)
app.secret_key = 'super_secret_key_maintenance_app'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


# --- Fungsi Kirim Notifikasi Telegram ---
def send_telegram_notification(chat_id, message):
    if not chat_id: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Gagal kirim notifikasi: {e}")

# --- Koneksi Database ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def check_db_schema():
    conn = get_db()
    try:
        conn.execute("ALTER TABLE maintenance_records ADD COLUMN ticket_status TEXT DEFAULT 'OPEN'")
        conn.execute("ALTER TABLE maintenance_records ADD COLUMN ticket_note TEXT")
        conn.execute("ALTER TABLE maintenance_records ADD COLUMN image_path TEXT")
        conn.commit()
    except sqlite3.OperationalError: pass
    
    try:
        conn.execute("SELECT * FROM support_tickets LIMIT 1")
    except sqlite3.OperationalError: pass

# --- Routes ---

@app.route('/')
def index():
    check_db_schema()
    
    # 1. Statistik Kartu
    try:
        open_maint = query_db("SELECT COUNT(*) as count FROM maintenance_records WHERE response_status = 'NOK' AND (ticket_status IS NULL OR ticket_status != 'RESOLVED')", one=True)
        open_support = query_db("SELECT COUNT(*) as count FROM support_tickets WHERE status = 'OPEN'", one=True)
        
        current_month = datetime.now().strftime('%Y-%m')
        maint_count = query_db("SELECT COUNT(*) as count FROM maintenance_sessions WHERE session_type = 'MAINTENANCE' AND strftime('%Y-%m', tanggal_tugas) = ?", [current_month], one=True)
        
        today = datetime.now().strftime('%Y-%m-%d')
        logbook_today = query_db("SELECT COUNT(*) as count FROM maintenance_sessions WHERE session_type = 'LOGBOOK' AND tanggal_tugas = ?", [today], one=True)
        
        stats = {
            'open_issues': open_maint['count'],
            'support_open': open_support['count'],
            'total_open': open_maint['count'] + open_support['count'],
            'maint_month': maint_count['count'],
            'logbook_filled': logbook_today['count'] > 0
        }
    except Exception:
        stats = {'open_issues': 0, 'support_open': 0, 'total_open': 0, 'maint_month': 0, 'logbook_filled': False}

    # 2. Tabel Kendala Alat (Maintenance)
    recent_maint_issues = query_db("""
        SELECT r.id, s.tanggal_tugas, e.name as equipment_name, p.question, r.ticket_status, s.technician_1_name
        FROM maintenance_records r
        JOIN checklist_points p ON r.point_id = p.id
        JOIN maintenance_sessions s ON r.session_id = s.id
        JOIN equipment e ON s.equipment_id = e.id
        WHERE r.response_status = 'NOK' AND (r.ticket_status IS NULL OR r.ticket_status != 'RESOLVED')
        ORDER BY s.tanggal_tugas DESC
        LIMIT 5
    """)

    # 3. Tabel Tiket Support (IT)
    recent_support_issues = query_db("""
        SELECT id, created_at, reporter_name, issue_category, issue_description, status
        FROM support_tickets
        WHERE status != 'RESOLVED'
        ORDER BY created_at DESC
        LIMIT 5
    """)

    # 2. Baca Jadwal Excel
    schedule_html = None
    schedule_path = os.path.join(app.config['UPLOAD_FOLDER'], 'current_schedule.xlsx')
    
    if os.path.exists(schedule_path):
        try:
            # Baca tanpa header agar format asli terlihat
            df = pd.read_excel(schedule_path, header=None) 
            schedule_html = df.to_html(classes='schedule-table', index=False, header=False, na_rep='')
        except Exception as e:
            schedule_html = f"<p style='color:red;'>Gagal membaca jadwal: {e}</p>"

    return render_template('index.html', stats=stats, schedule_html=schedule_html, maint_issues=recent_maint_issues, support_issues=recent_support_issues)

@app.route('/upload_schedule', methods=['GET', 'POST'])
def upload_schedule():
    if request.method == 'POST':
        if 'file' not in request.files: return redirect(request.url)
        file = request.files['file']
        if file.filename == '': return redirect(request.url)
        if file and file.filename.endswith(('.xlsx', '.xls')):
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'current_schedule.xlsx'))
            return redirect(url_for('index'))
    return render_template('upload_schedule.html')

@app.route('/logbook')
def logbook():
    filter_date = request.args.get('filter_date')
    query = "SELECT id, tanggal_tugas, shift, technician_1_name, technician_2_name, summary, image_path FROM maintenance_sessions WHERE session_type = 'LOGBOOK'"
    params = []
    if filter_date:
        query += " AND strftime('%Y-%m', tanggal_tugas) = ?"
        params.append(filter_date)
    query += " ORDER BY tanggal_tugas DESC, shift"
    
    sessions = query_db(query, params)
    logbook_data = defaultdict(lambda: {'PS': None, 'MT': None})
    for session in sessions:
        if session['shift'] in ['PS', 'MT']:
            logbook_data[session['tanggal_tugas']][session['shift']] = session
    return render_template('logbook.html', logbook_data=logbook_data, current_filter=filter_date)

@app.route('/kendala')
def kendala():
    check_db_schema()
    records = query_db("""
        SELECT r.id as record_id, s.tanggal_tugas, e.name as equipment_name, p.section, p.question, r.keterangan, r.ticket_status, r.ticket_note, s.technician_1_name, s.id as session_id
        FROM maintenance_records r
        JOIN checklist_points p ON r.point_id = p.id
        JOIN maintenance_sessions s ON r.session_id = s.id
        JOIN equipment e ON s.equipment_id = e.id
        WHERE r.response_status = 'NOK'
        ORDER BY CASE WHEN r.ticket_status = 'RESOLVED' THEN 1 ELSE 0 END, s.tanggal_tugas DESC
    """)
    return render_template('kendala.html', kendala_list=records)

@app.route('/support')
def support():
    try:
        tickets = query_db("SELECT * FROM support_tickets ORDER BY CASE WHEN status = 'OPEN' THEN 1 WHEN status = 'IN_PROGRESS' THEN 2 ELSE 3 END, created_at DESC")
    except: tickets = []
    return render_template('support.html', tickets=tickets)

@app.route('/maintenance/<int:session_id>')
def detail_maintenance(session_id):
    session = query_db("SELECT s.*, e.name as equipment_name FROM maintenance_sessions s JOIN equipment e ON s.equipment_id = e.id WHERE s.id = ?", [session_id], one=True)
    if not session: return "Not Found", 404
    records = query_db("SELECT p.section, p.question, r.response_status, r.response_value, r.keterangan FROM maintenance_records r JOIN checklist_points p ON r.point_id = p.id WHERE r.session_id = ? ORDER BY p.order_number", [session_id])
    return render_template('detail_maintenance.html', session=session, records=records)

# --- Action Routes ---

@app.route('/update_ticket/<int:record_id>', methods=['POST'])
def update_ticket(record_id):
    conn = get_db()
    conn.execute("UPDATE maintenance_records SET ticket_status = ?, ticket_note = ? WHERE id = ?", (request.form.get('status'), request.form.get('note'), record_id))
    conn.commit()
    return redirect(url_for('kendala'))

@app.route('/update_support_ticket/<int:ticket_id>', methods=['POST'])
def update_support_ticket(ticket_id):
    status = request.form.get('status')
    note = request.form.get('note')
    
    conn = get_db()
    
    # Ambil info tiket dulu untuk notifikasi
    cursor = conn.execute("SELECT reporter_chat_id, issue_description FROM support_tickets WHERE id = ?", (ticket_id,))
    ticket = cursor.fetchone()
    
    if status == 'RESOLVED':
        conn.execute("UPDATE support_tickets SET status = ?, technician_note = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?", (status, note, ticket_id))
        msg_status = "✅ *TIKET SELESAI*"
    else:
        conn.execute("UPDATE support_tickets SET status = ?, technician_note = ? WHERE id = ?", (status, note, ticket_id))
        msg_status = "⚙️ *TIKET DIPROSES*"
        
    conn.commit()
    
    # Kirim Notifikasi
    if ticket and ticket['reporter_chat_id']:
        pesan = (
            f"{msg_status}\n\n"
            f"Masalah: {ticket['issue_description']}\n"
            f"Catatan Teknisi: {note}\n"
            f"Terima kasih telah melapor."
        )
        send_telegram_notification(ticket['reporter_chat_id'], pesan)
        
    return redirect(url_for('support'))

@app.route('/delete_session/<int:session_id>', methods=['POST'])
def delete_session(session_id):
    conn = get_db()
    row = conn.execute("SELECT image_path FROM maintenance_sessions WHERE id = ?", (session_id,)).fetchone()
    conn.execute("DELETE FROM maintenance_records WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM maintenance_sessions WHERE id = ?", (session_id,))
    conn.commit()
    
    if row and row['image_path'] and os.path.exists(row['image_path']):
        try: os.remove(row['image_path'])
        except: pass
        
    if request.referrer and 'logbook' in request.referrer: return redirect(url_for('logbook'))
    return redirect(url_for('kendala'))

@app.route('/delete_ticket/<int:ticket_id>', methods=['POST'])
def delete_ticket(ticket_id):
    conn = get_db()
    row = conn.execute("SELECT image_path FROM support_tickets WHERE id = ?", (ticket_id,)).fetchone()
    conn.execute("DELETE FROM support_tickets WHERE id = ?", (ticket_id,))
    conn.commit()
    if row and row['image_path'] and os.path.exists(row['image_path']):
        try: os.remove(row['image_path'])
        except: pass
    return redirect(url_for('support'))

@app.route('/uploads/<path:filename>')
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

if __name__ == '__main__':
    app.run(debug=True, port=5001)