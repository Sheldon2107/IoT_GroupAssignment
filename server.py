from flask import Flask, jsonify, send_from_directory, request
import requests
import time
import threading

app = Flask(__name__)

# In-memory storage for simplicity
# Each record: {"latitude": float, "longitude": float, "altitude": float, "velocity": float, "timestamp": int}
records = []

ISS_API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 5  # seconds, safe for testing; for real 3-day tracking, increase interval to 1s-10s

# Function to fetch ISS data periodically
def fetch_iss_data():
    while True:
        try:
            r = requests.get(ISS_API_URL, timeout=5)
            if r.status_code == 200:
                data = r.json()
                record = {
                    "latitude": data.get("latitude", 0),
                    "longitude": data.get("longitude", 0),
                    "altitude": data.get("altitude", 0),
                    "velocity": data.get("velocity", 0),
                    "timestamp": int(time.time())
                }
                records.append(record)
                # Keep only last 3 days of data (optional, limit memory)
                # For demonstration, limit to last 1000 points
                if len(records) > 1000:
                    records.pop(0)
            else:
                print("ISS API returned", r.status_code)
        except Exception as e:
            print("Error fetching ISS data:", e)
        time.sleep(FETCH_INTERVAL)

# Start background thread to fetch ISS data
threading.Thread(target=fetch_iss_data, daemon=True).start()

# Routes
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/database.html')
def database():
    return send_from_directory('.', 'database.html')

@app.route('/api/preview')
def preview():
    try:
        day_index = int(request.args.get("day_index", 0))
        # For now, we ignore day_index and return all records
        return jsonify({"records": records})
    except Exception as e:
        print("Error in /api/preview:", e)
        return jsonify({"error": str(e)}), 500

@app.route('/api/download')
def download():
    try:
        csv_data = "timestamp,latitude,longitude,altitude,velocity\n"
        for r in records:
            csv_data += f"{r['timestamp']},{r['latitude']},{r['longitude']},{r['altitude']},{r['velocity']}\n"
        return csv_data, 200, {
            "Content-Type": "text/csv",
            "Content-Disposition": "attachment; filename=iss_data.csv"
        }
    except Exception as e:
        print("Error in /api/download:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
