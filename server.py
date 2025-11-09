# server.py
from flask import Flask, jsonify, send_file
import requests
import pandas as pd
import threading
import time
from datetime import datetime, timedelta
import os

app = Flask(__name__)

CSV_FILE = 'iss_data.csv'
WTIA_API_URL = 'https://api.wheretheiss.at/v1/satellites/25544'
FETCH_INTERVAL = 1  # seconds

# Initialize CSV if not exists
if not os.path.exists(CSV_FILE):
    df = pd.DataFrame(columns=['timestamp','latitude','longitude','altitude','velocity'])
    df.to_csv(CSV_FILE, index=False)

def fetch_iss_data():
    """Fetch ISS telemetry every second and append to CSV."""
    while True:
        try:
            response = requests.get(WTIA_API_URL)
            if response.status_code == 200:
                data = response.json()
                record = {
                    'timestamp': datetime.utcfromtimestamp(data['timestamp']).isoformat(),
                    'latitude': data['latitude'],
                    'longitude': data['longitude'],
                    'altitude': data.get('altitude',0),  # km
                    'velocity': data.get('velocity',0)   # km/h
                }
                df = pd.read_csv(CSV_FILE)
                df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
                df.to_csv(CSV_FILE, index=False)
            else:
                print(f"ISS API error: {response.status_code}")
        except Exception as e:
            print(f"Error fetching ISS data: {e}")
        time.sleep(FETCH_INTERVAL)

@app.route('/api/preview')
def preview():
    """
    Return ISS records for a given day_index.
    day_index=0 → today
    day_index=1 → yesterday, etc.
    """
    day_index = int(request.args.get('day_index', 0))
    df = pd.read_csv(CSV_FILE)
    if df.empty:
        return jsonify({"records":[]})

    # Compute date range for the requested day
    today = datetime.utcnow().date()
    day_start = datetime.combine(today - timedelta(days=day_index), datetime.min.time())
    day_end = day_start + timedelta(days=1)

    # Filter records for this day
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df_day = df[(df['timestamp'] >= day_start) & (df['timestamp'] < day_end)]
    records = df_day.to_dict(orient='records')
    return jsonify({"records": records})

@app.route('/api/download')
def download():
    """Download full CSV file."""
    return send_file(CSV_FILE, mimetype='text/csv', as_attachment=True)

if __name__ == '__main__':
    # Start background thread for fetching ISS data
    thread = threading.Thread(target=fetch_iss_data, daemon=True)
    thread.start()
    app.run(host='0.0.0.0', port=5000)
