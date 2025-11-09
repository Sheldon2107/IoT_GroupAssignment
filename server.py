# server.py
from flask import Flask, jsonify, send_file, request
import requests, sqlite3, os, threading, time
from datetime import datetime, timedelta

app = Flask(__name__)

DB_FILE = "iss_data.db"
API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 10  # seconds

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
            altitude REAL
        )
        """)
        conn.commit()
        conn.close()
        print("[DB] Initialized new database.")

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
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("INSERT INTO records (ts_utc, latitude, longitude, altitude) VALUES (?,?,?,?)",
                          (ts, lat, lon, alt))
                conn.commit()
                conn.close()
                print(f"[Fetch] {ts} Lat:{lat} Lon:{lon} Alt:{alt} km")
        except Exception as e:
            print("[Fetch Error]", e)
        time.sleep(FETCH_INTERVAL)

# --- API Routes ---

# Serve main dashboard
@app.route("/")
def index():
    return send_file("index.html")

# Database viewer page
@app.route("/database")
def database():
    return send_file("database.html")

# Preview API for charts / index.html
@app.route("/api/preview")
def api_preview():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT ts_utc, latitude, longitude, altitude FROM records ORDER BY id ASC")
    rows = c.fetchall()
    conn.close()
    records = [{"ts_utc": r[0], "latitude": r[1], "longitude": r[2], "altitude": r[3]} for r in rows]
    return jsonify({"records": records})

# Last 3 days data
@app.route("/api/last3days")
def api_last3days():
    cutoff = datetime.utcnow() - timedelta(days=3)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT ts_utc, latitude, longitude, altitude FROM records WHERE ts_utc >= ? ORDER BY id ASC",
              (cutoff.strftime("%Y-%m-%d %H:%M:%S"),))
    rows = c.fetchall()
    conn.close()
    records = [{"ts_utc": r[0], "latitude": r[1], "longitude": r[2], "altitude": r[3]} for r in rows]
    return jsonify(records)

# Download full database
@app.route("/api/download")
def api_download():
    return send_file(DB_FILE, as_attachment=True)

# --- Start background thread and server ---
if __name__ == "__main__":
    init_db()
    t = threading.Thread(target=fetch_loop, daemon=True)
    t.start()
    print("[Server] Starting Flask server on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
