import os
import csv
import threading
import time
import requests
from flask import Flask, jsonify, send_file

app = Flask(__name__)

CSV_FILE = "iss_data.csv"
API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 10  # seconds; change if you want ~1/sec respecting API limits

# Initialize CSV if it doesn't exist
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp","latitude","longitude","altitude","velocity"])
        writer.writeheader()

# Thread-safe in-memory data
iss_data = []

def load_csv():
    """Load CSV data into memory."""
    global iss_data
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE,"r") as f:
            reader = csv.DictReader(f)
            iss_data = [ {k: float(v) if k != "timestamp" else v for k,v in row.items()} for row in reader ]

def save_to_csv(record):
    """Append a record to CSV."""
    with open(CSV_FILE,"a",newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp","latitude","longitude","altitude","velocity"])
        writer.writerow(record)

def fetch_iss_data():
    """Background thread: fetch ISS telemetry every FETCH_INTERVAL seconds."""
    global iss_data
    while True:
        try:
            res = requests.get(API_URL, timeout=5)
            if res.status_code == 200:
                data = res.json()
                record = {
                    "timestamp": data["timestamp"],
                    "latitude": data["latitude"],
                    "longitude": data["longitude"],
                    "altitude": data["altitude"],
                    "velocity": data["velocity"]
                }
                iss_data.append(record)
                save_to_csv(record)
        except Exception as e:
            print("Error fetching ISS data:", e)
        time.sleep(FETCH_INTERVAL)

# API endpoint for preview
@app.route("/api/preview")
def preview():
    """Return historical data for a given day_index (optional)."""
    load_csv()
    # For simplicity, ignore day_index split for now
    return jsonify({"records": iss_data})

# API endpoint to download CSV
@app.route("/api/download")
def download_csv():
    return send_file(CSV_FILE, as_attachment=True)

if __name__ == "__main__":
    load_csv()
    # Start background thread
    thread = threading.Thread(target=fetch_iss_data, daemon=True)
    thread.start()

    port = int(os.environ.get("PORT", 5000))  # Render requires this
    app.run(host="0.0.0.0", port=port)
