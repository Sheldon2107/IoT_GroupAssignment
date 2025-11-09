# server.py
from flask import Flask, jsonify, send_file
from datetime import datetime
import requests
import threading
import time
import csv
import io

app = Flask(__name__)

# ---------------------------
# Global configuration
# ---------------------------
ISS_DATA = []  # Store ISS telemetry history
FETCH_INTERVAL_SECONDS = 10  # Fetch data every 10 seconds

# ---------------------------
# Function to fetch ISS telemetry
# ---------------------------
def fetch_iss_data():
    """Fetch ISS position from WTIA API and store in ISS_DATA."""
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

# ---------------------------
# Start background thread to fetch data
# ---------------------------
threading.Thread(target=fetch_iss_data, daemon=True).start()

# ---------------------------
# Flask routes
# ---------------------------
@app.route('/api/preview')
def preview():
    """Return ISS data for dashboard playback."""
    return jsonify({"records": ISS_DATA})

@app.route('/api/download')
def download():
    """Return ISS data as CSV file."""
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
    """Serve index.html."""
    return send_file('index.html')

@app.route('/database.html')
def database():
    """Serve database.html."""
    return send_file('database.html')

# ---------------------------
# Run Flask app
# ---------------------------
if __name__ == '__main__':
    # Use 0.0.0.0 if you want to access it from other devices
    app.run(debug=True, host='0.0.0.0', port=5000)
