# server.py
import os
import time
import logging
import requests
import sqlite3
from datetime import datetime, timedelta
from threading import Thread, Event
from flask import Flask, jsonify, send_file, request, Response
from flask_cors import CORS
import csv
from io import StringIO

# ---------- Configuration ----------
DB_PATH = "iss_data.db"  # SQLite database in same folder
API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 5  # seconds
MAX_RETENTION_DAYS = 3
PORT = int(os.environ.get("PORT", 10000))

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("iss-tracker")

# ---------- Flask ----------
app = Flask(__name__)
CORS(app)

# ---------- Database ----------
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
            day INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized.")

def save_position(lat, lon, alt, ts_utc):
    day = (datetime.strptime(ts_utc, "%Y-%m-%d %H:%M:%S").date() - START_DATE.date()).days + 1
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day) VALUES (?, ?, ?, ?, ?)",
                (lat, lon, alt, ts_utc, day))
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
        logger.info("Cleaned up %d old records", deleted)

# ---------- Fetch ISS ----------
def fetch_iss_position():
    try:
        resp = requests.get(API_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        ts = datetime.utcfromtimestamp(int(data.get("timestamp", time.time())))
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
def database_view():
    return send_file("database.html") if os.path.exists("database.html") else "Database Viewer Not Found", 404

@app.route("/api/current")
def api_current():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT latitude, longitude, altitude, timestamp FROM iss_positions ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return jsonify({
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "altitude": row["altitude"],
            "timestamp": row["timestamp"]
        })
    return jsonify({"error": "No data available"}), 404

@app.route("/api/all-records")
def api_all_records():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT day FROM iss_positions ORDER BY day ASC")
    days = [r["day"] for r in cur.fetchall()]
    
    day = request.args.get("day", type=int)
    if not day:
        day = days[0] if days else 1

    cur.execute("SELECT * FROM iss_positions WHERE day=? ORDER BY timestamp ASC", (day,))
    records = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({"records": records, "days": days, "current_day": day})

@app.route("/api/download-csv")
def api_download_csv():
    day = request.args.get("day", "all")
    conn = get_conn()
    cur = conn.cursor()
    if day == "all":
        cur.execute("SELECT * FROM iss_positions ORDER BY day ASC, timestamp ASC")
    else:
        cur.execute("SELECT * FROM iss_positions WHERE day=? ORDER BY timestamp ASC", (day,))
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        return jsonify({"error": "No data found"}), 404

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["id", "timestamp", "day", "latitude", "longitude", "altitude"])
    for r in rows:
        cw.writerow([r["id"], r["timestamp"], r["day"], r["latitude"], r["longitude"], r["altitude"]])
    
    filename = f"iss_data_day{day}.csv" if day != "all" else "iss_data_all.csv"
    return Response(si.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename={filename}"})

# ---------- Startup ----------
START_DATE = datetime.utcnow()
if __name__ == "__main__":
    init_db()
    Thread(target=background_loop, daemon=True).start()
    logger.info(f"Starting ISS Tracker on 0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
