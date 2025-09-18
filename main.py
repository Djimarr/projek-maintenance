### main.py ###
import sqlite3
import logging
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from datetime import datetime

# --- Konfigurasi ---
TOKEN = "7625689953:AAHNg2vnEexzW3qG3fVVmrW3fIXAV7RkdSk"
DATABASE_FILE = 'maintenance.db'
IMAGE_DIR = 'images'
os.makedirs(IMAGE_DIR, exist_ok=True)

# --- Setup Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Fungsi Database ---
def db_connect():
    return sqlite3.connect(DATABASE_FILE)

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

# --- Fungsi Bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Masukkan *Nama Teknisi 1*:", parse_mode='Markdown')
    context.user_data.clear()
    context.user_data['step'] = 'technician_1'

async def handle_pre_session_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')

    if step == 'technician_1':
        context.user_data['tech1'] = update.message.text
        context.user_data['step'] = 'technician_2'
        await update.message.reply_text("Masukkan *Nama Teknisi 2*:", parse_mode='Markdown')

    elif step == 'technician_2':
        context.user_data['tech2'] = update.message.text
        context.user_data['step'] = 'tanggal'
        await update.message.reply_text("Masukkan *Tanggal Tugas* (format YYYY-MM-DD):", parse_mode='Markdown')

    elif step == 'tanggal':
        context.user_data['tanggal'] = update.message.text
        context.user_data['step'] = 'choose_type'
        keyboard = [
            [InlineKeyboardButton("Maintenance", callback_data='type_maintenance')],
            [InlineKeyboardButton("Logbook Harian", callback_data='type_logbook')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Pilih *Tipe Sesi*:", reply_markup=reply_markup, parse_mode='Markdown')

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
        await context.bot.send_message(chat_id=chat_id, text="✅ Semua poin checklist telah dijawab.\n\nMasukkan keterangan akhir maintenance:")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == 'type_maintenance':
        context.user_data['session_type'] = 'MAINTENANCE'
        context.user_data['step'] = 'equipment'
        equipment_list = get_equipment()
        keyboard = [[InlineKeyboardButton(name, callback_data=f'equip_{eid}')] for eid, name in equipment_list]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Pilih *Peralatan* yang akan di-maintenance:", reply_markup=reply_markup, parse_mode='Markdown')

    elif data == 'type_logbook':
        context.user_data['session_type'] = 'LOGBOOK'
        context.user_data['step'] = 'choose_shift'
        keyboard = [
            [InlineKeyboardButton("PS", callback_data='shift_PS')],
            [InlineKeyboardButton("MT", callback_data='shift_MT')]
        ]
        await query.edit_message_text("Pilih *Shift* Anda:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

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

async def handle_text_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    text = update.message.text

    if step in ['technician_1', 'technician_2', 'tanggal']:
        await handle_pre_session_inputs(update, context)
        return

    if step == 'nok_keterangan':
        point_id = context.user_data.pop('pending_nok')
        session_id = context.user_data['session_id']
        save_response(session_id, point_id, 'NOK', None, text)
        await update.message.reply_text("Keterangan NOK tersimpan.")
        context.user_data['step'] = None
        await ask_question(context, update.message.chat_id, session_id)
        return

    if step == 'answer_value':
        session_id = context.user_data['session_id']
        point_id = context.user_data['point_id']
        value = text
        # simpan sebagai OK dengan value
        save_response(session_id, point_id, 'OK', value, None)
        await update.message.reply_text(f"Jawaban '{value}' tersimpan.")
        context.user_data['step'] = None
        await ask_question(context, update.message.chat_id, session_id)
        return

    if step == 'maintenance_summary':
        session_id = context.user_data['session_id']
        save_summary(session_id, text)
        context.user_data['step'] = 'maintenance_image'
        await update.message.reply_text("Masukkan gambar hasil maintenance:")
        return

    if step == 'logbook_keterangan':
        session_id = context.user_data['session_id']
        save_summary(session_id, text)
        context.user_data['step'] = 'logbook_image'
        await update.message.reply_text("Silakan kirim gambar untuk logbook Anda:")
        return

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get('step')
    session_id = context.user_data.get('session_id')
    if step in ['maintenance_image', 'logbook_image'] and session_id:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        path = os.path.join(IMAGE_DIR, f"session_{session_id}.jpg")
        await file.download_to_drive(path)
        save_image_path(session_id, path)
        await update.message.reply_text("✅ Sesi selesai dan data tersimpan.")
        context.user_data.clear()

async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return

# --- Main ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_response))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Bot started!")
    app.run_polling()

if __name__ == '__main__':
    main()