# server.py
import os
import time
import sqlite3
import logging
import requests
import csv
from io import StringIO
from datetime import datetime, timedelta
from threading import Thread, Event
from flask import Flask, jsonify, send_file, request, Response
from flask_cors import CORS

# ---------- Configuration ----------
DB_PATH = os.environ.get("DB_PATH", "iss_data.db")
API_URL = os.environ.get("ISS_API_URL", "https://api.wheretheiss.at/v1/satellites/25544")
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL_SEC", "5"))  # seconds
MAX_RETENTION_DAYS = int(os.environ.get("MAX_RETENTION_DAYS", "3"))
PORT = int(os.environ.get("PORT", "10000"))

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
def database_page():
    return send_file("database.html") if os.path.exists("database.html") else "Database viewer not found", 404

@app.route("/api/current")
def api_current():
    pos = fetch_iss_position()
    if pos:
        save_position(pos["latitude"], pos["longitude"], pos["altitude"], pos["ts_utc"])
        return jsonify(pos)
    # fallback to last saved
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
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 1000))
    day_filter = request.args.get('day', '')
    
    conn = get_conn()
    cur = conn.cursor()
    
    # Get available days
    cur.execute("SELECT DISTINCT day FROM iss_positions ORDER BY day DESC")
    available_days = [row['day'] for row in cur.fetchall()]
    
    # Build query with optional day filter
    where_clause = ""
    params = []
    if day_filter:
        where_clause = "WHERE day = ?"
        params.append(day_filter)
    
    # Get total count
    cur.execute(f"SELECT COUNT(*) FROM iss_positions {where_clause}", params)
    total = cur.fetchone()[0]
    
    # Calculate pagination
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page
    
    # Get records
    cur.execute(f"""
        SELECT id, latitude, longitude, altitude, timestamp AS ts_utc, day 
        FROM iss_positions {where_clause}
        ORDER BY timestamp DESC 
        LIMIT ? OFFSET ?
    """, params + [per_page, offset])
    
    records = [{
        "id": r["id"],
        "latitude": r["latitude"],
        "longitude": r["longitude"],
        "altitude": r["altitude"],
        "ts_utc": r["ts_utc"],
        "day": r["day"]
    } for r in cur.fetchall()]
    
    conn.close()
    
    return jsonify({
        "records": records,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "available_days": available_days
    })

@app.route("/api/download-csv")
def download_csv():
    """Download CSV file with optional date filtering"""
    day_filter = request.args.get('day', '')  # Can be specific date or 'all'
    
    conn = get_conn()
    cur = conn.cursor()
    
    # Build query
    if day_filter and day_filter != 'all':
        cur.execute("""
            SELECT id, timestamp, day, latitude, longitude, altitude 
            FROM iss_positions 
            WHERE day = ?
            ORDER BY timestamp ASC
        """, (day_filter,))
        filename = f"iss_data_{day_filter}.csv"
    else:
        cur.execute("""
            SELECT id, timestamp, day, latitude, longitude, altitude 
            FROM iss_positions 
            ORDER BY timestamp ASC
        """)
        filename = "iss_data_all.csv"
    
    rows = cur.fetchall()
    conn.close()
    
    # Create CSV in memory
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['ID', 'Timestamp (UTC)', 'Day', 'Latitude', 'Longitude', 'Altitude (km)'])
    
    for row in rows:
        writer.writerow([
            row['id'],
            row['timestamp'],
            row['day'],
            f"{row['latitude']:.6f}",
            f"{row['longitude']:.6f}",
            f"{row['altitude']:.2f}" if row['altitude'] else ""
        ])
    
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

@app.route("/api/days-with-data")
def api_days_with_data():
    """Get list of days that actually have data"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT day, COUNT(*) as record_count, 
               MIN(timestamp) as first_record, 
               MAX(timestamp) as last_record
        FROM iss_positions 
        GROUP BY day 
        ORDER BY day ASC
    """)
    days = [{
        "day": r["day"],
        "record_count": r["record_count"],
        "first_record": r["first_record"],
        "last_record": r["last_record"]
    } for r in cur.fetchall()]
    conn.close()
    return jsonify({"days": days})

# ---------- Startup ----------
if __name__ == "__main__":
    init_db()
    Thread(target=background_loop, daemon=True).start()
    logger.info(f"Starting ISS Tracker on 0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
