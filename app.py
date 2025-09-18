import sqlite3
from flask import Flask, render_template, g, send_from_directory
from collections import defaultdict

DATABASE = 'maintenance.db'
IMAGE_DIR = 'images' # Sesuaikan dengan nama folder gambar Anda

app = Flask(__name__)

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

# --- Route Utama ---

@app.route('/')
def index():
    """Halaman utama dengan navigasi."""
    return render_template('index.html')

@app.route('/logbook')
def logbook():
    """Halaman untuk menampilkan Logbook Harian seperti spreadsheet."""
    sessions = query_db("""
        SELECT id, tanggal_tugas, shift, technician_1_name, technician_2_name, summary, image_path
        FROM maintenance_sessions
        WHERE session_type = 'LOGBOOK'
        ORDER BY tanggal_tugas DESC, shift
    """)
    
    # Mengelompokkan data berdasarkan tanggal
    logbook_data = defaultdict(lambda: {'PS': None, 'MT': None})
    for session in sessions:
        if session['shift'] in ['PS', 'MT']:
            logbook_data[session['tanggal_tugas']][session['shift']] = session

    return render_template('logbook.html', logbook_data=logbook_data)

@app.route('/kendala')
def kendala():
    """Halaman untuk menampilkan semua poin maintenance yang 'NOK'."""
    kendala_records = query_db("""
        SELECT 
            s.tanggal_tugas,
            e.name as equipment_name,
            p.section,
            p.question,
            r.keterangan,
            s.technician_1_name,
            s.technician_2_name,
            s.id as session_id
        FROM maintenance_records r
        JOIN checklist_points p ON r.point_id = p.id
        JOIN maintenance_sessions s ON r.session_id = s.id
        JOIN equipment e ON s.equipment_id = e.id
        WHERE r.response_status = 'NOK'
        ORDER BY s.tanggal_tugas DESC
    """)
    return render_template('kendala.html', kendala_list=kendala_records)

@app.route('/maintenance/<int:session_id>')
def detail_maintenance(session_id):
    """Halaman untuk melihat detail lengkap satu sesi maintenance."""
    session_info = query_db("""
        SELECT s.*, e.name as equipment_name
        FROM maintenance_sessions s
        JOIN equipment e ON s.equipment_id = e.id
        WHERE s.id = ? AND s.session_type = 'MAINTENANCE'
    """, [session_id], one=True)

    records = query_db("""
        SELECT p.section, p.question, r.response_status, r.response_value, r.keterangan
        FROM maintenance_records r
        JOIN checklist_points p ON r.point_id = p.id
        WHERE r.session_id = ?
        ORDER BY p.order_number
    """, [session_id])
    
    return render_template('detail_maintenance.html', session=session_info, records=records)

@app.route('/uploads/<path:filename>')
def serve_image(filename):
    """Route untuk menyajikan file gambar yang diunggah."""
    return send_from_directory(IMAGE_DIR, filename)


if __name__ == '__main__':
    # Gunakan port yang berbeda dari bot jika dijalankan bersamaan
    app.run(debug=True, port=5001)
