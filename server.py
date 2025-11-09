from flask import Flask, jsonify, send_file, request
import csv, os
from datetime import datetime, timezone

app = Flask(__name__)

CSV_FILE = "iss_data.csv"

# Ensure CSV exists with headers
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_utc", "latitude", "longitude", "altitude", "velocity"])

# Helper to read CSV
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
                    continue
    return records

# Serve index and database pages
@app.route("/")
def index():
    return send_file("index.html")

@app.route("/database.html")
def database():
    return send_file("database.html")

# CSV download
@app.route("/api/download")
def download_csv():
    try:
        return send_file(CSV_FILE, as_attachment=True)
    except Exception as e:
        return str(e), 500

# Preview API (all data, ignore day_index)
@app.route("/api/preview")
def api_preview():
    records = read_iss_csv()
    # Compute delta altitude
    for i in range(1, len(records)):
        records[i]['delta_altitude'] = records[i]['altitude'] - records[i-1]['altitude']
    if records:
        records[0]['delta_altitude'] = 0
    return jsonify({"records": records})

# Add sample data (for testing)
@app.route("/api/add_sample")
def add_sample():
    import random
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    lat = random.uniform(-90, 90)
    lon = random.uniform(-180, 180)
    alt = random.uniform(400, 420)
    vel = random.uniform(27000, 28000)
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([ts, lat, lon, alt, vel])
    return jsonify({"status":"ok","record":{"ts_utc":ts,"latitude":lat,"longitude":lon,"altitude":alt,"velocity":vel}})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=10000)
