# server.py
from flask import Flask, jsonify, render_template, send_from_directory, request
import sqlite3
import requests
import threading
import time
from datetime import datetime, timedelta
import os

app = Flask(__name__)
DB_FILE = 'iss_data.db'
API_URL = 'https://api.wheretheiss.at/v1/satellites/25544'

# --------------------------
# Initialize database
# --------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS iss_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT,
            latitude REAL,
            longitude REAL,
            altitude REAL
        )
    ''')
    conn.commit()
    conn.close()

# --------------------------
# Background fetch thread
# --------------------------
def fetch_and_store():
    while True:
        try:
            res = requests.get(API_URL, timeout=5)
            data = res.json()
            ts_utc = datetime.utcfromtimestamp(data['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            lat = data['latitude']
            lon = data['longitude']
            alt = data['altitude']

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('INSERT INTO iss_positions (ts_utc, latitude, longitude, altitude) VALUES (?, ?, ?, ?)',
                      (ts_utc, lat, lon, alt))
            conn.commit()
            conn.close()
            print(f"Stored: {ts_utc} | Lat:{lat:.2f} Lon:{lon:.2f} Alt:{alt:.2f}")
        except Exception as e:
            print("Error fetching/storing ISS data:", e)

        time.sleep(1)  # fetch every 1 second

# --------------------------
# API: last 3 days of data
# --------------------------
@app.route('/api/last3days')
def last3days():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM iss_positions WHERE ts_utc >= datetime('now','-3 days') ORDER BY ts_utc ASC")
    rows = c.fetchall()
    conn.close()

    data = []
    for row in rows:
        data.append({
            "id": row[0],
            "ts_utc": row[1],
            "latitude": row[2],
            "longitude": row[3],
            "altitude": row[4]
        })
    return jsonify(data)

# --------------------------
# API: all records (with pagination & filtering by day)
# --------------------------
@app.route('/api/all-records')
def all_records():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 1000))
    day_filter = request.args.get('day', '')

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    query = "SELECT COUNT(*) FROM iss_positions"
    if day_filter:
        query += f" WHERE date(ts_utc)='{day_filter}'"
    total = c.execute(query).fetchone()[0]

    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page

    query = "SELECT * FROM iss_positions"
    if day_filter:
        query += f" WHERE date(ts_utc)='{day_filter}'"
    query += f" ORDER BY ts_utc ASC LIMIT {per_page} OFFSET {offset}"
    rows = c.execute(query).fetchall()

    # unique available days
    days = [r[1][:10] for r in c.execute("SELECT DISTINCT date(ts_utc) FROM iss_positions ORDER BY date(ts_utc)").fetchall()]

    conn.close()

    records = [{
        "id": r[0],
        "ts_utc": r[1],
        "latitude": r[2],
        "longitude": r[3],
        "altitude": r[4],
        "day": r[1][:10]
    } for r in rows]

    return jsonify({
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "records": records,
        "available_days": days
    })

# --------------------------
# Serve HTML pages
# --------------------------
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/database')
def database():
    return send_from_directory('.', 'database.html')

# --------------------------
# Serve static files (CSS/JS if needed)
# --------------------------
@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

# --------------------------
# Main
# --------------------------
if __name__ == '__main__':
    init_db()
    threading.Thread(target=fetch_and_store, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=True)
