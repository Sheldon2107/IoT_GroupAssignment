# server.py
import os
import time
import sqlite3
import logging
import requests
from datetime import datetime, timedelta
from threading import Thread, Event
from flask import Flask, jsonify, send_file, request, Response
from flask_cors import CORS
import csv
from io import StringIO

# ---------- Configuration ----------
DB_PATH = os.environ.get("DB_PATH", "iss_data.db")
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
            day TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", DB_PATH)

def save_position(lat, lon, alt, ts_utc):
    day = ts_utc.split(" ")[0]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO iss_positions (latitude, longitude, altitude, timestamp, day) VALUES (?, ?, ?, ?, ?)",
                (lat, lon, alt, ts_utc, day))
    conn.commit()
    conn.close()

def cleanup_old_data():
    # Remove data older than MAX_RETENTION_DAYS
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
    # Return index.html for the main dashboard
    return send_file("index.html") if os.path.exists("index.html") else "ISS Tracker API", 200

@app.route("/database")
def database_viewer():
    # Return database.html for the full records viewer
    return send_file("database.html") if os.path.exists("database.html") else "Database Viewer Not Found", 404

@app.route("/api/current")
def api_current():
    # Attempt to fetch latest from API and save
    pos = fetch_iss_position()
    if pos:
        save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
        return jsonify(pos)
    
    # Fallback to last saved record if API fails
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT latitude, longitude, altitude, timestamp AS ts_utc, day FROM iss_positions ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        return jsonify({"latitude": row["latitude"], "longitude": row["longitude"],
                        "altitude": row["altitude"], "ts_utc": row["ts_utc"], "day": row["day"]})
    
    return jsonify({"error": "No data available"}), 404

@app.route("/api/last3days")
def api_last3days():
    # Retrieve all data within the retention period (latest 3 days)
    cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT latitude, longitude, altitude, timestamp AS ts_utc, day FROM iss_positions WHERE timestamp >= ? ORDER BY timestamp ASC", (cutoff,))
    rows = cur.fetchall()
    conn.close()
    return jsonify([{"latitude": r["latitude"], "longitude": r["longitude"], "altitude": r["altitude"], "ts_utc": r["ts_utc"], "day": r["day"]} for r in rows])

@app.route("/api/stats")
def api_stats():
    conn = get_conn()
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
    
    conn = get_conn()
    cur = conn.cursor()
    
    # 1. Get available days
    cur.execute("SELECT DISTINCT day FROM iss_positions ORDER BY day DESC")
    available_days = [row["day"] for row in cur.fetchall()]

    # 2. Build WHERE clause and get total count
    where_clause = ""
    params = []
    if day_filter:
        where_clause = "WHERE day = ?"
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
        LIMIT ? OFFSET ?
    """
    params.extend([per_page, offset])
    cur.execute(query, params)
    records = cur.fetchall()
    conn.close()
    
    return jsonify({
        "total": total_records,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "available_days": available_days,
        "records": [{"id": r["id"], "latitude": r["latitude"], "longitude": r["longitude"], "altitude": r["altitude"], "ts_utc": r["ts_utc"], "day": r["day"]} for r in records]
    })

@app.route("/api/download-csv")
def api_download_csv():
    day_filter = request.args.get('day', 'all')
    
    conn = get_conn()
    cur = conn.cursor()
    
    # Build query
    where_clause = ""
    params = []
    if day_filter and day_filter != 'all':
        where_clause = "WHERE day = ?"
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
    init_db()
    Thread(target=background_loop, daemon=True).start()
    logger.info(f"Starting ISS Tracker on 0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
