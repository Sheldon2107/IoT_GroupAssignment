# server.py
from flask import Flask, jsonify, send_file
from datetime import datetime
import requests
import csv
import io
import threading
import time

app = Flask(__name__)

# ---------------------------
# Global data store
# ---------------------------
ISS_DATA = []  # Stores all fetched ISS telemetry

API_URL = "https://api.wheretheiss.at/v1/satellites/25544"

# ---------------------------
# Function to fetch ISS telemetry
# ---------------------------
def fetch_iss_data():
    while True:
        try:
            res = requests.get(API_URL, timeout=5)
            if res.status_code == 200:
                data = res.json()
                record = {
                    "ts_utc": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    "latitude": round(data.get("latitude", 0), 4),
                    "longitude": round(data.get("longitude", 0), 4),
                    "altitude": round(data.get("altitude", 0), 2),   # in km
                    "velocity": round(data.get("velocity", 0), 2)    # in km/h
                }
                ISS_DATA.append(record)
                # Optional: keep data for 3+ days max
                # ISS_DATA[:] = ISS_DATA[-(3*24*60*6):]  # if fetching every 10s
            else:
                print(f"Failed to fetch ISS data. Status code: {res.status_code}")
        except Exception as e:
            print(f"Error fetching ISS data: {e}")
        time.sleep(10)  # fetch every 10 seconds (well below 1 request/sec)

# Start fetching in a separate thread so Flask can run
threading.Thread(target=fetch_iss_data, daemon=True).start()

# ---------------------------
# Routes
# ---------------------------
@app.route('/api/preview')
def preview():
    """Return ISS telemetry for dashboard and database"""
    return jsonify({"records": ISS_DATA})

@app.route('/api/download')
def download():
    """Download ISS data as CSV"""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["ts_utc","latitude","longitude","altitude","velocity"])
    writer.writeheader()
    for row in ISS_DATA:
        writer.writerow(row)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='iss_data.csv'
    )

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/database.html')
def database():
    return send_file('database.html')

# ---------------------------
if __name__ == '__main__':
    app.run(debug=True)
