import sqlite3
import os
import time

DATABASE_FILE = "maintenance.db"

def create_database():
    # 1. Hapus database lama jika ada
    if os.path.exists(DATABASE_FILE):
        try:
            os.remove(DATABASE_FILE)
            print(f"File database lama '{DATABASE_FILE}' berhasil dihapus.")
        except PermissionError:
            print(f"ERROR: Gagal menghapus '{DATABASE_FILE}'.")
            print("Pastikan Anda sudah MENUTUP 'main.py' (Bot) dan 'app.py' (Web) sebelum menjalankan script ini.")
            print("File database sedang dikunci oleh program lain.")
            return

    # Beri jeda sedikit untuk memastikan file system release handle
    time.sleep(1)

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    print("Database baru berhasil dibuat dan terhubung.")

    # --- Skema Tabel (DIBERSIHKAN: Hapus Duplikasi) ---
    sql_schema = """
        -- 1. Tabel Peralatan
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        -- 2. Tabel Poin Checklist
        CREATE TABLE IF NOT EXISTS checklist_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER,
            section TEXT NOT NULL,
            question TEXT NOT NULL,
            input_type TEXT NOT NULL,
            order_number INTEGER NOT NULL,
            FOREIGN KEY (equipment_id) REFERENCES equipment (id)
        );

        -- 3. Tabel Sesi Maintenance & Logbook
        CREATE TABLE IF NOT EXISTS maintenance_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            technician_1_name TEXT NOT NULL,
            technician_2_name TEXT,
            tanggal_tugas DATE NOT NULL,
            session_type TEXT NOT NULL, -- 'MAINTENANCE' atau 'LOGBOOK'
            equipment_id INTEGER,
            shift TEXT, -- 'PS' atau 'MT' (Hanya untuk Logbook)
            summary TEXT,
            image_path TEXT, -- Foto dokumentasi umum/logbook
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'IN_PROGRESS',
            FOREIGN KEY (equipment_id) REFERENCES equipment (id)
        );

        -- 4. Tabel Record Jawaban Maintenance
        CREATE TABLE IF NOT EXISTS maintenance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            point_id INTEGER NOT NULL,
            response_status TEXT, -- 'OK' atau 'NOK'
            response_value TEXT,
            keterangan TEXT,
            image_path TEXT,  -- Foto bukti kerusakan per item
            ticket_status TEXT DEFAULT 'OPEN', -- Status tiket per item: OPEN, RESOLVED
            ticket_note TEXT, -- Catatan perbaikan teknisi
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES maintenance_sessions (id),
            FOREIGN KEY (point_id) REFERENCES checklist_points (id)
        );

        -- 5. Tabel Tiket Support IT (DEFINISI TUNGGAL & LENGKAP)
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_name TEXT NOT NULL,
            reporter_chat_id INTEGER, -- ID Telegram Pelapor untuk notifikasi
            issue_category TEXT NOT NULL, -- Hardware, Software, Jaringan, dll
            issue_description TEXT NOT NULL,
            image_path TEXT,
            status TEXT DEFAULT 'OPEN', -- OPEN, IN_PROGRESS, RESOLVED
            technician_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );
    """
    cursor.executescript(sql_schema)
    print("Skema tabel berhasil dibuat.")

    # --- Data Awal (Equipment & Checklist) ---
    
    # A. RADAR CUACA EEC
    rc_name = 'RADAR CUACA EEC'
    cursor.execute("INSERT INTO equipment (name) VALUES (?)", (rc_name,))
    rc_id = cursor.lastrowid

    rc_checklist = [
        # 1. Genset
        (rc_id, '1. Genset', 'Cek kondisi air accu', 'OK/NOK', 1),
        (rc_id, '1. Genset', 'Ukur Tegangan Accu', 'Vdc', 2),
        (rc_id, '1. Genset', 'Cek air radiator', 'OK/NOK', 3),
        (rc_id, '1. Genset', 'Cek ketersediaan solar', 'OK/NOK', 4),
        (rc_id, '1. Genset', 'Cek kebersihan genset dan ruangan genset', 'OK/NOK', 5),
        (rc_id, '1. Genset', 'Cek panel ATS', 'OK/NOK', 6),
        (rc_id, '1. Genset', 'Test running genset (Sumber)', 'OK/NOK', 7),
        (rc_id, '1. Genset', 'Ukur Tegangan Output Genset RN', 'Vac', 8),
        (rc_id, '1. Genset', 'Ukur Tegangan Output Genset SN', 'Vac', 9),
        (rc_id, '1. Genset', 'Ukur Tegangan Output Genset TN', 'Vac', 10),
        (rc_id, '1. Genset', 'Ukur Tegangan Output Genset RS', 'Vac', 11),
        (rc_id, '1. Genset', 'Ukur Tegangan Output Genset RT', 'Vac', 12),
        (rc_id, '1. Genset', 'Ukur Tegangan Output Genset ST', 'Vac', 13),
        (rc_id, '1. Genset', 'Ukur Tegangan PLN RN (Panel ATS)', 'Vac', 14),
        (rc_id, '1. Genset', 'Ukur Tegangan PLN SN (Panel ATS)', 'Vac', 15),
        (rc_id, '1. Genset', 'Ukur Tegangan PLN TN (Panel ATS)', 'Vac', 16),
        (rc_id, '1. Genset', 'Ukur Tegangan PLN RS (Panel ATS)', 'Vac', 17),
        (rc_id, '1. Genset', 'Ukur Tegangan PLN RT (Panel ATS)', 'Vac', 18),
        (rc_id, '1. Genset', 'Ukur Tegangan PLN ST (Panel ATS)', 'Vac', 19),
        (rc_id, '1. Genset', 'Ukur Arus Beban R', 'A', 20),
        (rc_id, '1. Genset', 'Ukur Arus Beban S', 'A', 21),
        (rc_id, '1. Genset', 'Ukur Arus Beban T', 'A', 22),
        (rc_id, '1. Genset', 'Ukur Arus Beban N', 'A', 23),
        (rc_id, '1. Genset', 'Cek Operate Time', 'Jam', 24),
        # 2. Air Conditioner (AC)
        (rc_id, '2. Air Conditioner (AC)', 'Cek kondisi temperatur ruangan', 'OK/NOK', 25),
        # 3. Ruangan Server
        (rc_id, '3. Ruangan Server', 'Cek kebersihan unit CPU, keyboard, mouse, monitor Server Rx', 'OK/NOK', 26),
        (rc_id, '3. Ruangan Server', 'Cek kebersihan ruangan server', 'OK/NOK', 27),
        # 4. PC LDM
        (rc_id, '4. PC LDM', 'Cek kebersihan unit CPU, keyboard, mouse, monitor', 'OK/NOK', 28),
        # 5. UPS LDM
        (rc_id, '5. UPS LDM', 'Cek Tegangan Input', 'Vac', 29),
        (rc_id, '5. UPS LDM', 'Cek Tegangan Output', 'Vac', 30),
        (rc_id, '5. UPS LDM', 'Cek Load UPS', '%', 31),
        (rc_id, '5. UPS LDM', 'Cek kebersihan UPS', 'OK/NOK', 32),
        # 6. Perangkat Jaringan
        (rc_id, '6. Perangkat Jaringan', 'Cek switch Hub', 'OK/NOK', 33),
        (rc_id, '6. Perangkat Jaringan', 'Cek router', 'OK/NOK', 34),
        (rc_id, '6. Perangkat Jaringan', 'Cek jaringan Radar', 'OK/NOK', 35),
        (rc_id, '6. Perangkat Jaringan', 'Cek catu daya processor', 'OK/NOK', 36),
        # 7. Unit Antena Processor
        (rc_id, '7. Unit Antena Processor', 'Cek Operate Time', 'Jam', 37),
        (rc_id, '7. Unit Antena Processor', 'Cek Tegangan HVPS', 'Vdc', 38),
        # 8. Antena Parabola System
        (rc_id, '8. Antena Parabola System', 'Check Azimut', 'OK/NOK', 39),
        (rc_id, '8. Antena Parabola System', 'Check Elevasi', 'OK/NOK', 40),
        # 9. UPS Radar
        (rc_id, '9. UPS RADAR', 'Cek tegangan input', 'Vdc', 41),
        (rc_id, '9. UPS RADAR', 'Cek tegangan output', 'Vdc', 42),
        (rc_id, '9. UPS RADAR', 'Cek load UPS', '%', 43),
        (rc_id, '9. UPS RADAR', 'Cek kebersihan UPS', 'OK/NOK', 44),
    ]
    cursor.executemany("INSERT INTO checklist_points (equipment_id, section, question, input_type, order_number) VALUES (?, ?, ?, ?, ?)", rc_checklist)

    # B. AWS DIGITASI
    aws_name = 'AWS DIGITASI'
    cursor.execute("INSERT INTO equipment (name) VALUES (?)", (aws_name,))
    aws_id = cursor.lastrowid
    
    aws_checklist = [
        (aws_id, '1. Datalogger', 'Cek kebersihan datalogger', 'OK/NOK', 1),
        (aws_id, '1. Datalogger', 'Cek pembacaan seluruh sensor', 'OK/NOK', 2),
        (aws_id, '1. Datalogger', 'Ukur tegangan sumber daya', 'Vac', 3),
        (aws_id, '1. Datalogger', 'Ukur tegangan battery', 'Vac', 4),
        (aws_id, '2. Sensor Suhu dan Kelembapan', 'Cek kondisi sensor', 'OK/NOK', 5),
        (aws_id, '3. Sensor Tekanan', 'Cek kondisi sensor', 'OK/NOK', 6),
        (aws_id, '3. Sensor Tekanan', 'Cek selang udara dari sensor ke udara luar', 'OK/NOK', 7),
        (aws_id, '4. Sensor Hujan', 'Cek pondasi dan dudukan sensor hujan', 'OK/NOK', 8),
        (aws_id, '4. Sensor Hujan', 'Test Reed Switch', 'OK/NOK', 9),
        (aws_id, '4. Sensor Hujan', 'Cek kondisi tipping bucket', 'OK/NOK', 10),
        (aws_id, '4. Sensor Hujan', 'Cek saluran masuk air', 'OK/NOK', 11),
        (aws_id, '4. Sensor Hujan', 'Cek saluran buang', 'OK/NOK', 12),
        (aws_id, '5. Sensor Angin', 'Cek kondisi sensor', 'OK/NOK', 13),
        (aws_id, '6. Sensor Radiasi Matahari', 'Cek kondisi sensor', 'OK/NOK', 14),
        (aws_id, '7. Sensor Penguapan Udara', 'Cek kondisi sensor', 'OK/NOK', 15),
        (aws_id, '7. Sensor Penguapan Udara', 'Pastikan level air sesuai', 'OK/NOK', 16),
        (aws_id, '8. Server', 'Cek kebersihan PC/Server', 'OK/NOK', 17),
        (aws_id, '8. Server', 'Cek real time data', 'OK/NOK', 18),
        (aws_id, '9. UPS', 'Ukur Tegangan Input R', 'Vac', 19),
        (aws_id, '9. UPS', 'Ukur Tegangan Input S', 'Vac', 20),
        (aws_id, '9. UPS', 'Ukur Tegangan Input T', 'Vac', 21),
        (aws_id, '9. UPS', 'Ukur Tegangan Input N', 'Vac', 22),
        (aws_id, '9. UPS', 'Ukur Tegangan Output R', 'Vac', 23),
        (aws_id, '9. UPS', 'Ukur Tegangan Output S', 'Vac', 24),
        (aws_id, '9. UPS', 'Ukur Tegangan Output T', 'Vac', 25),
        (aws_id, '9. UPS', 'Ukur Tegangan Output N', 'Vac', 26),
        (aws_id, '9. UPS', 'Cek Kebersihan UPS', 'OK/NOK', 27),
        (aws_id, '10. Cek Client di AMOS', 'Cek tampilan data pada PC client', 'OK/NOK', 28),
    ]
    cursor.executemany("INSERT INTO checklist_points (equipment_id, section, question, input_type, order_number) VALUES (?, ?, ?, ?, ?)", aws_checklist)

    # C. PERALATAN KONVENSIONAL
    pk_name = 'PERALATAN KONVENSIONAL'
    cursor.execute("INSERT INTO equipment (name) VALUES (?)", (pk_name,))
    pk_id = cursor.lastrowid

    pk_checklist = [
        (pk_id, '1. Sangkar Meteo', 'Cek nilai thermometer max-min dan bola basah-kering', 'OK/NOK', 1),
        (pk_id, '1. Sangkar Meteo', 'Cek kebersihan peralatan', 'OK/NOK', 2),
        (pk_id, '1. Sangkar Meteo', 'Cek kain thermometer bola basah', 'OK/NOK', 3),
        (pk_id, '1. Sangkar Meteo', 'Cek pondasi water level', 'OK/NOK', 4),
        (pk_id, '2. Cambre Stokes', 'Cek kebersihan peralatan', 'OK/NOK', 5),
        (pk_id, '2. Cambre Stokes', 'Cek kondisi pias', 'OK/NOK', 6),
        (pk_id, '2. Cambre Stokes', 'Cek pondasi water level', 'OK/NOK', 7),
        (pk_id, '3. Penakar Hujan Hillmann', 'Cek posisi pena mulai 0 hingga 10 mm', 'OK/NOK', 8),
        (pk_id, '3. Penakar Hujan Hillmann', 'Cek kejernihan tinta', 'OK/NOK', 9),
        (pk_id, '3. Penakar Hujan Hillmann', 'Cek saluran pembuangan', 'OK/NOK', 10),
        (pk_id, '3. Penakar Hujan Hillmann', 'Cek saluran masuk hujan', 'OK/NOK', 11),
        (pk_id, '3. Penakar Hujan Hillmann', 'Cek putaran silinder jatuh', 'OK/NOK', 12),
        (pk_id, '3. Penakar Hujan Hillmann', 'Cek pondasi water level', 'OK/NOK', 13),
        (pk_id, '4. Penakar Hujan OBS', 'Cek saluran masuk hujan', 'OK/NOK', 14),
        (pk_id, '4. Penakar Hujan OBS', 'Cek kondisi keran', 'OK/NOK', 15),
        (pk_id, '4. Penakar Hujan OBS', 'Cek tabung ukur', 'OK/NOK', 16),
        (pk_id, '4. Penakar Hujan OBS', 'Cek pondasi water level', 'OK/NOK', 17),
        (pk_id, '5. Panci Penguapan', 'Cek kebersihan air, still well, hook gauge, panci', 'OK/NOK', 18),
        (pk_id, '5. Panci Penguapan', 'Cek pembacaan thermometer apung', 'OK/NOK', 19),
        (pk_id, '5. Panci Penguapan', 'Cek fungsi cup counter', 'OK/NOK', 20),
        (pk_id, '5. Panci Penguapan', 'Cek pondasi water level', 'OK/NOK', 21),
        (pk_id, '5. Panci Penguapan', 'Kuras panci sebelum 00 UTC', 'OK/NOK', 22),
        (pk_id, '6. Theodolite', 'Bersihkan peralatan dan lensa', 'OK/NOK', 23),
        (pk_id, '6. Theodolite', 'Cek leveling', 'OK/NOK', 24),
        (pk_id, '6. Theodolite', 'Cek lensa jarak jauh/dekat', 'OK/NOK', 25),
   ]
    cursor.executemany("INSERT INTO checklist_points (equipment_id, section, question, input_type, order_number) VALUES (?, ?, ?, ?, ?)", pk_checklist)

    conn.commit()
    conn.close()
    print("Koneksi ditutup. Database siap digunakan.")

if __name__ == '__main__':
    create_database()