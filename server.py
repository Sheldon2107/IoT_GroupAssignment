from flask import Flask, jsonify, send_file
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
import time
import threading
import sqlite3
import os

app = Flask(__name__)
CORS(app)

DB_NAME = 'iss_data.db'
UPDATE_INTERVAL = 1   # seconds — you can increase to 5 or 10 to reduce writes
MAX_DAYS = 3
ISS_API_URL = 'https://api.wheretheiss.at/v1/satellites/25544'


# ===== Initialize Database =====
def init_database():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS iss_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude REAL NOT NULL,
            ts_utc TEXT NOT NULL,
            day TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    print("✓ Database initialized")


# ===== Fetch Current ISS Position =====
def fetch_iss_position():
    try:
        response = requests.get(ISS_API_URL, timeout=5)
        data = response.json()
        timestamp = datetime.utcfromtimestamp(data['timestamp'])
        return {
            'latitude': data['latitude'],
            'longitude': data['longitude'],
            'altitude': data['altitude'],  # kilometers
            'ts_utc': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'day': timestamp.strftime('%Y-%m-%d')
        }
    except Exception as e:
        print(f"[!] Error fetching ISS position: {e}")
        return None


# ===== Database Operations =====
def insert_position_to_db(position):
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO iss_positions (latitude, longitude, altitude, ts_utc, day)
        VALUES (?, ?, ?, ?, ?)
    ''', (position['latitude'], position['longitude'], position['altitude'],
          position['ts_utc'], position['day']))
    conn.commit()
    conn.close()


def prune_old_data():
    cutoff = datetime.utcnow() - timedelta(days=MAX_DAYS)
    cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM iss_positions WHERE ts_utc < ?', (cutoff_str,))
    conn.commit()
    conn.close()


# ===== Background Updater Thread =====
def background_update():
    while True:
        try:
            pos = fetch_iss_position()
            if pos:
                insert_position_to_db(pos)
                prune_old_data()
            time.sleep(UPDATE_INTERVAL)
        except Exception as e:
            print(f"[!] Background update error: {e}")
            time.sleep(UPDATE_INTERVAL)


# ===== Routes =====
@app.route('/')
def index():
    return send_file('index.html')


@app.route('/api/current')
def get_current():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT latitude, longitude, altitude, ts_utc, day FROM iss_positions ORDER BY id DESC LIMIT 1')
    row = cursor.fetchone()
    conn.close()

    if row:
        return jsonify({
            'latitude': row[0],
            'longitude': row[1],
            'altitude': row[2],
            'ts_utc': row[3],
            'day': row[4]
        })
    return jsonify({'error': 'No data available'}), 500


@app.route('/api/last3days')
def get_last_3_days():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT latitude, longitude, altitude, ts_utc, day FROM iss_positions ORDER BY id ASC')
    rows = cursor.fetchall()
    conn.close()

    # Sample every 60 seconds to reduce payload size
    sampled = rows[::60]
    data = [
        {'latitude': r[0], 'longitude': r[1], 'altitude': r[2], 'ts_utc': r[3], 'day': r[4]}
        for r in sampled
    ]
    return jsonify(data)


@app.route('/api/stats')
def get_stats():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT day, COUNT(*) FROM iss_positions GROUP BY day')
    rows = cursor.fetchall()
    conn.close()

    return jsonify({
        'records_per_day': {r[0]: r[1] for r in rows},
        'collection_rate': f'{UPDATE_INTERVAL} sec/request',
        'max_days': MAX_DAYS
    })


# ===== Start Background Thread =====
def start_background_thread():
    t = threading.Thread(target=background_update, daemon=True)
    t.start()
    print("✓ Background update started")


# ===== Entry Point =====
if __name__ == '__main__':
    init_database()
    start_background_thread()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
