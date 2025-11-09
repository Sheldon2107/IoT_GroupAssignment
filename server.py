# server.py  (FINAL FIXED VERSION)

import os
import sqlite3
import threading
import time
import csv
import io
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_file, request, make_response

import requests

# -------------------------------------------------
# CONFIG
# -------------------------------------------------

DB_FILE = "iss_data.db"
API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 60             # fetch every 60 sec (safe)
MAX_RETENTION_DAYS = 3          # keep 3 days of data
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)

# -------------------------------------------------
# INIT DATABASE
# -------------------------------------------------

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
    );
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON records(ts_utc);")
    conn.commit()
    conn.close()
    print("✅ DATABASE READY:", DB_FILE)

# -------------------------------------------------
# BACKGROUND FETCH LOOP
# -------------------------------------------------

def fetch_loop():
    print(f"✅ Background fetch started ({FETCH_INTERVAL}s interval)")
    while True:
        try:
            response = requests.get(API_URL, timeout=10)
            if response.status_code == 200:
                json = response.json()

                ts = datetime.utcfromtimestamp(json["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                lat = float(json["latitude"])
                lon = float(json["longitude"])
                alt = float(json["altitude"])
                vel = float(json["velocity"])

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()

                c.execute(
                    "INSERT INTO records (ts_utc, latitude, longitude, altitude, velocity) VALUES (?,?,?,?,?)",
                    (ts, lat, lon, alt, vel)
                )

                # Delete data older than X days
                cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
                c.execute("DELETE FROM records WHERE ts_utc < ?", (cutoff,))

                conn.commit()
                conn.close()

                print(f"✅ SAVED  {ts} | lat={lat:.2f} lon={lon:.2f} alt={alt:.2f} vel={vel:.2f}")

        except Exception as e:
            print("❌ FETCH ERROR:", e)

        time.sleep(FETCH_INTERVAL)

# -------------------------------------------------
# HELPERS
# -------------------------------------------------

def open_conn():
    return sqlite3.connect(DB_FILE)

# -------------------------------------------------
# ROUTES
# -------------------------------------------------

# Main Dashboard
@app.route("/")
def index_page():
    return send_file("index.html")

# FIXED — Serve database page
@app.route("/database.html")
def database_html():
    return send_file("database.html")

# FIXED — Allow /database also
@app.route("/database")
def database_redirect():
    return send_file("database.html")

# API for preview data (index chart + map)
@app.route("/api/preview")
def api_preview():
    try:
        cutoff = (datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")

        conn = open_conn()
        c = conn.cursor()
        c.execute("""
            SELECT ts_utc, latitude, longitude, altitude, velocity
            FROM records
            WHERE ts_utc >= ?
            ORDER BY ts_utc ASC
        """, (cutoff,))
        rows = c.fetchall()
        conn.close()

        records = [
            {
                "ts_utc": r[0],
                "latitude": r[1],
                "longitude": r[2],
                "altitude": r[3],
                "velocity": r[4]
            }
            for r in rows
        ]

        return jsonify({"records": records})

    except Exception as e:
        print("❌ ERROR /api/preview:", e)
        return jsonify({"records": [], "error": str(e)}), 500

# List days with stored data
@app.route("/api/days-with-data")
def api_days():
    try:
        conn = open_conn()
        c = conn.cursor()
        c.execute("""
            SELECT DATE(ts_utc), COUNT(*),
                   MIN(ts_utc), MAX(ts_utc)
            FROM records
            GROUP BY DATE(ts_utc)
            ORDER BY DATE(ts_utc)
        """)
        rows = c.fetchall()
        conn.close()

        days = [{
            "day": r[0],
            "record_count": r[1],
            "first_record": r[2],
            "last_record": r[3]
        } for r in rows]

        return jsonify({"days": days})

    except Exception as e:
        print("❌ ERROR /api/days-with-data:", e)
        return jsonify({"days": []}), 500

# Download DB
@app.route("/api/download")
def api_download_db():
    return send_file(DB_FILE, as_attachment=True)

# Download CSV
@app.route("/api/download-csv")
def api_csv():
    try:
        day = request.args.get('day', 'all')

        conn = open_conn()
        c = conn.cursor()

        if day == "all":
            c.execute("SELECT * FROM records ORDER BY ts_utc ASC")
            filename = "iss_all_data.csv"
        else:
            c.execute("SELECT * FROM records WHERE DATE(ts_utc)=? ORDER BY ts_utc ASC", (day,))
            filename = f"iss_{day}.csv"

        rows = c.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "timestamp", "latitude", "longitude", "altitude", "velocity"])

        for row in rows:
            writer.writerow(row)

        output.seek(0)
        resp = make_response(output.getvalue())
        resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
        resp.headers["Content-Type"] = "text/csv"
        return resp

    except Exception as e:
        print("❌ CSV ERROR:", e)
        return str(e), 500

# -------------------------------------------------
# START SERVER
# -------------------------------------------------

if __name__ == "__main__":
    print("🚀 STARTING ISS TRACKING SERVER...")
    init_db()

    thread = threading.Thread(target=fetch_loop, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=PORT, debug=False)
