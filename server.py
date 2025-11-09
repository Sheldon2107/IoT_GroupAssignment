# server.py
from flask import Flask, jsonify, send_file
from datetime import datetime
import requests
import csv
import io

app = Flask(__name__)

# ---------------------------
# Global storage for ISS data history
# ---------------------------
ISS_DATA = []

# Max points to store to avoid memory issues
MAX_POINTS = 5000

# ---------------------------
# Function to fetch live ISS telemetry
# ---------------------------
def fetch_iss_live():
    url = "https://api.wheretheiss.at/v1/satellites/25544"
    try:
        res = requests.get(url, timeout=5)
        res.raise_for_status()
        data = res.json()
        record = {
            "ts_utc": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            "latitude": round(data.get("latitude", 0), 4),
            "longitude": round(data.get("longitude", 0), 4),
            "altitude": round(data.get("altitude", 0), 2),
            "velocity": round(data.get("velocity", 0), 2)
        }
        return record
    except Exception as e:
        print("ISS fetch error:", e)
        return None

# ---------------------------
# API: Preview for dashboard
# ---------------------------
@app.route('/api/preview')
def preview():
    record = fetch_iss_live()
    if record:
        ISS_DATA.append(record)
        if len(ISS_DATA) > MAX_POINTS:
            ISS_DATA.pop(0)  # remove oldest
    return jsonify({"records": ISS_DATA})

# ---------------------------
# API: Download CSV
# ---------------------------
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

# ---------------------------
# Routes for frontend
# ---------------------------
@app.route('/')
def index():
    return send_file('index.html')

@app.route('/database.html')
def database():
    return send_file('database.html')

# ---------------------------
if __name__ == '__main__':
    app.run(debug=True)
