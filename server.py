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
# Global ISS data storage
# ---------------------------
ISS_DATA = []  # list of dicts: ts_utc, latitude, longitude, altitude, velocity

# ---------------------------
# Function to fetch ISS data from WTIA API
# ---------------------------
def fetch_iss_data_periodically():
    while True:
        try:
            res = requests.get("https://api.wheretheiss.at/v1/satellites/25544")
            if res.status_code == 200:
                d = res.json()
                record = {
                    "ts_utc": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "latitude": round(d.get("latitude", 0), 4),
                    "longitude": round(d.get("longitude", 0), 4),
                    "altitude": round(d.get("altitude", 0), 2),  # km
                    "velocity": round(d.get("velocity", 0), 2)   # km/h
                }
                ISS_DATA.append(record)
                # Keep only last 3 days (~4320 points if 1 per minute)
                if len(ISS_DATA) > 4320:
                    ISS_DATA.pop(0)
            else:
                print("WTIA API error:", res.status_code)
        except Exception as e:
            print("Error fetching ISS data:", e)
        time.sleep(60)  # wait 1 minute before next fetch

# Start background thread
threading.Thread(target=fetch_iss_data_periodically, daemon=True).start()

# ---------------------------
# Routes
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
