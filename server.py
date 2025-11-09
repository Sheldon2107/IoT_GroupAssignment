from flask import Flask, jsonify, request, send_file
import requests, time, threading, csv, io
from datetime import datetime, timedelta

app = Flask(__name__)

# In-memory storage of ISS telemetry for 3 days
DATA_RETENTION_DAYS = 3
iss_data = []  # Each entry: {'ts_utc':..., 'latitude':..., 'longitude':..., 'altitude':..., 'velocity':...}

# WTIA API endpoint
ISS_URL = "https://api.wheretheiss.at/v1/satellites/25544"

def fetch_iss_data():
    while True:
        try:
            resp = requests.get(ISS_URL, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                record = {
                    'ts_utc': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    'latitude': data.get('latitude', 0),
                    'longitude': data.get('longitude', 0),
                    'altitude': data.get('altitude', 0),
                    'velocity': data.get('velocity', 0)
                }
                iss_data.append(record)

                # Remove old data beyond retention
                cutoff = datetime.utcnow() - timedelta(days=DATA_RETENTION_DAYS)
                iss_data[:] = [r for r in iss_data if datetime.strptime(r['ts_utc'], "%Y-%m-%d %H:%M:%S") >= cutoff]

            else:
                print(f"ISS API error: {resp.status_code}")
        except Exception as e:
            print(f"Error fetching ISS data: {e}")
        time.sleep(10)  # fetch every 10 seconds

# Start the background thread
threading.Thread(target=fetch_iss_data, daemon=True).start()

# API: Preview data for a specific day
@app.route("/api/preview")
def preview():
    try:
        day_index = int(request.args.get('day_index', 0))
        # Split data by day (0 = today, 1 = yesterday, 2 = 2 days ago)
        today = datetime.utcnow().date()
        target_date = today - timedelta(days=day_index)
        records = [r for r in iss_data if datetime.strptime(r['ts_utc'], "%Y-%m-%d %H:%M:%S").date() == target_date]
        return jsonify({"records": records})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# API: Download all stored data as CSV
@app.route("/api/download")
def download_csv():
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Timestamp (UTC)', 'Latitude (°)', 'Longitude (°)', 'Altitude (km)', 'Velocity (km/h)'])
        for r in iss_data:
            writer.writerow([r['ts_utc'], r['latitude'], r['longitude'], r['altitude'], r['velocity']])
        output.seek(0)
        return send_file(io.BytesIO(output.getvalue().encode()),
                         mimetype='text/csv',
                         as_attachment=True,
                         download_name='iss_data.csv')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Serve index.html and database.html if needed
@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/database.html")
def database():
    return app.send_static_file("database.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
