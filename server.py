# server.py (SQLite only, flat directory)
import os
import time
import logging
import requests
from datetime import datetime, timedelta
from threading import Thread, Event
from flask import Flask, jsonify, send_file, request, Response
import sqlite3
import csv
from io import StringIO

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("iss-tracker")

# ---------- Configuration ----------
DB_PATH = os.environ.get("DB_PATH", "iss_data.db")  # SQLite file in same directory
API_URL = os.environ.get("ISS_API_URL", "https://api.wheretheiss.at/v1/satellites/25544")
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL_SEC", "5"))  # seconds
MAX_RETENTION_DAYS = int(os.environ.get("MAX_RETENTION_DAYS", "3"))
PORT = int(os.environ.get("PORT", "10000"))

# ---------- Flask ----------
app = Flask(__name__)

# ---------- Database Functions ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS iss_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude REAL,
            timestamp TEXT NOT NULL,
            day TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized (SQLite)")

def save_position(lat, lon, alt, ts_utc):
    day = ts_utc.split(" ")[0]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day) VALUES (?, ?, ?, ?, ?)",
        (lat, lon, alt, ts_utc, day)
    )
    conn.commit()
    conn.close()

def cleanup_old_data():
    cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM iss_positions WHERE timestamp < ?", (cutoff,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    if deleted:
        logger.info("Cleaned up %d old records older than %s", deleted, cutoff)

# ---------- Fetch ISS ----------
def fetch_iss_position():
    try:
        resp = requests.get(API_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        ts = datetime.utcfromtimestamp(int(data.get("timestamp", time.time())))

        if "iss_position" in data:
            pos = data["iss_position"]
            lat = float(pos["latitude"])
            lon = float(pos["longitude"])
            alt = None
        else:
            lat = float(data.get("latitude", 0))
            lon = float(data.get("longitude", 0))
            alt = float(data.get("altitude", 0))
        return {"latitude": lat, "longitude": lon, "altitude": alt, "ts_utc": ts.strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as e:
        logger.warning("Fetch error: %s", e)
        return None

# ---------- Background Thread ----------
stop_event = Event()
def background_loop():
    while not stop_event.is_set():
        pos = fetch_iss_position()
        if pos:
            save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
        cleanup_old_data()
        stop_event.wait(FETCH_INTERVAL)

# ---------- API Endpoints ----------
@app.route("/")
def index():
    return send_file("index.html") if os.path.exists("index.html") else "ISS Tracker API", 200

@app.route("/database")
def database_viewer():
    return send_file("database.html") if os.path.exists("database.html") else "Database Viewer Not Found", 404

@app.route("/api/current")
def api_current():
    pos = fetch_iss_position()
    if pos:
        save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
        return jsonify(pos)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT latitude, longitude, altitude, timestamp AS ts_utc, day FROM iss_positions ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return jsonify(dict(row))
    return jsonify({"error": "No data available"}), 404

@app.route("/api/all-records")
def api_all_records():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 1000, type=int)

    conn = get_conn()
    cur = conn.cursor()

    # Get unique days for navigation
    cur.execute("SELECT DISTINCT day FROM iss_positions ORDER BY day ASC")
    days = [r["day"] for r in cur.fetchall()]

    # Get total records
    cur.execute("SELECT COUNT(*) FROM iss_positions")
    total_records = cur.fetchone()[0]

    total_pages = (total_records + per_page - 1) // per_page
    if page < 1: page = 1
    if page > total_pages and total_pages > 0: page = total_pages
    offset = (page - 1) * per_page

    cur.execute("""
        SELECT id, latitude, longitude, altitude, timestamp AS ts_utc, day
        FROM iss_positions
        ORDER BY timestamp ASC
        LIMIT ? OFFSET ?
    """, (per_page, offset))

    records = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({
        "total": total_records,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "available_days": days,
        "records": records
    })

@app.route("/api/download-csv")
def api_download_csv():
    day_filter = request.args.get('day', 'all')

    conn = get_conn()
    cur = conn.cursor()

    if day_filter != 'all':
        cur.execute("SELECT timestamp, day, latitude, longitude, altitude FROM iss_positions WHERE day = ? ORDER BY timestamp ASC", (day_filter,))
    else:
        cur.execute("SELECT timestamp, day, latitude, longitude, altitude FROM iss_positions ORDER BY timestamp ASC")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return jsonify({"error": "No data found for the selected period"}), 404

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["timestamp_utc", "day", "latitude", "longitude", "altitude_km"])
    for row in rows:
        cw.writerow([row["timestamp"], row["day"], row["latitude"], row["longitude"], row["altitude"]])

    filename = f"iss_data_{day_filter.replace('-', '')}.csv" if day_filter != 'all' else "iss_data_all.csv"
    response = Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )
    return response

# ---------- Startup ----------
if __name__ == "__main__":
    init_db()
    Thread(target=background_loop, daemon=True).start()
    logger.info(f"Starting ISS Tracker on 0.0.0.0:{PORT} using SQLite")
    app.run(host="0.0.0.0", port=PORT, debug=False)
