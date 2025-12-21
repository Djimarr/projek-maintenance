import sqlite3
import logging
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from datetime import datetime
from fpdf import FPDF

# --- Konfigurasi ---
TOKEN = "7625689953:AAHNg2vnEexzW3qG3fVVmrW3fIXAV7RkdSk"
DATABASE_FILE = 'maintenance.db'
IMAGE_DIR = 'images'
REPORT_DIR = 'reports'
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# --- Setup Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Helper: Translate Hari ---
def get_hari_indonesia(date_obj):
    days = {
        'Monday': 'Senin', 'Tuesday': 'Selasa', 'Wednesday': 'Rabu',
        'Thursday': 'Kamis', 'Friday': 'Jumat', 'Saturday': 'Sabtu', 'Sunday': 'Minggu'
    }
    return days[date_obj.strftime('%A')]

# --- Fungsi Database & Schema ---
def db_connect():
    return sqlite3.connect(DATABASE_FILE)

def check_and_update_db_schema():
    """Memastikan struktur database lengkap untuk semua fitur"""
    conn = db_connect()
    cursor = conn.cursor()
    
    # 1. Cek kolom image_path di maintenance_records
    try:
        cursor.execute("ALTER TABLE maintenance_records ADD COLUMN image_path TEXT")
    except sqlite3.OperationalError:
        pass # Kolom sudah ada

    # 2. Cek tabel support_tickets
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_name TEXT NOT NULL,
                issue_category TEXT NOT NULL,
                issue_description TEXT NOT NULL,
                image_path TEXT,
                status TEXT DEFAULT 'OPEN',
                technician_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP
            )
        """)
    except Exception as e:
        logger.error(f"Error creating support table: {e}")

    # 3. Cek kolom reporter_chat_id 
    try:
        conn.execute("ALTER TABLE support_tickets ADD COLUMN reporter_chat_id INTEGER")
    except: pass
    
    conn.commit()
    conn.close()

# --- Class PDF Generator (Hanya untuk Maintenance/Logbook) ---
class MaintenanceReportPDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'MAINTENANCE CHECKLIST', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Halaman {self.page_no()}', 0, 0, 'C')

def print_table_header(pdf):
    pdf.set_fill_color(200, 200, 200)
    pdf.set_font('Arial', 'B', 9)
    pdf.cell(10, 10, "No", 1, 0, 'C', 1)
    pdf.cell(80, 10, "Maintenance Point", 1, 0, 'C', 1)
    pdf.cell(15, 10, "OK", 1, 0, 'C', 1)
    pdf.cell(15, 10, "NOK", 1, 0, 'C', 1)
    pdf.cell(70, 10, "Keterangan / Nilai", 1, 1, 'C', 1)

def create_pdf(session_id):
    conn = db_connect()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT s.tanggal_tugas, s.technician_1_name, s.technician_2_name, 
               e.name, s.summary, s.image_path, s.session_type, s.shift
        FROM maintenance_sessions s
        LEFT JOIN equipment e ON s.equipment_id = e.id
        WHERE s.id = ?
    """, (session_id,))
    session = cursor.fetchone()
    
    if not session:
        return None

    tanggal_str, tech1, tech2, equip_name, summary, session_image_path, session_type, shift = session
    
    date_obj = datetime.strptime(tanggal_str, '%Y-%m-%d')
    hari = get_hari_indonesia(date_obj)
    formatted_date = date_obj.strftime('%d-%m-%Y')
    
    pdf = MaintenanceReportPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    pdf.set_font('Arial', '', 10)
    
    # --- INFO HEADER ---
    tech_names = tech1
    if tech2: tech_names += f", {tech2}"

    if session_type == 'MAINTENANCE':
        pdf.cell(30, 6, "Nama Alat", 0, 0)
        pdf.cell(5, 6, ":", 0, 0)
        pdf.cell(80, 6, f"{equip_name}", 0, 1)
        pdf.cell(30, 6, "Hari / Tanggal", 0, 0)
        pdf.cell(5, 6, ":", 0, 0)
        pdf.cell(80, 6, f"{hari}, {formatted_date}", 0, 1)
        pdf.cell(30, 6, "Teknisi", 0, 0)
        pdf.cell(5, 6, ":", 0, 0)
        pdf.cell(80, 6, f"{tech_names}", 0, 1)
    else: 
        pdf.cell(30, 6, "Tipe Laporan", 0, 0)
        pdf.cell(5, 6, ":", 0, 0)
        pdf.cell(80, 6, "LOGBOOK HARIAN", 0, 1)
        pdf.cell(30, 6, "Shift", 0, 0)
        pdf.cell(5, 6, ":", 0, 0)
        pdf.cell(80, 6, f"{shift}", 0, 1)
        pdf.cell(30, 6, "Tanggal", 0, 0)
        pdf.cell(5, 6, ":", 0, 0)
        pdf.cell(80, 6, f"{hari}, {formatted_date}", 0, 1)
        pdf.cell(30, 6, "Teknisi", 0, 0)
        pdf.cell(5, 6, ":", 0, 0)
        pdf.cell(80, 6, f"{tech_names}", 0, 1)

    pdf.ln(5)

    # --- TABEL CHECKLIST (MAINTENANCE) ---
    if session_type == 'MAINTENANCE':
        print_table_header(pdf)
        
        pdf.set_font('Arial', '', 9)
        cursor.execute("""
            SELECT p.section, p.question, r.response_status, r.response_value, r.keterangan, p.order_number
            FROM maintenance_records r
            JOIN checklist_points p ON r.point_id = p.id
            WHERE r.session_id = ?
            ORDER BY p.order_number
        """, (session_id,))
        records = cursor.fetchall()
        
        current_section = ""
        no_counter = 1
        
        for section, question, status, value, ket, order in records:
            if section != current_section:
                if pdf.get_y() + 8 > 270:
                    pdf.add_page()
                    print_table_header(pdf)
                
                pdf.set_font('Arial', 'B', 9)
                pdf.set_fill_color(240, 240, 240)
                pdf.cell(190, 8, f"  {section}", 1, 1, 'L', 1)
                pdf.set_font('Arial', '', 9)
                current_section = section
            
            mark_ok = "V" if status == 'OK' else ""
            mark_nok = "V" if status == 'NOK' else ""
            final_ket = ""
            if value: final_ket += f"{value} "
            if ket: final_ket += f"({ket})"
            
            lines_quest = int(len(question) / 35) + 1
            lines_ket = int(len(final_ket) / 30) + 1
            h_row = max(6, lines_quest * 5, lines_ket * 5)
            
            if pdf.get_y() + h_row > 270:
                pdf.add_page()
                print_table_header(pdf)
            
            x_start = pdf.get_x()
            y_start = pdf.get_y()
            
            pdf.set_xy(x_start + 10, y_start)
            pdf.multi_cell(80, 5, question, border=0, align='L')
            
            pdf.set_xy(x_start + 120, y_start)
            pdf.multi_cell(70, 5, final_ket, border=0, align='L')
            
            pdf.set_xy(x_start, y_start)
            
            pdf.cell(10, h_row, str(no_counter), 1, 0, 'C')
            pdf.cell(80, h_row, "", 1, 0)
            pdf.cell(15, h_row, mark_ok, 1, 0, 'C')
            pdf.cell(15, h_row, mark_nok, 1, 0, 'C')
            pdf.cell(70, h_row, "", 1, 1)
            
            no_counter += 1

    # --- FOOTER SUMMARY ---
    pdf.ln(5)
    if pdf.get_y() + 30 > 270: pdf.add_page()
        
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(0, 6, "Catatan / Ringkasan:", 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.multi_cell(0, 6, summary if summary else "-", 1)
    
    # --- TANDA TANGAN ---
    pdf.ln(10)
    if pdf.get_y() + 40 > 270: pdf.add_page()

    pdf.cell(60, 6, "Mengetahui/Supervisor", 0, 0, 'C')
    pdf.cell(70, 6, "", 0, 0)
    pdf.cell(60, 6, "Teknisi Pelaksana", 0, 1, 'C')
    pdf.ln(20)
    pdf.cell(60, 6, "( ........................... )", 0, 0, 'C')
    pdf.cell(70, 6, "", 0, 0)
    pdf.cell(60, 6, f"( {tech1} )", 0, 1, 'C')

    # --- LAMPIRAN FOTO ---
    
    # 1. Ambil Foto dari Record (Item NOK)
    cursor.execute("""
        SELECT p.question, r.image_path 
        FROM maintenance_records r
        JOIN checklist_points p ON r.point_id = p.id
        WHERE r.session_id = ? AND r.image_path IS NOT NULL
    """, (session_id,))
    nok_images = cursor.fetchall()

    has_session_image = session_image_path and os.path.exists(session_image_path)
    
    if nok_images or has_session_image:
        pdf.add_page()
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, "LAMPIRAN FOTO KEGIATAN", 0, 1, 'C')
        pdf.ln(5)

        for question, img_path in nok_images:
            if img_path and os.path.exists(img_path):
                pdf.set_font('Arial', 'B', 10)
                pdf.cell(0, 8, f"Kendala: {question}", 0, 1, 'L')
                try:
                    pdf.image(img_path, x=15, w=100)
                    pdf.ln(5)
                except Exception as e:
                    pdf.cell(0, 10, f"Gagal memuat gambar: {e}", 0, 1)

        if has_session_image:
            pdf.ln(5)
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(0, 8, "Dokumentasi Umum:", 0, 1, 'L')
            try:
                pdf.image(session_image_path, x=15, w=150)
            except Exception as e:
                pdf.cell(0, 10, f"Gagal memuat gambar: {e}", 0, 1)

    filename = f"Laporan_{session_type}_{formatted_date}_{session_id}.pdf"
    filepath = os.path.join(REPORT_DIR, filename)
    pdf.output(filepath)
    conn.close()
    return filepath

# --- Fungsi Database CRUD ---
def start_session(tech1, tech2, tanggal, session_type, equipment_id=None, shift=None):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO maintenance_sessions (technician_1_name, technician_2_name, tanggal_tugas, session_type, equipment_id, shift) VALUES (?, ?, ?, ?, ?, ?)",
        (tech1, tech2, tanggal, session_type, equipment_id, shift)
    )
    conn.commit()
    session_id = cursor.lastrowid
    conn.close()
    return session_id

def save_support_ticket(name, chat_id, category, description, image_path):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO support_tickets (reporter_name, reporter_chat_id, issue_category, issue_description, image_path) VALUES (?, ?, ?, ?, ?)",
        (name, chat_id, category, description, image_path)
    )
    conn.commit()
    ticket_id = cursor.lastrowid
    conn.close()
    return ticket_id

def get_equipment():
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM equipment")
    result = cursor.fetchall()
    conn.close()
    return result

def get_next_question(session_id):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.section, p.question, p.input_type
        FROM checklist_points p
        JOIN maintenance_sessions s ON p.equipment_id = s.equipment_id
        WHERE s.id = ? AND p.id NOT IN (
            SELECT r.point_id FROM maintenance_records r WHERE r.session_id = ?
        )
        ORDER BY p.order_number
        LIMIT 1
    """, (session_id, session_id))
    result = cursor.fetchone()
    conn.close()
    return result

def save_response(session_id, point_id, status, value, keterangan):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO maintenance_records (session_id, point_id, response_status, response_value, keterangan) VALUES (?, ?, ?, ?, ?)",
        (session_id, point_id, status, value, keterangan)
    )
    conn.commit()
    conn.close()

def save_record_image(session_id, point_id, image_path):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE maintenance_records SET image_path = ? WHERE session_id = ? AND point_id = ?",
        (image_path, session_id, point_id)
    )
    conn.commit()
    conn.close()

def save_summary(session_id, summary):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE maintenance_sessions SET summary = ? WHERE id = ?", (summary, session_id))
    conn.commit()
    conn.close()

def save_image_path(session_id, image_path):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE maintenance_sessions SET image_path = ?, status = 'COMPLETED' WHERE id = ?", (image_path, session_id))
    conn.commit()
    conn.close()

async def finish_session_process(update: Update, context: ContextTypes.DEFAULT_TYPE, session_id, image_path=None):
    save_image_path(session_id, image_path)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text="✅ Data tersimpan. Sedang membuat laporan PDF..."
    )
    
    try:
        pdf_path = create_pdf(session_id)
        if pdf_path and os.path.exists(pdf_path):
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=open(pdf_path, 'rb'),
                filename=os.path.basename(pdf_path),
                caption="📄 Berikut adalah laporan hasil kegiatan hari ini."
            )
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Gagal membuat PDF.")
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"⚠️ Terjadi kesalahan saat membuat PDF: {e}")
    
    context.user_data.clear()

# --- HANDLERS BOT ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Selamat datang di Bot Teknis.\n\nSilakan masukkan *Nama Anda*:", parse_mode='Markdown')
    context.user_data.clear()
    context.user_data['step'] = 'input_name'

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔧 Maintenance Rutin", callback_data='menu_maintenance')],
        [InlineKeyboardButton("📓 Logbook Harian", callback_data='menu_logbook')],
        [InlineKeyboardButton("🆘 Lapor Kendala / Support IT", callback_data='menu_support')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    user_name = context.user_data.get('user_name', 'Teknisi')
    msg_text = f"Halo *{user_name}*, pilih menu:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')

async def ask_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int, session_id: int):
    question_data = get_next_question(session_id)
    if question_data:
        point_id, section, question, input_type = question_data
        context.user_data['point_id'] = point_id
        context.user_data['input_type'] = input_type
        context.user_data['step'] = 'answer_value' if input_type != 'OK/NOK' else None

        full_text = f"*{section}*\n\n{question}"

        if input_type == 'OK/NOK':
            keyboard = [
                [InlineKeyboardButton("✅ OK", callback_data=f'answer_ok_{point_id}'),
                 InlineKeyboardButton("❌ NOK", callback_data=f'answer_nok_{point_id}')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(chat_id=chat_id, text=full_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"{full_text}\n\n_(Silakan ketik jawabannya dalam format {input_type})_", parse_mode='Markdown')
    else:
        context.user_data['step'] = 'maintenance_summary'
        await context.bot.send_message(chat_id=chat_id, text="✅ Semua poin checklist telah dijawab.\n\nMasukkan keterangan akhir / ringkasan maintenance:")

async def request_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text):
    keyboard = [[InlineKeyboardButton("Lewati Foto / Selesai", callback_data='skip_photo')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(message_text, reply_markup=reply_markup)
    elif update.callback_query:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup)

# --- Button Callback Handler ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # --- MENU UTAMA ---
    if data == 'menu_maintenance':
        context.user_data['session_type'] = 'MAINTENANCE'
        context.user_data['tech1'] = context.user_data.get('user_name')
        context.user_data['step'] = 'technician_2'
        await query.edit_message_text("🔧 *Menu Maintenance* Dipilih.\nMasukkan *Nama Teknisi 2* (Ketik '-' jika sendiri):", parse_mode='Markdown')
    
    elif data == 'menu_logbook':
        context.user_data['session_type'] = 'LOGBOOK'
        context.user_data['tech1'] = context.user_data.get('user_name')
        context.user_data['step'] = 'technician_2'
        await query.edit_message_text("📓 *Menu Logbook* Dipilih.\nMasukkan *Nama Teknisi 2* (Ketik '-' jika sendiri):", parse_mode='Markdown')

    elif data == 'menu_support':
        context.user_data['step'] = 'support_category'
        keyboard = [
            [InlineKeyboardButton("🖥️ Hardware", callback_data='cat_hardware')],
            [InlineKeyboardButton("💾 Software", callback_data='cat_software')],
            [InlineKeyboardButton("🌐 Jaringan", callback_data='cat_network')],
            [InlineKeyboardButton("❓ Lainnya", callback_data='cat_other')]
        ]
        await query.edit_message_text("🆘 *Support IT* Dipilih.\nPilih Kategori Masalah:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    # --- SUPPORT FLOW ---
    elif data.startswith('cat_'):
        category_map = {'cat_hardware': 'Hardware', 'cat_software': 'Software', 'cat_network': 'Jaringan', 'cat_other': 'Lainnya'}
        context.user_data['support_category'] = category_map[data]
        context.user_data['step'] = 'support_desc'
        await query.edit_message_text(f"Kategori: *{category_map[data]}*\n\nSilakan jelaskan detail kendala/kerusakan:", parse_mode='Markdown')
    
    elif data == 'skip_support_photo':
        name = context.user_data.get('user_name')
        chat_id = update.effective_chat.id # Ambil ID Chat
        cat = context.user_data.get('support_category')
        desc = context.user_data.get('support_desc')
        ticket_id = save_support_ticket(name, cat, desc, None)
        await query.edit_message_text(f"✅ Tiket Support #{ticket_id} berhasil dibuat!\nTim teknisi akan segera menindaklanjuti.")
        context.user_data.clear()

    # --- MAINTENANCE/LOGBOOK FLOW ---
    elif data == 'use_today_date':
        today_str = context.user_data.get('temp_today_date')
        context.user_data['tanggal'] = today_str
        
        # Branching berdasarkan tipe sesi awal
        if context.user_data.get('session_type') == 'MAINTENANCE':
             context.user_data['step'] = 'equipment'
             equipment_list = get_equipment()
             keyboard = [[InlineKeyboardButton(name, callback_data=f'equip_{eid}')] for eid, name in equipment_list]
             reply_markup = InlineKeyboardMarkup(keyboard)
             await query.edit_message_text("Pilih *Peralatan* yang akan di-maintenance:", reply_markup=reply_markup, parse_mode='Markdown')
        else: # LOGBOOK
             context.user_data['step'] = 'choose_shift'
             keyboard = [[InlineKeyboardButton("PS", callback_data='shift_PS')], [InlineKeyboardButton("MT", callback_data='shift_MT')]]
             await query.edit_message_text("Pilih *Shift* Anda:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data == 'change_date_manual':
        context.user_data['step'] = 'manual_date_input'
        await query.edit_message_text("Silakan ketik tanggal tugas (format YYYY-MM-DD):")

    elif data.startswith('shift_'):
        shift = data.split('_')[1]
        context.user_data['shift'] = shift
        session_id = start_session(
            context.user_data['tech1'],
            context.user_data['tech2'],
            context.user_data['tanggal'],
            'LOGBOOK',
            equipment_id=None,
            shift=shift
        )
        context.user_data['session_id'] = session_id
        context.user_data['step'] = 'logbook_keterangan'
        await query.edit_message_text(f"Shift *{shift}* dipilih.\n\nMasukkan keterangan shift harian Anda:", parse_mode='Markdown')

    elif data.startswith('equip_'):
        equipment_id = int(data.split('_')[1])
        session_id = start_session(
            context.user_data['tech1'],
            context.user_data['tech2'],
            context.user_data['tanggal'],
            'MAINTENANCE',
            equipment_id=equipment_id
        )
        context.user_data['session_id'] = session_id
        await query.edit_message_text("Memulai maintenance untuk peralatan yang dipilih...")
        await ask_question(context, chat_id, session_id)

    elif data.startswith('answer_'):
        parts = data.split('_')
        status = parts[1].upper()
        point_id = int(parts[2])
        session_id = context.user_data.get('session_id')

        if status == 'NOK':
            context.user_data['pending_nok'] = point_id
            context.user_data['step'] = 'nok_keterangan'
            await context.bot.send_message(chat_id=chat_id, text="Anda memilih NOK. Masukkan keterangan untuk poin ini:")
        else:
            save_response(session_id, point_id, status, None, None)
            await query.edit_message_text(f"Jawaban 'OK' tersimpan.")
            await ask_question(context, chat_id, session_id)

    elif data == 'skip_nok_photo':
        session_id = context.user_data.get('session_id')
        await query.edit_message_text("Foto dilewati.")
        context.user_data['step'] = None
        await ask_question(context, chat_id, session_id)

    elif data == 'skip_photo':
        session_id = context.user_data.get('session_id')
        await query.edit_message_text("Foto dilewati.")
        await finish_session_process(update, context, session_id, image_path=None)


# --- Text Handler ---
async def handle_text_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text

    if step == 'input_name':
        context.user_data['user_name'] = text
        await show_main_menu(update, context)
        return

    # --- SUPPORT FLOW ---
    if step == 'support_desc':
        context.user_data['support_desc'] = text
        context.user_data['step'] = 'support_photo'
        keyboard = [[InlineKeyboardButton("Lewati Foto", callback_data='skip_support_photo')]]
        await update.message.reply_text("Deskripsi tersimpan. Kirimkan *Foto Kendala* (atau klik Lewati):", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # --- MAINTENANCE/LOGBOOK PRE-SESSION ---
    if step == 'technician_2':
        tech2_input = text
        context.user_data['tech2'] = tech2_input if tech2_input != '-' else ""
        
        today = datetime.now()
        today_str = today.strftime('%Y-%m-%d')
        hari_ini = get_hari_indonesia(today)
        context.user_data['temp_today_date'] = today_str
        
        keyboard = [
            [InlineKeyboardButton(f"✅ Gunakan ({today_str})", callback_data='use_today_date')],
            [InlineKeyboardButton("✏️ Ubah Tanggal", callback_data='change_date_manual')]
        ]
        await update.message.reply_text(f"Tanggal hari ini: *{hari_ini}, {today_str}*\nGunakan tanggal ini?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    if step == 'manual_date_input':
        try:
            date_obj = datetime.strptime(text, '%Y-%m-%d')
            context.user_data['tanggal'] = text
            # Branching manual
            if context.user_data.get('session_type') == 'MAINTENANCE':
                context.user_data['step'] = 'equipment'
                equipment_list = get_equipment()
                keyboard = [[InlineKeyboardButton(name, callback_data=f'equip_{eid}')] for eid, name in equipment_list]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("Pilih *Peralatan*:", reply_markup=reply_markup, parse_mode='Markdown')
            else:
                context.user_data['step'] = 'choose_shift'
                keyboard = [[InlineKeyboardButton("PS", callback_data='shift_PS')], [InlineKeyboardButton("MT", callback_data='shift_MT')]]
                await update.message.reply_text("Pilih *Shift*:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("⚠️ Format salah. Gunakan YYYY-MM-DD")
        return

    # --- MAINTENANCE/LOGBOOK IN-SESSION ---
    if step == 'nok_keterangan':
        point_id = context.user_data.get('pending_nok')
        session_id = context.user_data['session_id']
        save_response(session_id, point_id, 'NOK', None, text)
        context.user_data['step'] = 'nok_photo'
        keyboard = [[InlineKeyboardButton("Lewati Foto", callback_data='skip_nok_photo')]]
        await update.message.reply_text("Ket. tersimpan. Ada foto bukti kerusakan?", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if step == 'answer_value':
        session_id = context.user_data['session_id']
        point_id = context.user_data['point_id']
        save_response(session_id, point_id, 'OK', text, None)
        await update.message.reply_text(f"Jawaban '{text}' tersimpan.")
        context.user_data['step'] = None
        await ask_question(context, update.message.chat_id, session_id)
        return

    if step == 'maintenance_summary':
        session_id = context.user_data['session_id']
        save_summary(session_id, text)
        # Maintenance selesai di sini, tidak perlu foto umum
        await finish_session_process(update, context, session_id, image_path=None)
        return

    if step == 'logbook_keterangan':
        session_id = context.user_data['session_id']
        save_summary(session_id, text)
        context.user_data['step'] = 'logbook_image'
        await request_photo_upload(update, context, "Silakan kirim gambar dokumentasi Logbook (Opsional):")
        return

# --- Photo Handler ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    session_id = context.user_data.get("session_id")
    
    # 1. Foto Support Ticket
    if step == 'support_photo':
        user_name = context.user_data.get('user_name', 'unknown')
        chat_id = update.effective_chat.id # Ambil ID Chat
        
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        filename = f"support_{int(datetime.now().timestamp())}_{user_name}.jpg"
        path = os.path.join(IMAGE_DIR, filename)
        await file.download_to_drive(path)
        
        name = user_name
        cat = context.user_data.get('support_category')
        desc = context.user_data.get('support_desc')
        
        ticket_id = save_support_ticket(name, chat_id, cat, desc, path)
        await update.message.reply_text(f"✅ Tiket Support #{ticket_id} berhasil dibuat dengan foto!\nAnda akan menerima notifikasi saat tiket diproses.")
        context.user_data.clear()
        return

    # 2. Foto NOK Maintenance
    if step == 'nok_photo' and session_id:
        point_id = context.user_data.get('pending_nok')
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        path = os.path.join(IMAGE_DIR, f"session_{session_id}_point_{point_id}.jpg")
        await file.download_to_drive(path)
        
        save_record_image(session_id, point_id, path)
        await update.message.reply_text("Foto bukti tersimpan.")
        context.user_data.pop('pending_nok', None)
        context.user_data['step'] = None
        await ask_question(context, update.message.chat_id, session_id)
        return

    # 3. Foto Logbook (Akhir Sesi)
    if step == 'logbook_image' and session_id:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        path = os.path.join(IMAGE_DIR, f"session_{session_id}.jpg")
        await file.download_to_drive(path)
        await finish_session_process(update, context, session_id, image_path=path)

# --- Photo Handler ---
async def error_handler(update, context):
    print("ERROR:", context.error)

def main():
    check_and_update_db_schema() # Jalankan migrasi DB
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_response))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_error_handler(error_handler)

    logger.info("Bot started!")
    app.run_polling()

if __name__ == '__main__':
    main()