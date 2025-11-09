from flask import Flask, jsonify, send_file
from datetime import datetime
import requests
import csv
import io
import threading
import time

app = Flask(__name__)

# ---------------------------
# Global ISS Data Storage
# ---------------------------
ISS_DATA = []

FETCH_INTERVAL_SECONDS = 10  # fetch every 10 seconds

# ---------------------------
# Function to fetch real ISS telemetry
# ---------------------------
def fetch_iss_data():
    while True:
        try:
            res = requests.get("https://api.wheretheiss.at/v1/satellites/25544")
            if res.status_code == 200:
                data = res.json()
                record = {
                    "ts_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "latitude": round(data.get("latitude", 0), 4),
                    "longitude": round(data.get("longitude", 0), 4),
                    "altitude": round(data.get("altitude", 0), 2),
                    "velocity": round(data.get("velocity", 0), 2)
                }
                ISS_DATA.append(record)
                print(f"[{record['ts_utc']}] Fetched ISS position: Lat {record['latitude']}, Lon {record['longitude']}")
            else:
                print(f"Error fetching ISS data: HTTP {res.status_code}")
        except Exception as e:
            print(f"Exception during ISS fetch: {e}")

        time.sleep(FETCH_INTERVAL_SECONDS)

# Start background thread to fetch ISS data continuously
threading.Thread(target=fetch_iss_data, daemon=True).start()

# ---------------------------
# Flask Routes
# ---------------------------

@app.route('/api/preview')
def preview():
    return jsonify({"records": ISS_DATA})

@app.route('/api/download')
def download():
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
