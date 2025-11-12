#!/usr/bin/env python3
"""
main.py - Telegram bot untuk checklist maintenance & logbook (versi lengkap tanpa fitur pause)

Fitur utama:
- .env support (BOT_TOKEN, DATABASE_FILE, IMAGE_DIR)
- validasi tanggal + opsi gunakan tanggal hari ini
- validasi nilai numerik (Vac, Vdc, A, %, Jam)
- NOK -> wajib input keterangan
- Summary + image upload (dengan opsi "skip image")
- Logbook PS/MT + catatan + gambar (opsional)
- Menyimpan image ke folder IMAGE_DIR
"""

import os
import sqlite3
import logging
from datetime import datetime, date
from uuid import uuid4

# env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv optional; fallback to os.environ
    pass

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- Configuration ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN")  # prefer .env key BOT_TOKEN
DATABASE_FILE = os.getenv("DATABASE_FILE", "maintenance.db")
IMAGE_DIR = os.getenv("IMAGE_DIR", "images")
os.makedirs(IMAGE_DIR, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- Database helpers ----------------
def db_connect():
    return sqlite3.connect(DATABASE_FILE)

def start_session(tech1, tech2, tanggal, session_type, equipment_id=None, shift=None):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO maintenance_sessions (technician_1_name, technician_2_name, tanggal_tugas, session_type, equipment_id, shift, start_time, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (tech1, tech2, tanggal, session_type, equipment_id, shift, datetime.now(), 'IN_PROGRESS')
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid

def get_equipment():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM equipment")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_next_question(session_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.section, p.question, p.input_type
        FROM checklist_points p
        JOIN maintenance_sessions s ON p.equipment_id = s.equipment_id
        WHERE s.id = ? AND p.id NOT IN (
            SELECT r.point_id FROM maintenance_records r WHERE r.session_id = ?
        )
        ORDER BY p.order_number
        LIMIT 1
    """, (session_id, session_id))
    row = cur.fetchone()
    conn.close()
    return row  # or None

def save_response(session_id, point_id, status, value, keterangan):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO maintenance_records (session_id, point_id, response_status, response_value, keterangan) VALUES (?, ?, ?, ?, ?)",
        (session_id, point_id, status, value, keterangan)
    )
    conn.commit()
    conn.close()

def save_summary(session_id, summary):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE maintenance_sessions SET summary = ? WHERE id = ?", (summary, session_id))
    conn.commit()
    conn.close()

def save_image_path(session_id, image_paths):
    """
    image_paths: list of strings (file paths) -> will join with commas
    Mark session completed
    """
    if isinstance(image_paths, list):
        joined = ",".join(image_paths)
    else:
        joined = image_paths or None

    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE maintenance_sessions SET image_path = ?, status = 'COMPLETED' WHERE id = ?", (joined, session_id))
    conn.commit()
    conn.close()

# ---------------- Utility helpers ----------------
def is_number_for_type(value_text, input_type):
    """
    Validate numeric inputs for types like Vac, Vdc, A, %, Jam.
    Accepts numbers with optional decimal, optionally with comma as decimal sep.
    """
    if input_type is None:
        return True, value_text
    t = input_type.strip().lower()
    # normalize commas -> dots
    normalized = value_text.replace(",", ".").strip()
    # allow negative? not for these metrics -> not necessary
    try:
        if t in ('vac', 'vdc', 'a', '%', 'jam', 'jam(s)'):
            v = float(normalized)
            return True, str(v)
        else:
            # for unknown types accept as-is
            return True, value_text
    except Exception:
        return False, None

def format_today_buttons():
    today = date.today().isoformat()
    kb = [
        [InlineKeyboardButton("Gunakan tanggal hari ini (" + today + ")", callback_data=f'use_date_{today}')],
        [InlineKeyboardButton("Masukkan manual", callback_data='enter_date_manual')]
    ]
    return InlineKeyboardMarkup(kb)

def save_uploaded_photo_file(file_obj, session_id):
    """Save telegram File object to IMAGE_DIR with unique name, return path."""
    ext = ".jpg"
    fname = f"{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}{ext}"
    path = os.path.join(IMAGE_DIR, fname)
    # file_obj is telegram File, has method download_to_drive in PTB v20
    # caller should await file_obj.download_to_drive(path)
    return path

# ---------------- Bot state (per-conversation) ----------------
# We'll use context.user_data for per-chat state (provided by PTB).
# keys used in user_data:
# step, tech1, tech2, tanggal, session_type, equipment_id, session_id, shift,
# point_id, input_type, pending_nok, image_paths (list), expecting_date_manual

# ---------------- Bot handlers ----------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Start flow
    await update.message.reply_text(
        "👷 Masukkan *Nama Teknisi 1*:",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    context.user_data['step'] = 'technician_1'

async def handle_pre_session_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text.strip()

    if step == 'technician_1':
        context.user_data['tech1'] = text
        context.user_data['step'] = 'technician_2'
        await update.message.reply_text("👷 Masukkan *Nama Teknisi 2* (atau ketik '-' jika tidak ada):", parse_mode="Markdown")
        return

    if step == 'technician_2':
        context.user_data['tech2'] = text if text != '-' else ''
        context.user_data['step'] = 'tanggal'
        # Provide option to use today's date or manual
        await update.message.reply_text("🗓 Pilih tanggal tugas atau masukkan manual:", reply_markup=format_today_buttons(), parse_mode="Markdown")
        return

    if step == 'tanggal':
        # This path is used when user types manual date (not using button)
        # validate date format
        try:
            d = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            await update.message.reply_text("❌ Format tanggal tidak valid. Gunakan YYYY-MM-DD atau pilih tombol 'Gunakan tanggal hari ini'.")
            return
        context.user_data['tanggal'] = d.isoformat()
        context.user_data['step'] = 'choose_type'
        # show session type choose
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔧 Maintenance", callback_data='type_maintenance')],
            [InlineKeyboardButton("📘 Logbook Harian", callback_data='type_logbook')]
        ])
        await update.message.reply_text("Pilih *Tipe Sesi*:", reply_markup=keyboard, parse_mode="Markdown")
        return

    # If not in pre-session flow, pass to other handlers
    await update.message.reply_text("Silakan gunakan /start untuk memulai sesi, atau ikuti instruksi.", parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    cd = data
    chat_id = query.message.chat_id

    # Use date from button
    if cd.startswith('use_date_'):
        iso = cd.split('use_date_')[1]
        context.user_data['tanggal'] = iso
        context.user_data['step'] = 'choose_type'
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔧 Maintenance", callback_data='type_maintenance')],
            [InlineKeyboardButton("📘 Logbook Harian", callback_data='type_logbook')]
        ])
        await query.edit_message_text(f"✅ Tanggal dipilih: {iso}\nPilih tipe sesi:", reply_markup=keyboard)
        return

    if cd == 'enter_date_manual':
        context.user_data['step'] = 'tanggal'  # expecting manual typing of date
        await query.edit_message_text("Silakan ketik tanggal tugas dengan format YYYY-MM-DD.")
        return

    if cd == 'type_maintenance':
        context.user_data['session_type'] = 'MAINTENANCE'
        context.user_data['step'] = 'choose_equipment'
        # list equipment
        rows = get_equipment()
        if not rows:
            await query.edit_message_text("⚠️ Belum ada peralatan di database.")
            return
        kb = [[InlineKeyboardButton(name, callback_data=f'equip_{rid}')] for (rid, name) in rows]
        await query.edit_message_text("Pilih *Peralatan* yang akan di-maintenance:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if cd == 'type_logbook':
        context.user_data['session_type'] = 'LOGBOOK'
        context.user_data['step'] = 'choose_shift'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("PS (Pagi/Sore)", callback_data='shift_PS')],
            [InlineKeyboardButton("MT (Malam Tengah)", callback_data='shift_MT')]
        ])
        await query.edit_message_text("Pilih *Shift* Anda:", reply_markup=kb, parse_mode="Markdown")
        return

    if cd.startswith('shift_'):
        # Create logbook session
        shift = cd.split('_')[1]
        context.user_data['shift'] = shift
        s_id = start_session(
            context.user_data.get('tech1'),
            context.user_data.get('tech2'),
            context.user_data.get('tanggal'),
            'LOGBOOK',
            equipment_id=None,
            shift=shift
        )
        context.user_data['session_id'] = s_id
        context.user_data['step'] = 'logbook_notes'
        await query.edit_message_text(f"Shift *{shift}* dipilih. Silakan masukkan catatan kegiatan (teks):", parse_mode="Markdown")
        return

    if cd.startswith('equip_'):
        # Start maintenance session & start asking checklist
        eid = int(cd.split('_')[1])
        s_id = start_session(
            context.user_data.get('tech1'),
            context.user_data.get('tech2'),
            context.user_data.get('tanggal'),
            'MAINTENANCE',
            equipment_id=eid,
            shift=None
        )
        context.user_data['session_id'] = s_id
        context.user_data['step'] = None
        # ask first question
        await query.edit_message_text("Memulai maintenance untuk peralatan yang dipilih...")
        await ask_question(context, chat_id, s_id)
        return

    if cd.startswith('answer_'):
        # answer_ok_123 or answer_nok_123
        parts = cd.split('_')
        if len(parts) < 3:
            await query.edit_message_text("Callback format error.")
            return
        st = parts[1].upper()  # OK or NOK
        pid = int(parts[2])
        session_id = context.user_data.get('session_id')
        if not session_id:
            await query.edit_message_text("Sesi tidak ditemukan. Mulai ulang dengan /start.")
            return

        if st == 'OK':
            # save OK and immediately continue
            save_response(session_id, pid, 'OK', None, None)
            await query.edit_message_text("✅ OK tersimpan.")
            await ask_question(context, chat_id, session_id)
            return
        else:
            # NOK -> require keterangan
            context.user_data['pending_nok'] = pid
            context.user_data['step'] = 'nok_keterangan'
            await query.edit_message_text("❌ Anda memilih NOK. Silakan masukkan *keterangan* untuk poin ini:", parse_mode="Markdown")
            return

    if cd == 'skip_image':
        # Mark session completed, without image
        sid = context.user_data.get('session_id')
        if not sid:
            await query.edit_message_text("Tidak ada sesi aktif.")
            return
        save_image_path(sid, "")
        await query.edit_message_text("Sesi diselesaikan tanpa gambar. Data tersimpan. Terima kasih!")
        context.user_data.clear()
        return

    if cd == 'skip_logbook_image':
        sid = context.user_data.get('session_id')
        if not sid:
            await query.edit_message_text("Tidak ada sesi aktif.")
            return
        save_image_path(sid, "")
        await query.edit_message_text("Logbook disimpan tanpa gambar. Terima kasih!")
        context.user_data.clear()
        return

    # unknown callback
    await query.edit_message_text("Action tidak dikenali.")

async def ask_question(context: ContextTypes.DEFAULT_TYPE, chat_id: int, session_id: int):
    """
    Get next question and ask user. If none, prompt for summary then image (with skip).
    """
    q = get_next_question(session_id)
    if q:
        point_id, section, question, input_type = q
        context.user_data['point_id'] = point_id
        context.user_data['input_type'] = input_type
        # if input_type is OK/NOK, present two buttons; else ask for value
        full_text = f"*{section}*\n\n{question}\n\nTipe jawaban: {input_type}"
        if input_type.upper() == 'OK/NOK':
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ OK", callback_data=f'answer_ok_{point_id}'),
                 InlineKeyboardButton("❌ NOK", callback_data=f'answer_nok_{point_id}')]
            ])
            await context.bot.send_message(chat_id=chat_id, text=full_text, reply_markup=kb, parse_mode="Markdown")
            # set step to None because answer will come from callback
            context.user_data['step'] = None
        else:
            # ask for value and set step to answer_value
            context.user_data['step'] = 'answer_value'
            await context.bot.send_message(chat_id=chat_id, text=full_text + f"\n\nKetik jawabannya (format {input_type}):", parse_mode="Markdown")
    else:
        # no more questions
        context.user_data['step'] = 'maintenance_summary'
        await context.bot.send_message(chat_id=chat_id, text="✅ Semua poin checklist selesai.\nSilakan masukkan *keterangan akhir* maintenance (ringkasan):", parse_mode="Markdown")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Central text handler. Routes based on context.user_data['step'].
    """
    step = context.user_data.get('step')
    text = (update.message.text or "").strip()

    # pre-session steps (tech names, tanggal)
    if step in ('technician_1', 'technician_2', 'tanggal'):
        await handle_pre_session_inputs(update, context)
        return

    # NOK keterangan for a point
    if step == 'nok_keterangan':
        pid = context.user_data.pop('pending_nok', None)
        sid = context.user_data.get('session_id')
        if pid and sid:
            # save nok with keterangan
            save_response(sid, pid, 'NOK', None, text)
            await update.message.reply_text("Keterangan NOK tersimpan. Lanjutkan ke poin berikutnya.")
            # reset step and continue
            context.user_data['step'] = None
            await ask_question(context, update.effective_chat.id, sid)
            return
        else:
            await update.message.reply_text("Keterangan NOK gagal disimpan (sesi/poin tidak ditemukan).")
            return

    # answer_value for numeric/text inputs
    if step == 'answer_value':
        sid = context.user_data.get('session_id')
        pid = context.user_data.get('point_id')
        input_type = context.user_data.get('input_type')
        if not sid or not pid:
            await update.message.reply_text("Tidak ada sesi atau poin aktif. Mulai ulang dengan /start.")
            return

        # validate numeric if needed
        ok, normalized = is_number_for_type(text, input_type)
        if not ok:
            await update.message.reply_text(f"❌ Input tidak valid untuk tipe {input_type}. Coba lagi.")
            return

        # save as OK with value
        save_response(sid, pid, 'OK', normalized, None)
        await update.message.reply_text(f"✅ Jawaban '{normalized}' tersimpan.")
        context.user_data['step'] = None
        await ask_question(context, update.effective_chat.id, sid)
        return

    # maintenance_summary -> ask image with skip option
    if step == 'maintenance_summary':
        sid = context.user_data.get('session_id')
        if not sid:
            await update.message.reply_text("Sesi tidak ditemukan.")
            return
        save_summary(sid, text)
        context.user_data['step'] = 'maintenance_image'
        # offer skip button
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Kirim gambar", callback_data='do_upload_image')],  # placeholder, user can still send photo
            [InlineKeyboardButton("Lewati tanpa foto", callback_data='skip_image')]
        ])
        await update.message.reply_text("Silakan kirim gambar hasil maintenance (opsional). Jika tidak ada, pilih 'Lewati tanpa foto'.", reply_markup=kb)
        return

    # For logbook notes
    if step == 'logbook_keterangan' or step == 'logbook_notes':
        sid = context.user_data.get('session_id')
        if not sid:
            await update.message.reply_text("Sesi logbook tidak ditemukan.")
            return
        save_summary(sid, text)
        # next: ask for image (optional)
        context.user_data['step'] = 'logbook_image'
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Kirim gambar", callback_data='do_upload_image')],
            [InlineKeyboardButton("Lewati tanpa foto", callback_data='skip_logbook_image')]
        ])
        await update.message.reply_text("Catatan tersimpan. Jika ada foto kegiatan, kirim sekarang. Atau pilih 'Lewati tanpa foto'.", reply_markup=kb)
        return

    # default fallback
    await update.message.reply_text("Perintah tidak dikenali. Gunakan /start untuk memulai sesi atau ikuti instruksi yang muncul.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle photo uploads for maintenance or logbook.
    Save image, update session and mark completed.
    """
    step = context.user_data.get('step')
    sid = context.user_data.get('session_id')
    if not sid:
        await update.message.reply_text("Tidak ada sesi aktif untuk menyimpan gambar.")
        return

    # get highest-resolution photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    save_path = save_uploaded_photo_file(file, sid)
    # download
    await file.download_to_drive(save_path)

    # update DB: append path or set
    # we will allow multiple images; read existing image_path from DB then append
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT image_path FROM maintenance_sessions WHERE id = ?", (sid,))
    row = cur.fetchone()
    conn.close()
    existing = row[0] if row and row[0] else ""
    if existing:
        new_val = existing + "," + save_path
    else:
        new_val = save_path
    save_image_path(sid, [p for p in new_val.split(",") if p])  # save list

    await update.message.reply_text("✅ Foto diterima dan disimpan. Sesi selesai. Terima kasih!")
    context.user_data.clear()

# ----------------- Safety command(s) -----------------
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Sesi dibatalkan. Gunakan /start untuk memulai lagi.")

# ---------------- Main -----------------
def main():
    token = BOT_TOKEN
    if not token:
        logger.error("BOT_TOKEN tidak ditemukan. Set environment variable BOT_TOKEN atau buat .env dengan BOT_TOKEN.")
        return

    app = ApplicationBuilder().token(token).build()

    # handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    main()
