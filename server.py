import os
import time
import csv
import sqlite3
import logging
import requests
from datetime import datetime, timedelta
from threading import Thread, Event
from flask import Flask, jsonify, send_file, request, abort
from flask_cors import CORS

DB_PATH = "iss_data.db"
API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 5
MAX_RETENTION_DAYS = 3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("iss")

app = Flask(__name__)
CORS(app)

# ---------------- DATABASE ----------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS iss_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            latitude REAL,
            longitude REAL,
            altitude REAL,
            timestamp TEXT,
            day TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_position(lat, lon, alt, ts_utc):
    day = ts_utc.split(" ")[0]
    conn = get_conn()
    conn.execute(
        "INSERT INTO iss_positions (latitude,longitude,altitude,timestamp,day) VALUES (?,?,?,?,?)",
        (lat, lon, alt, ts_utc, day)
    )
    conn.commit()
    conn.close()

def cleanup_old():
    cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    conn.execute("DELETE FROM iss_positions WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()

# ---------------- FETCH LOOP ----------------
stop_event = Event()

def fetch_iss():
    try:
        r = requests.get(API_URL, timeout=8)
        data = r.json()
        ts = datetime.utcfromtimestamp(data["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        lat = float(data["latitude"])
        lon = float(data["longitude"])
        alt = float(data["altitude"])
        return lat, lon, alt, ts
    except:
        return None

def background_loop():
    while not stop_event.is_set():
        pos = fetch_iss()
        if pos:
            lat, lon, alt, ts = pos
            save_position(lat, lon, alt, ts)
        cleanup_old()
        stop_event.wait(FETCH_INTERVAL)

# ---------------- API ----------------

@app.route("/")
def home():
    return send_file("index.html")

@app.route("/database")
def db_page():
    return send_file("database.html")

@app.route("/api/last3days")
def last3():
    cutoff = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    rows = conn.execute(
        "SELECT latitude,longitude,altitude,timestamp AS ts_utc,day FROM iss_positions WHERE timestamp >= ? ORDER BY timestamp ASC",
        (cutoff,)
    ).fetchall()
    conn.close()

    return jsonify([
        dict(r) for r in rows
    ])

@app.route("/api/all-records")
def all_records():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 1000))
    day = request.args.get("day")

    conn = get_conn()
    args = []
    q = "SELECT COUNT(*) FROM iss_positions"
    if day:
        q += " WHERE day = ?"
        args.append(day)

    total = conn.execute(q, args).fetchone()[0]
    pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page

    q2 = "SELECT * FROM iss_positions"
    if day:
        q2 += " WHERE day = ?"
    q2 += " ORDER BY id ASC LIMIT ? OFFSET ?"

    args2 = args + [per_page, offset]
    rows = conn.execute(q2, args2).fetchall()

    days = conn.execute("SELECT DISTINCT day FROM iss_positions ORDER BY day ASC").fetchall()
    conn.close()

    return jsonify({
        "total": total,
        "page": page,
        "total_pages": pages,
        "records": [dict(r) for r in rows],
        "available_days": [d["day"] for d in days]
    })

@app.route("/api/download")
def download_csv():
    day = request.args.get("day")  # YYYY-MM-DD or None

    conn = get_conn()
    if day:
        rows = conn.execute("SELECT * FROM iss_positions WHERE day = ? ORDER BY timestamp ASC", (day,))
        filename = f"iss_{day}.csv"
    else:
        rows = conn.execute("SELECT * FROM iss_positions ORDER BY timestamp ASC")
        filename = "iss_all_days.csv"

    path = f"/tmp/{filename}"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id","timestamp","day","latitude","longitude","altitude"])
        for r in rows:
            writer.writerow([
                r["id"], r["timestamp"], r["day"],
                r["latitude"], r["longitude"], r["altitude"]
            ])

    conn.close()
    return send_file(path, as_attachment=True)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    init_db()
    Thread(target=background_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
