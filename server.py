# server.py
import os
import sqlite3
import threading
import time
import csv
import io
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_file, request, make_response

import requests

# Configuration (can override with env vars)
DB_FILE = os.environ.get("DB_FILE", "iss_data.db")
API_URL = os.environ.get("ISS_API_URL", "https://api.wheretheiss.at/v1/satellites/25544")
FETCH_INTERVAL = int(os.environ.get("FETCH_INTERVAL_SEC", "60"))   # seconds between fetches (default 60s)
MAX_RETENTION_DAYS = int(os.environ.get("MAX_RETENTION_DAYS", "3"))
PORT = int(os.environ.get("PORT", "5000"))

app = Flask(__name__)

# ---------- DB init ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        altitude REAL NOT NULL,
        velocity REAL NOT NULL
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON records(ts_utc)")
    conn.commit()
    conn.close()
    print("✓ Database initialized:", DB_FILE)

# ---------- Background fetch loop ----------
def fetch_loop():
    print("✓ Background fetch thread started (interval={}s)".format(FETCH_INTERVAL))
    while True:
        try:
            r = requests.get(API_URL, timeout=10)
            if r.status_code == 200:
                data = r.json()
                # Convert timestamp to UTC string
                ts = datetime.utcfromtimestamp(int(data.get("timestamp", time.time()))).strftime("%Y-%m-%d %H:%M:%S")
                lat = float(data.get("latitude", 0.0))
                lon = float(data.get("longitude", 0.0))
                alt = float(data.get("altitude", 0.0))
                vel = float(data.get("velocity", 0.0))

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute(
                    "INSERT INTO records (ts_utc, latitude, longitude, altitude, velocity) VALUES (?,?,?,?,?)",
                    (ts, lat, lon, alt, vel)
                )
                # cleanup older than retention
                cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("DELETE FROM records WHERE ts_utc < ?", (cutoff,))
                conn.commit()
                conn.close()
                print(f"Saved {ts} | lat={lat:.4f} lon={lon:.4f} alt={alt:.2f} vel={vel:.2f}")
            else:
                print("API returned status:", r.status_code)
        except Exception as e:
            print("Fetch Error:", e)
        time.sleep(FETCH_INTERVAL)

# ---------- Helper to open DB ----------
def open_conn(row_factory=None):
    conn = sqlite3.connect(DB_FILE)
    if row_factory:
        conn.row_factory = row_factory
    return conn

# ---------- Endpoints ----------
@app.route("/")
def index():
    if os.path.exists("index.html"):
        return send_file("index.html")
    return "index.html not found", 404

@app.route("/database.html")
def database_page():
    if os.path.exists("database.html"):
        return send_file("database.html")
    return "database.html not found", 404

@app.route("/api/preview")
def api_preview():
    # returns last MAX_RETENTION_DAYS worth of records (ascending by ts)
    try:
        cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        conn = open_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT ts_utc, latitude, longitude, altitude, velocity
            FROM records
            WHERE ts_utc >= ?
            ORDER BY ts_utc ASC
        """, (cutoff,))
        rows = cur.fetchall()
        conn.close()
        records = [{"ts_utc": r[0], "latitude": r[1], "longitude": r[2], "altitude": r[3], "velocity": r[4]} for r in rows]
        return jsonify({"records": records})
    except Exception as e:
        print("Error /api/preview:", e)
        return jsonify({"records": [], "error": str(e)}), 500

@app.route("/api/days-with-data")
def api_days_with_data():
    try:
        conn = open_conn()
        c = conn.cursor()
        c.execute("""
            SELECT DATE(ts_utc) as day, COUNT(*) as record_count,
                   MIN(ts_utc) as first_record, MAX(ts_utc) as last_record
            FROM records
            GROUP BY DATE(ts_utc)
            ORDER BY day ASC
        """)
        rows = c.fetchall()
        conn.close()
        days = [{"day": r[0], "record_count": r[1], "first_record": r[2], "last_record": r[3]} for r in rows]
        return jsonify({"days": days})
    except Exception as e:
        print("Error /api/days-with-data:", e)
        return jsonify({"days": []}), 500

@app.route("/api/all-records")
def api_all_records():
    try:
        day = request.args.get('day', None)
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))
        offset = (page - 1) * per_page

        conn = open_conn()
        c = conn.cursor()

        if day:
            c.execute("SELECT COUNT(*) FROM records WHERE DATE(ts_utc) = ?", (day,))
            total = c.fetchone()[0]
            c.execute("""
                SELECT id, ts_utc, latitude, longitude, altitude, velocity, DATE(ts_utc) as day
                FROM records
                WHERE DATE(ts_utc) = ?
                ORDER BY ts_utc ASC
                LIMIT ? OFFSET ?
            """, (day, per_page, offset))
        else:
            c.execute("SELECT COUNT(*) FROM records")
            total = c.fetchone()[0]
            c.execute("""
                SELECT id, ts_utc, latitude, longitude, altitude, velocity, DATE(ts_utc) as day
                FROM records
                ORDER BY ts_utc ASC
                LIMIT ? OFFSET ?
            """, (per_page, offset))

        rows = c.fetchall()
        conn.close()
        records = [{"id": r[0], "ts_utc": r[1], "latitude": r[2], "longitude": r[3], "altitude": r[4], "velocity": r[5], "day": r[6]} for r in rows]
        total_pages = (total + per_page - 1) // per_page if total > 0 else 0
        return jsonify({"records": records, "total": total, "page": page, "per_page": per_page, "total_pages": total_pages})
    except Exception as e:
        print("Error /api/all-records:", e)
        return jsonify({"records": [], "total": 0}), 500

@app.route("/api/download")
def api_download_db():
    if os.path.exists(DB_FILE):
        return send_file(DB_FILE, as_attachment=True, download_name=os.path.basename(DB_FILE))
    return "DB not found", 404

@app.route("/api/download-csv")
def api_download_csv():
    try:
        day = request.args.get('day', 'all')
        conn = open_conn()
        cur = conn.cursor()
        if day == 'all':
            cur.execute("SELECT id, ts_utc, latitude, longitude, altitude, velocity FROM records ORDER BY ts_utc ASC")
            filename = "iss_data_all_days.csv"
        else:
            cur.execute("SELECT id, ts_utc, latitude, longitude, altitude, velocity FROM records WHERE DATE(ts_utc) = ? ORDER BY ts_utc ASC", (day,))
            filename = f"iss_data_{day}.csv"
        rows = cur.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Timestamp (UTC)', 'Latitude', 'Longitude', 'Altitude (km)', 'Velocity (km/h)'])
        for r in rows:
            writer.writerow(r)
        output.seek(0)
        resp = make_response(output.getvalue())
        resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
        resp.headers["Content-Type"] = "text/csv"
        return resp
    except Exception as e:
        print("Error /api/download-csv:", e)
        return str(e), 500

# ---------- Start ----------
if __name__ == "__main__":
    print("Starting ISS Tracker server...")
    init_db()
    t = threading.Thread(target=fetch_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
