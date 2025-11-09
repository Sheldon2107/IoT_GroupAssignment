from flask import Flask, jsonify, send_from_directory, Response, request
import requests
import threading
import time
import csv
from datetime import datetime

app = Flask(__name__)

# In-memory storage for ISS telemetry
iss_data = []

# WTIA API URL
WTIA_URL = "https://api.wheretheiss.at/v1/satellites/25544"

# Lock for thread-safe access
data_lock = threading.Lock()

# Function to fetch ISS data every second (rate limit ~1 req/sec)
def fetch_iss_data():
    while True:
        try:
            r = requests.get(WTIA_URL)
            if r.status_code == 200:
                d = r.json()
                record = {
                    "latitude": d.get("latitude", 0.0),
                    "longitude": d.get("longitude", 0.0),
                    "altitude": d.get("altitude", 0.0),
                    "velocity": d.get("velocity", 0.0),
                    "timestamp": d.get("timestamp", time.time())
                }
                with data_lock:
                    iss_data.append(record)
            else:
                print(f"Error fetching ISS data: {r.status_code}")
        except Exception as e:
            print(f"Exception fetching ISS data: {e}")
        time.sleep(1)  # respect rate limit

# Start the background thread
threading.Thread(target=fetch_iss_data, daemon=True).start()

# Route to serve index.html
@app.route("/")
def home():
    return send_from_directory(".", "index.html")

# Route to serve database.html
@app.route("/database.html")
def database_page():
    return send_from_directory(".", "database.html")

# API route to preview ISS data
@app.route("/api/preview")
def api_preview():
    day_index = int(request.args.get("day_index", 0))
    with data_lock:
        return jsonify({"records": iss_data})

# API route to download CSV
@app.route("/api/download")
def api_download():
    with data_lock:
        if not iss_data:
            return "No data yet.", 404

        # Generate CSV content
        output = []
        output.append(["timestamp","latitude","longitude","altitude","velocity"])
        for d in iss_data:
            ts = datetime.fromtimestamp(d["timestamp"]).isoformat()
            output.append([ts, d["latitude"], d["longitude"], d["altitude"], d["velocity"]])

        csv_str = "\n".join([",".join(map(str,row)) for row in output])
        return Response(csv_str, mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=iss_data.csv"})

# Required for Render or local
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
