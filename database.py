# database.py - SQLite Database Manager for ONGC Dashboard v2

import sqlite3
import os
from datetime import datetime
from config import DATABASE_PATH
from werkzeug.security import generate_password_hash


# ── Connection ─────────────────────────────────────────────────────────
def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Initialise all tables ──────────────────────────────────────────────
def init_db():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    conn = get_connection()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS tank_data (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        tank_number INTEGER NOT NULL,
        pressure    REAL    NOT NULL,
        temperature REAL    NOT NULL,
        flow_rate   REAL    NOT NULL,
        tank_level  REAL    NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS app_config (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role     TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS event_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        username  TEXT,
        event     TEXT NOT NULL,
        detail    TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS prediction_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT NOT NULL,
        tank_number INTEGER NOT NULL,
        parameter   TEXT NOT NULL,
        predicted   REAL NOT NULL,
        actual      REAL,
        horizon_min INTEGER NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS alert_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT NOT NULL,
        tank_number INTEGER NOT NULL,
        alert_type  TEXT NOT NULL,
        value       REAL NOT NULL,
        notified    INTEGER DEFAULT 0
    )''')

    conn.commit()
    conn.close()


def init_users_table():
    conn = get_connection()
    c = conn.cursor()
    default_users = [
        ('admin',    generate_password_hash('admin123'),    'Admin'),
        ('operator', generate_password_hash('operator123'), 'Operator'),
    ]
    c.executemany(
        'INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)',
        default_users
    )
    conn.commit()
    conn.close()


# ── Tank Data ──────────────────────────────────────────────────────────
def save_reading(tank_number, pressure, temperature, flow_rate, tank_level):
    conn = get_connection()
    conn.execute('''
        INSERT INTO tank_data (timestamp, tank_number, pressure, temperature, flow_rate, tank_level)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
          tank_number, pressure, temperature, flow_rate, tank_level))
    conn.commit()
    conn.close()


def get_history(tank_number=None, date_filter=None, time_filter=None, limit=500):
    conn = get_connection()
    query  = "SELECT * FROM tank_data WHERE 1=1"
    params = []
    if tank_number:
        query += " AND tank_number = ?"; params.append(tank_number)
    if date_filter:
        query += " AND DATE(timestamp) = ?"; params.append(date_filter)
    if time_filter:
        query += " AND TIME(timestamp) >= ?"; params.append(time_filter)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_for_export(tank_number=None):
    return get_history(tank_number=tank_number, limit=100000)


def get_tank_readings_for_ai(tank_number, parameter, limit=500):
    """Return a flat list of (timestamp, value) for AI training."""
    col_map = {'pressure': 'pressure', 'temperature': 'temperature',
               'flow': 'flow_rate', 'level': 'tank_level'}
    col = col_map.get(parameter, 'pressure')
    conn = get_connection()
    rows = conn.execute(
        f'SELECT timestamp, {col} AS value FROM tank_data '
        f'WHERE tank_number=? ORDER BY timestamp ASC LIMIT ?',
        (tank_number, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_readings(tank_number):
    conn = get_connection()
    row = conn.execute(
        'SELECT COUNT(*) AS cnt FROM tank_data WHERE tank_number=?', (tank_number,)
    ).fetchone()
    conn.close()
    return row['cnt'] if row else 0


# ── Analytics ──────────────────────────────────────────────────────────
def get_analytics(tank_number=None):
    conn = get_connection()
    where  = "WHERE tank_number = ?" if tank_number else ""
    params = [tank_number] if tank_number else []
    rows   = conn.execute(f'''
        SELECT tank_number,
            ROUND(AVG(pressure),2) avg_pressure, ROUND(MAX(pressure),2) max_pressure,
            ROUND(MIN(pressure),2) min_pressure,
            ROUND(AVG(temperature),2) avg_temperature, ROUND(MAX(temperature),2) max_temperature,
            ROUND(MIN(temperature),2) min_temperature,
            ROUND(AVG(flow_rate),2) avg_flow,  ROUND(MAX(flow_rate),2) max_flow,
            ROUND(MIN(flow_rate),2) min_flow,
            ROUND(AVG(tank_level),2) avg_level, ROUND(MAX(tank_level),2) max_level,
            ROUND(MIN(tank_level),2) min_level, COUNT(*) total_readings
        FROM tank_data {where} GROUP BY tank_number ORDER BY tank_number
    ''', params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_summary(tank_number=None):
    conn = get_connection()
    where  = "AND tank_number=?" if tank_number else ""
    params = [tank_number] if tank_number else []
    rows   = conn.execute(f'''
        SELECT DATE(timestamp) day, tank_number,
            ROUND(AVG(pressure),2) avg_pressure, ROUND(AVG(temperature),2) avg_temperature,
            ROUND(AVG(flow_rate),2) avg_flow, ROUND(AVG(tank_level),2) avg_level,
            COUNT(*) readings
        FROM tank_data
        WHERE DATE(timestamp) >= DATE('now','-7 days') {where}
        GROUP BY DATE(timestamp), tank_number ORDER BY day DESC, tank_number
    ''', params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_weekly_summary(tank_number=None):
    conn = get_connection()
    where  = "AND tank_number=?" if tank_number else ""
    params = [tank_number] if tank_number else []
    rows   = conn.execute(f'''
        SELECT strftime('%Y-W%W', timestamp) week, tank_number,
            ROUND(AVG(pressure),2) avg_pressure, ROUND(AVG(temperature),2) avg_temperature,
            ROUND(AVG(flow_rate),2) avg_flow, ROUND(AVG(tank_level),2) avg_level,
            COUNT(*) readings
        FROM tank_data
        WHERE DATE(timestamp) >= DATE('now','-30 days') {where}
        GROUP BY strftime('%Y-W%W', timestamp), tank_number ORDER BY week DESC, tank_number
    ''', params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_monthly_summary(tank_number=None):
    conn = get_connection()
    where  = "AND tank_number=?" if tank_number else ""
    params = [tank_number] if tank_number else []
    rows   = conn.execute(f'''
        SELECT strftime('%Y-%m', timestamp) month, tank_number,
            ROUND(AVG(pressure),2) avg_pressure, ROUND(AVG(temperature),2) avg_temperature,
            ROUND(AVG(flow_rate),2) avg_flow, ROUND(AVG(tank_level),2) avg_level,
            COUNT(*) readings
        FROM tank_data {where.replace("AND","WHERE")}
        GROUP BY strftime('%Y-%m', timestamp), tank_number ORDER BY month DESC, tank_number
    ''', params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trend(tank_number, parameter='pressure', points=20):
    conn = get_connection()
    col_map = {'pressure': 'pressure', 'temperature': 'temperature',
               'flow': 'flow_rate', 'level': 'tank_level'}
    col  = col_map.get(parameter, parameter)
    rows = conn.execute(
        f'SELECT {col} FROM tank_data WHERE tank_number=? ORDER BY timestamp DESC LIMIT ?',
        (tank_number, points)
    ).fetchall()
    conn.close()
    if len(rows) < 2:
        return 'Stable'
    values      = [r[0] for r in reversed(rows)]
    mid         = len(values) // 2
    first_half  = sum(values[:mid]) / mid
    second_half = sum(values[mid:]) / (len(values) - mid)
    diff        = second_half - first_half
    if diff > 1.5:   return 'Increasing'
    if diff < -1.5:  return 'Decreasing'
    return 'Stable'


# ── Config ─────────────────────────────────────────────────────────────
def save_config(key, value):
    conn = get_connection()
    conn.execute('INSERT OR REPLACE INTO app_config (key,value) VALUES (?,?)', (key, str(value)))
    conn.commit()
    conn.close()


def load_config(key, default=None):
    conn = get_connection()
    row  = conn.execute('SELECT value FROM app_config WHERE key=?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


# ── Users ──────────────────────────────────────────────────────────────
def get_user_by_username(username):
    conn = get_connection()
    row  = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Event Log ──────────────────────────────────────────────────────────
def log_event(username, event, detail=''):
    conn = get_connection()
    conn.execute(
        'INSERT INTO event_log (timestamp, username, event, detail) VALUES (?,?,?,?)',
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), username, event, detail)
    )
    conn.commit()
    conn.close()


def get_event_log(limit=200):
    conn = get_connection()
    rows = conn.execute(
        'SELECT * FROM event_log ORDER BY timestamp DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Alert Log ──────────────────────────────────────────────────────────
def log_alert(tank_number, alert_type, value):
    conn = get_connection()
    conn.execute(
        'INSERT INTO alert_log (timestamp, tank_number, alert_type, value) VALUES (?,?,?,?)',
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), tank_number, alert_type, value)
    )
    conn.commit()
    conn.close()


def get_recent_alert(tank_number, alert_type, minutes=5):
    """Returns True if same alert was logged within cooldown period."""
    conn = get_connection()
    row  = conn.execute('''
        SELECT id FROM alert_log
        WHERE tank_number=? AND alert_type=?
          AND timestamp >= datetime('now', ?)
        ORDER BY timestamp DESC LIMIT 1
    ''', (tank_number, alert_type, f'-{minutes} minutes')).fetchone()
    conn.close()
    return row is not None


# ── Prediction History ─────────────────────────────────────────────────
def save_prediction(tank_number, parameter, predicted, horizon_min):
    conn = get_connection()
    conn.execute('''
        INSERT INTO prediction_history (timestamp, tank_number, parameter, predicted, horizon_min)
        VALUES (?,?,?,?,?)
    ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
          tank_number, parameter, predicted, horizon_min))
    conn.commit()
    conn.close()