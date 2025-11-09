# server.py
from flask import Flask, jsonify, send_file
from datetime import datetime, timedelta
import random
import csv
import io

app = Flask(__name__)

# ---------------------------
# Generate some sample ISS data
# ---------------------------
def generate_iss_data():
    # Generate data for 100 points
    records = []
    base_time = datetime.utcnow() - timedelta(minutes=100)
    lat, lon, alt, vel = 0, 0, 420, 27600  # starting values
    for i in range(100):
        lat += random.uniform(-0.5, 0.5)
        lon += random.uniform(0.5, 1)
        alt += random.uniform(-1, 1)
        vel += random.uniform(-10, 10)
        ts = (base_time + timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')
        records.append({
            "ts_utc": ts,
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "altitude": round(alt, 2),
            "velocity": round(vel, 2)
        })
    return records

# Store data globally
ISS_DATA = generate_iss_data()

# ---------------------------
# Routes
# ---------------------------

@app.route('/api/preview')
def preview():
    """
    Return data for dashboard playback.
    Optional: ?day_index=0 (not used in this sample)
    """
    return jsonify({"records": ISS_DATA})

@app.route('/api/download')
def download():
    """
    Return ISS data as CSV file
    """
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
