# server.py (Fully DB-agnostic for PostgreSQL / SQLite on Render)

import os
import time
import logging
import requests
from datetime import datetime, timedelta
from threading import Thread, Event
from flask import Flask, jsonify, send_file, request, Response
from flask_cors import CORS
import csv
from io import StringIO

# ---------- DATABASE SETUP ----------
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor as PostgresRow
    from urllib.parse import urlparse
    USE_POSTGRES = True
    logging.info("PostgreSQL module (psycopg2) loaded.")
except ImportError:
    import sqlite3
    USE_POSTGRES = False
    logging.warning("PostgreSQL not found. Falling back to SQLite.")

DB_PATH = os.environ.get("DATABASE_URL", ":memory:")
API_URL = os.environ.get("ISS_API_URL", "https://api.wheretheiss.at/v1/satellites/25544")
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL_SEC", 5))
MAX_RETENTION_DAYS = int(os.environ.get("MAX_RETENTION_DAYS", 3))
PORT = int(os.environ.get("PORT", 10000))
PER_PAGE = 1000

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("iss-tracker")

# ---------- Flask ----------
app = Flask(__name__)
CORS(app)

# ---------- Database Connection ----------
def get_conn():
    if USE_POSTGRES:
        result = urlparse(DB_PATH)
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
        return conn, PostgresRow
    else:
        conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        conn.row_factory = sqlite3.Row
        return conn, None

def init_db():
    conn, row_factory_class = get_conn()
    cur = conn.cursor(cursor_factory=row_factory_class) if USE_POSTGRES else conn.cursor()
    
    if USE_POSTGRES:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS iss_positions (
                id SERIAL PRIMARY KEY,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                altitude REAL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                day VARCHAR(10) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)
    else:
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
    logger.info("Database initialized.")

# ---------- Helper for Placeholder ----------
def placeholder():
    return "%s" if USE_POSTGRES else "?"

# ---------- Save & Cleanup ----------
def save_position(lat, lon, alt, ts_utc):
    day = ts_utc.split(" ")[0]
    conn, row_factory_class = get_conn()
    cur = conn.cursor(cursor_factory=row_factory_class) if USE_POSTGRES else conn.cursor()
    p = placeholder()
    cur.execute(f"INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day) VALUES ({p},{p},{p},{p},{p})",
                (lat, lon, alt, ts_utc, day))
    conn.commit()
    conn.close()

def cleanup_old_data():
    cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn, row_factory_class = get_conn()
    cur = conn.cursor(cursor_factory=row_factory_class) if USE_POSTGRES else conn.cursor()
    p = placeholder()
    cur.execute(f"DELETE FROM iss_positions WHERE timestamp < {p}", (cutoff,))
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

# ---------- API ENDPOINTS ----------
@app.route("/")
def index():
    return send_file("index.html") if os.path.exists("index.html") else "ISS Tracker API", 200

@app.route("/api/current")
def api_current():
    pos = fetch_iss_position()
    if pos:
        save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
        return jsonify(pos)
    conn, row_factory_class = get_conn()
    cur = conn.cursor(cursor_factory=row_factory_class) if USE_POSTGRES else conn.cursor()
    cur.execute("SELECT latitude, longitude, altitude, timestamp AS ts_utc, day FROM iss_positions ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return jsonify({"latitude": row["latitude"], "longitude": row["longitude"], "altitude": row["altitude"], "ts_utc": row["ts_utc"], "day": row["day"]})
    return jsonify({"error":"No data available"}), 404

@app.route("/api/last3days")
def api_last3days():
    cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn, row_factory_class = get_conn()
    cur = conn.cursor(cursor_factory=row_factory_class) if USE_POSTGRES else conn.cursor()
    p = placeholder()
    cur.execute(f"SELECT latitude, longitude, altitude, timestamp AS ts_utc, day FROM iss_positions WHERE timestamp >= {p} ORDER BY timestamp ASC", (cutoff,))
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/stats")
def api_stats():
    conn, row_factory_class = get_conn()
    cur = conn.cursor(cursor_factory=row_factory_class) if USE_POSTGRES else conn.cursor()
    cur.execute("SELECT COUNT(*) FROM iss_positions")
    total = cur.fetchone()[0]
    cur.execute("SELECT day, COUNT(*) AS cnt FROM iss_positions GROUP BY day ORDER BY day DESC")
    per_day = {r["day"]: r["cnt"] for r in cur.fetchall()}
    conn.close()
    return jsonify({
        "total_records": total,
        "records_per_day": per_day,
        "collection_interval_seconds": FETCH_INTERVAL,
        "max_retention_days": MAX_RETENTION_DAYS
    })

# ---------- STARTUP ----------
if __name__ == "__main__":
    init_db()
    Thread(target=background_loop, daemon=True).start()
    logger.info(f"Starting ISS Tracker on 0.0.0.0:{PORT} using {'PostgreSQL' if USE_POSTGRES else 'SQLite (In-Memory)'}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
