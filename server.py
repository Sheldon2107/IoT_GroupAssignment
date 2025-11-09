# server.py
import os
import time
import sqlite3
import logging
import requests
from datetime import datetime, timedelta
from threading import Thread, Event
from flask import Flask, jsonify, send_file, request
from flask_cors import CORS

# ---------- Configuration ----------
DB_PATH = os.environ.get("DB_PATH", "iss_data.db")
API_URL = os.environ.get("ISS_API_URL", "https://api.wheretheiss.at/v1/satellites/25544")

# Default: 1 second. For Render use 60 for fewer DB writes.
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL_SEC", "1"))

# Keep last 3 days
MAX_RETENTION_DAYS = int(os.environ.get("MAX_RETENTION_DAYS", "3"))

# Sample data on first init? ("1" to enable)
SAMPLE_DATA = os.environ.get("SAMPLE_DATA", "0") == "1"

# Render uses PORT env var automatically
PORT = int(os.environ.get("PORT", "10000"))

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("iss-tracker")

# ---------- Flask ----------
app = Flask(__name__)
CORS(app)

# ---------- Database Utilities ----------
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON iss_positions(timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_day ON iss_positions(day)")
    conn.commit()
    conn.close()
    logger.info("✅ Database ready: %s", DB_PATH)

def save_position(lat, lon, alt, ts):
    day = ts.split(" ")[0]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day)
        VALUES (?, ?, ?, ?, ?)
    """, (lat, lon, alt, ts, day))
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
    if deleted > 0:
        logger.info(f"🧹 Removed {deleted} old records older than {cutoff}")

def get_record_count():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM iss_positions")
    count = cur.fetchone()[0]
    conn.close()
    return count

# ---------- API Parsing ----------
def parse_wheretheiss(data):
    ts = datetime.utcfromtimestamp(int(data["timestamp"]))
    return {
        "latitude": float(data["latitude"]),
        "longitude": float(data["longitude"]),
        "altitude": float(data.get("altitude", 0.0)),
        "ts_utc": ts.strftime("%Y-%m-%d %H:%M:%S")
    }

def parse_open_notify(data):
    ts = datetime.utcfromtimestamp(int(data["timestamp"]))
    pos = data["iss_position"]
    return {
        "latitude": float(pos["latitude"]),
        "longitude": float(pos["longitude"]),
        "altitude": None,
        "ts_utc": ts.strftime("%Y-%m-%d %H:%M:%S")
    }

def fetch_iss_position():
    try:
        resp = requests.get(API_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        if "iss_position" in data:
            return parse_open_notify(data)
        return parse_wheretheiss(data)
    except Exception as e:
        logger.warning("⚠️ API fetch failed: %s", e)
        return None

# ---------- Background Collector ----------
stop_event = Event()

def background_loop():
    cleanup_counter = 0
    while not stop_event.is_set():
        pos = fetch_iss_position()
        if pos:
            save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])

        cleanup_counter += 1
        if cleanup_counter >= max(1, int(3600 / max(1, FETCH_INTERVAL))):
            cleanup_old_data()
            cleanup_counter = 0

        stop_event.wait(FETCH_INTERVAL)

# ---------- Routes ----------
@app.route("/")
def index():
    try:
        return send_file("index.html")
    except:
        return "ISS Tracker API Running", 200

@app.route("/database")
def database_view():
    try:
        return send_file("database.html")
    except:
        return "Database viewer not found", 404

@app.route("/api/current")
def api_current():
    pos = fetch_iss_position()
    if pos:
        try:
            save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
        except:
            pass
        return jsonify(pos)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT latitude, longitude, altitude, timestamp AS ts_utc, day FROM iss_positions ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "No data available"}), 404

    return jsonify(dict(row))

@app.route("/api/last3days")
def api_last3days():
    cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT latitude, longitude, altitude, timestamp AS ts_utc, day
        FROM iss_positions WHERE timestamp >= ? ORDER BY timestamp ASC
    """, (cutoff,))
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/all-records")
def api_all():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(5000, max(1, int(request.args.get("per_page", 1000))))
        day_filter = request.args.get("day")

        conn = get_conn()
        cur = conn.cursor()

        if day_filter:
            cur.execute("SELECT COUNT(*) FROM iss_positions WHERE day = ?", (day_filter,))
            total = cur.fetchone()[0]
            cur.execute("""
                SELECT id, latitude, longitude, altitude, timestamp AS ts_utc, day
                FROM iss_positions
                WHERE day = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """, (day_filter, per_page, (page - 1) * per_page))
        else:
            cur.execute("SELECT COUNT(*) FROM iss_positions")
            total = cur.fetchone()[0]
            cur.execute("""
                SELECT id, latitude, longitude, altitude, timestamp AS ts_utc, day
                FROM iss_positions
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """, (per_page, (page - 1) * per_page))

        rows = cur.fetchall()
        conn.close()

        return jsonify({
            "records": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        })

    except Exception as e:
        logger.exception("Error in /api/all-records: %s", e)
        return jsonify({"error": "Server error"}), 500

@app.route("/api/stats")
def api_stats():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM iss_positions")
    total = cur.fetchone()[0]

    cur.execute("SELECT day, COUNT(*) AS cnt FROM iss_positions GROUP BY day ORDER BY day DESC")
    per_day = {row["day"]: row["cnt"] for row in cur.fetchall()}
    conn.close()

    total_hours = total / 3600
    total_days = total_hours / 24

    return jsonify({
        "total_records": total,
        "total_hours": round(total_hours, 2),
        "total_days": round(total_days, 2),
        "records_per_day": per_day,
        "collection_interval_seconds": FETCH_INTERVAL,
        "max_retention_days": MAX_RETENTION_DAYS
    })

# ---------- Startup ----------
if __name__ == "__main__":
    logger.info(f"🚀 Starting ISS Tracker on port {PORT} (interval={FETCH_INTERVAL}s)")
    init_database()

    if SAMPLE_DATA and get_record_count() == 0:
        logger.info("Generating sample data...")
        now = datetime.utcnow()
        conn = get_conn()
        cur = conn.cursor()
        for i in range(1000):
            t = now - timedelta(seconds=i)
            cur.execute("""
                INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day)
                VALUES (?, ?, ?, ?, ?)
            """, (45 + (i % 90), -180 + (i * 0.7) % 360, 400 + (i % 10), t.strftime("%Y-%m-%d %H:%M:%S"), t.strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()
        logger.info("✅ Sample data added")

    Thread(target=background_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
