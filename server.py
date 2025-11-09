# server.py
from flask import Flask, jsonify, send_file, request
import requests, sqlite3, os, threading, time
from datetime import datetime, timedelta

app = Flask(__name__)

DB_FILE = "iss_data.db"
API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 10  # seconds
MAX_RETENTION_DAYS = 3

# --- Initialize SQLite Database ---
def init_db():
    if not os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
        CREATE TABLE records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT,
            latitude REAL,
            longitude REAL,
            altitude REAL,
            velocity REAL
        )
        """)
        conn.commit()
        conn.close()

# --- Background Fetch Loop ---
def fetch_loop():
    while True:
        try:
            r = requests.get(API_URL, timeout=5)
            if r.status_code == 200:
                data = r.json()
                ts = datetime.utcfromtimestamp(data["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                lat = float(data["latitude"])
                lon = float(data["longitude"])
                alt = float(data["altitude"])
                vel = float(data.get("velocity", 0.0))

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                # Insert new record
                c.execute("INSERT INTO records (ts_utc, latitude, longitude, altitude, velocity) VALUES (?,?,?,?,?)",
                          (ts, lat, lon, alt, vel))
                
                # Cleanup old records (>MAX_RETENTION_DAYS)
                cutoff = datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)
                c.execute("DELETE FROM records WHERE ts_utc < ?", (cutoff.strftime("%Y-%m-%d %H:%M:%S"),))

                conn.commit()
                conn.close()
        except Exception as e:
            print("Fetch Error:", e)
        time.sleep(FETCH_INTERVAL)

# --- API Routes ---

# Serve main dashboard
@app.route("/")
def index():
    return send_file("index.html")

# Preview API for dashboard (last 3 days)
@app.route("/api/preview")
def api_preview():
    day_index = request.args.get("day_index", default=0, type=int)
    cutoff = datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT ts_utc, latitude, longitude, altitude, velocity
        FROM records
        WHERE ts_utc >= ?
        ORDER BY ts_utc ASC
    """, (cutoff.strftime("%Y-%m-%d %H:%M:%S"),))
    rows = c.fetchall()
    conn.close()
    records = [{"ts_utc": r[0], "latitude": r[1], "longitude": r[2], "altitude": r[3], "velocity": r[4]} for r in rows]
    return jsonify({"records": records})

# Download database
@app.route("/api/download")
def api_download():
    return send_file(DB_FILE, as_attachment=True)

# Stats API (bonus: max/min altitude & longitude)
@app.route("/api/stats")
def api_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT MAX(latitude), MIN(latitude), MAX(longitude), MIN(longitude), MAX(altitude), MIN(altitude) FROM records")
    max_lat, min_lat, max_lon, min_lon, max_alt, min_alt = c.fetchone()
    conn.close()
    return jsonify({
        "min_latitude": min_lat,
        "max_latitude": max_lat,
        "min_longitude": min_lon,
        "max_longitude": max_lon,
        "min_altitude": min_alt,
        "max_altitude": max_alt
    })

# --- Start background fetch thread ---
if __name__ == "__main__":
    init_db()
    t = threading.Thread(target=fetch_loop, daemon=True)
    t.start()
    print(f"ISS Tracker running. Fetching every {FETCH_INTERVAL}s...")
    app.run(host="0.0.0.0", port=5000, debug=True)
