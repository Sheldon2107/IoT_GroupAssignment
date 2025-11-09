from flask import Flask, jsonify, send_file, render_template, request
import csv
import os
from datetime import datetime, timezone

app = Flask(__name__)

CSV_FILE = "iss_data.csv"

# Ensure CSV exists with headers
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_utc", "latitude", "longitude", "altitude", "velocity"])

# --- Helper to read CSV --- #
def read_iss_csv():
    records = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    records.append({
                        "ts_utc": row["ts_utc"],
                        "latitude": float(row["latitude"]),
                        "longitude": float(row["longitude"]),
                        "altitude": float(row["altitude"]),
                        "velocity": float(row["velocity"]),
                    })
                except:
                    pass
    return records

# --- Route for index.html --- #
@app.route("/")
def index():
    return send_file("index.html")

# --- Route for database.html --- #
@app.route("/database.html")
def database():
    return send_file("database.html")

# --- Route for CSV download --- #
@app.route("/api/download")
def download_csv():
    try:
        return send_file(CSV_FILE, as_attachment=True)
    except Exception as e:
        return str(e), 500

# --- Route for preview API --- #
@app.route("/api/preview")
def api_preview():
    day_index = int(request.args.get("day_index", 0))
    records = read_iss_csv()

    # Filter by day_index (0 = today, 1 = yesterday, etc.)
    filtered = []
    now = datetime.now(timezone.utc)
    for r in records:
        ts = datetime.strptime(r["ts_utc"], "%Y-%m-%d %H:%M:%S")
        ts = ts.replace(tzinfo=timezone.utc)
        delta_days = (now.date() - ts.date()).days
        if delta_days == day_index:
            filtered.append(r)

    return jsonify({"records": filtered})

# --- Route to simulate adding new data (for testing) --- #
@app.route("/api/add_sample")
def add_sample():
    # Just simulate a new ISS record with current UTC time
    import random
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    lat = random.uniform(-90, 90)
    lon = random.uniform(-180, 180)
    alt = random.uniform(400, 420)  # km
    vel = random.uniform(27000, 28000)  # km/h

    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([ts, lat, lon, alt, vel])

    return jsonify({"status":"ok","record":{"ts_utc":ts,"latitude":lat,"longitude":lon,"altitude":alt,"velocity":vel}})

# --- Run the server --- #
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=10000)
