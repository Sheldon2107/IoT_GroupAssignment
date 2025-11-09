from flask import Flask, jsonify, send_file, request
import sqlite3
import csv
from io import StringIO
from datetime import datetime, timedelta
import requests
import threading
import time

app = Flask(__name__)

DB_FILE = "iss_data.db"

# Initialize DB
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
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

init_db()

# Background ISS fetch every 10 seconds
def fetch_iss_data():
    while True:
        try:
            res = requests.get("https://api.wheretheiss.at/v1/satellites/25544")
            if res.status_code == 200:
                data = res.json()
                ts_utc = datetime.utcfromtimestamp(data["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                lat = data.get("latitude", 0)
                lon = data.get("longitude", 0)
                alt = data.get("altitude", 0)
                vel = data.get("velocity", 0)
                
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO telemetry (ts_utc, latitude, longitude, altitude, velocity)
                    VALUES (?,?,?,?,?)
                """, (ts_utc, lat, lon, alt, vel))
                conn.commit()
                conn.close()
        except Exception as e:
            print("Error fetching ISS data:", e)
        time.sleep(10)

# Start background thread
threading.Thread(target=fetch_iss_data, daemon=True).start()

# API for preview table / dashboard
@app.route("/api/preview")
def api_preview():
    day_index = int(request.args.get("day_index", 0))
    target_day = datetime.utcnow() - timedelta(days=day_index)
    day_start = target_day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ts_utc, latitude, longitude, altitude, velocity
        FROM telemetry
        WHERE ts_utc BETWEEN ? AND ?
        ORDER BY ts_utc ASC
    """, (day_start.strftime("%Y-%m-%d %H:%M:%S"), day_end.strftime("%Y-%m-%d %H:%M:%S")))
    rows = cursor.fetchall()
    conn.close()

    records = []
    for r in rows:
        records.append({
            "ts_utc": r[0],
            "latitude": r[1],
            "longitude": r[2],
            "altitude": r[3],
            "velocity": r[4]
        })

    # Add last change in altitude
    for i in range(1, len(records)):
        records[i]["delta_altitude"] = records[i]["altitude"] - records[i-1]["altitude"]
    if records:
        records[0]["delta_altitude"] = 0

    return jsonify({"records": records})

# CSV download
@app.route("/api/download")
def api_download():
    day_index = int(request.args.get("day_index", 0))
    target_day = datetime.utcnow() - timedelta(days=day_index)
    day_start = target_day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ts_utc, latitude, longitude, altitude, velocity
        FROM telemetry
        WHERE ts_utc BETWEEN ? AND ?
        ORDER BY ts_utc ASC
    """, (day_start.strftime("%Y-%m-%d %H:%M:%S"), day_end.strftime("%Y-%m-%d %H:%M:%S")))
    rows = cursor.fetchall()
    conn.close()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Timestamp (UTC)", "Latitude (°)", "Longitude (°)", "Altitude (km)", "Velocity (km/h)"])
    for r in rows:
        writer.writerow(r)

    si.seek(0)
    return send_file(
        si,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"iss_data_day{day_index+1}.csv"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
