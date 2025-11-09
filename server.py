# server.py (Updated for PostgreSQL compatibility on Render)

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

# --- BEGIN DATABASE ADAPTER IMPORTS ---
try:
    # Attempt to import PostgreSQL connector
    import psycopg2
    from psycopg2.extras import RealDictCursor as PostgresRow
    from urllib.parse import urlparse
    logger = logging.getLogger("iss-tracker")
    logger.info("PostgreSQL module (psycopg2) imported successfully.")
    USE_POSTGRES = True
except ImportError:
    # Fallback to standard SQLite
    import sqlite3
    logger = logging.getLogger("iss-tracker")
    logger.warning("PostgreSQL module not found. Falling back to in-memory SQLite.")
    USE_POSTGRES = False
# --- END DATABASE ADAPTER IMPORTS ---


# ---------- Configuration ----------
# Use DATABASE_URL for Postgres, or fallback to an in-memory SQLite path
DB_PATH = os.environ.get("DATABASE_URL", ":memory:")
API_URL = os.environ.get("ISS_API_URL", "https://api.wheretheiss.at/v1/satellites/25544")
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL_SEC", "5"))  # seconds
MAX_RETENTION_DAYS = int(os.environ.get("MAX_RETENTION_DAYS", "3"))
PORT = int(os.environ.get("PORT", "10000"))
PER_PAGE = 1000 # Default for database viewer

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("iss-tracker")

# ---------- Flask ----------
app = Flask(__name__)
CORS(app)

# ---------- Database Connection Logic ----------

def get_conn():
    if USE_POSTGRES:
        # Connection for PostgreSQL using environment variable
        result = urlparse(DB_PATH)
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
        # Use a dictionary cursor for consistency with sqlite3.Row
        return conn, PostgresRow
    else:
        # Connection for SQLite (defaulting to non-persistent in-memory)
        conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        conn.row_factory = sqlite3.Row
        return conn, None

def init_db():
    conn, row_factory_class = get_conn()
    cur = conn.cursor()
    
    if USE_POSTGRES:
        # SQL for PostgreSQL
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
        # SQL for SQLite (similar to original, but running in memory if DB_PATH is not specified)
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


def save_position(lat, lon, alt, ts_utc):
    day = ts_utc.split(" ")[0]
    conn, row_factory_class = get_conn()
    cur = conn.cursor()
    
    # Use different placeholders for SQLite (?) vs Postgres (%s)
    if USE_POSTGRES:
        cur.execute("INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day) VALUES (%s, %s, %s, %s, %s)",
                    (lat, lon, alt, ts_utc, day))
    else:
        cur.execute("INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day) VALUES (?, ?, ?, ?, ?)",
                    (lat, lon, alt, ts_utc, day))

    conn.commit()
    conn.close()

def cleanup_old_data():
    # Remove data older than MAX_RETENTION_DAYS
    cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn, row_factory_class = get_conn()
    cur = conn.cursor()
    
    # The WHERE clause is the same, but the placeholder might be different, though SQLite's '?' is generally safe.
    # For simplicity, using the safe '?' placeholder for both is common in Python DBAPI wrappers.
    cur.execute("DELETE FROM iss_positions WHERE timestamp < ?", (cutoff,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    if deleted:
        logger.info("Cleaned up %d old records older than %s", deleted, cutoff)

# ---------- Fetch ISS (UNMODIFIED) ----------
def fetch_iss_position():
    try:
        resp = requests.get(API_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        ts = datetime.utcfromtimestamp(int(data.get("timestamp", time.time())))
        
        # Determine data structure based on API response (handling both formats seen in source)
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

# ---------- Background Thread (UNMODIFIED) ----------
stop_event = Event()
def background_loop():
    while not stop_event.is_set():
        pos = fetch_iss_position()
        if pos:
            save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
        cleanup_old_data()
        stop_event.wait(FETCH_INTERVAL)

# ---------- API Endpoints (MODIFIED FOR UNIVERSAL DB ACCESS) ----------
@app.route("/")
def index():
    return send_file("index.html") if os.path.exists("index.html") else "ISS Tracker API", 200

@app.route("/database")
def database_viewer():
    return send_file("database.html") if os.path.exists("database.html") else "Database Viewer Not Found", 404

def _fetch_last_record():
    conn, row_factory_class = get_conn()
    # Need to set the row factory if using Postgres
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=row_factory_class)
    else:
        cur = conn.cursor()

    cur.execute("SELECT latitude, longitude, altitude, timestamp AS ts_utc, day FROM iss_positions ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row

@app.route("/api/current")
def api_current():
    pos = fetch_iss_position()
    if pos:
        save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
        return jsonify(pos)
    
    row = _fetch_last_record()
    if row:
        return jsonify({"latitude": row["latitude"], "longitude": row["longitude"],
                        "altitude": row["altitude"], "ts_utc": row["ts_utc"], "day": row["day"]})
    
    return jsonify({"error": "No data available"}), 404

@app.route("/api/last3days")
def api_last3days():
    cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn, row_factory_class = get_conn()
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=row_factory_class)
    else:
        cur = conn.cursor()
        
    cur.execute("SELECT latitude, longitude, altitude, timestamp AS ts_utc, day FROM iss_positions WHERE timestamp >= %s ORDER BY timestamp ASC", (cutoff,))
    rows = cur.fetchall()
    conn.close()
    # Ensure rows are convertible to dict/json for jsonify
    return jsonify([dict(r) for r in rows])

@app.route("/api/stats")
def api_stats():
    conn, row_factory_class = get_conn()
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=row_factory_class)
    else:
        cur = conn.cursor()
        
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

@app.route("/api/all-records")
def api_all_records():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', PER_PAGE, type=int)
    day_filter = request.args.get('day', '')
    
    conn, row_factory_class = get_conn()
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=row_factory_class)
        # Placeholder style for Postgres is %s
        limit_offset_placeholder = "%s OFFSET %s"
    else:
        cur = conn.cursor()
        # Placeholder style for SQLite is ?
        limit_offset_placeholder = "? OFFSET ?"
    
    # 1. Get available days
    cur.execute("SELECT DISTINCT day FROM iss_positions ORDER BY day DESC")
    available_days = [row["day"] for row in cur.fetchall()]

    # 2. Build WHERE clause and get total count
    where_clause = ""
    params = []
    if day_filter:
        where_clause = "WHERE day = %s" if USE_POSTGRES else "WHERE day = ?"
        params.append(day_filter)
        
    cur.execute(f"SELECT COUNT(*) FROM iss_positions {where_clause}", params)
    total_records = cur.fetchone()[0]
    
    # 3. Calculate pagination
    total_pages = (total_records + per_page - 1) // per_page
    if page < 1: page = 1
    if page > total_pages and total_pages > 0: page = total_pages
    offset = (page - 1) * per_page
    
    # 4. Fetch records for the page
    query = f"""
        SELECT id, latitude, longitude, altitude, timestamp AS ts_utc, day 
        FROM iss_positions 
        {where_clause} 
        ORDER BY timestamp DESC 
        LIMIT {limit_offset_placeholder}
    """
    
    # The order of parameters is crucial: (day_filter), per_page, offset
    query_params = params + [per_page, offset]
    
    cur.execute(query, query_params)
    records = cur.fetchall()
    conn.close()
    
    return jsonify({
        "total": total_records,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "available_days": available_days,
        "records": [dict(r) for r in records]
    })

@app.route("/api/download-csv")
def api_download_csv():
    day_filter = request.args.get('day', 'all')
    
    conn, row_factory_class = get_conn()
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=row_factory_class)
        day_placeholder = "%s"
    else:
        cur = conn.cursor()
        day_placeholder = "?"
    
    # Build query
    where_clause = ""
    params = []
    if day_filter and day_filter != 'all':
        where_clause = f"WHERE day = {day_placeholder}"
        params.append(day_filter)
        
    query = f"""
        SELECT timestamp, day, latitude, longitude, altitude
        FROM iss_positions 
        {where_clause} 
        ORDER BY timestamp ASC
    """
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        return jsonify({"error": "No data found for the selected period"}), 404

    # Create CSV in-memory
    si = StringIO()
    cw = csv.writer(si)
    
    # Write header
    header = ["timestamp_utc", "day", "latitude", "longitude", "altitude_km"]
    cw.writerow(header)
    
    # Write rows
    for row in rows:
        cw.writerow([row["timestamp"], row["day"], row["latitude"], row["longitude"], row["altitude"]])

    output = si.getvalue()
    
    # Determine filename
    filename = f"iss_data_{day_filter.replace('-', '')}.csv" if day_filter != 'all' else "iss_data_all.csv"
    
    # Create the Flask response
    response = Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )
    return response

# ---------- Startup ----------
if __name__ == "__main__":
    # Ensure DB is initialized before starting threads
    init_db()
    Thread(target=background_loop, daemon=True).start()
    logger.info(f"Starting ISS Tracker on 0.0.0.0:{PORT} using {'PostgreSQL' if USE_POSTGRES else 'SQLite (In-Memory)'}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
