from flask import Flask, jsonify, send_from_directory, request
import requests, sqlite3, time, threading, os

app = Flask(__name__)
ISS_API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 5  # seconds, safe for testing
DB_FILE = 'iss_data.db'

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS records
                 (timestamp INTEGER PRIMARY KEY, latitude REAL, longitude REAL, altitude REAL, velocity REAL)''')
    conn.commit()
    conn.close()

def insert_record(data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO records (timestamp, latitude, longitude, altitude, velocity) VALUES (?,?,?,?,?)",
              (data['timestamp'], data['latitude'], data['longitude'], data['altitude'], data['velocity']))
    conn.commit()
    conn.close()

def fetch_all_records():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT timestamp, latitude, longitude, altitude, velocity FROM records ORDER BY timestamp ASC")
    rows = c.fetchall()
    conn.close()
    return [{"timestamp": r[0], "latitude": r[1], "longitude": r[2], "altitude": r[3], "velocity": r[4]} for r in rows]

# --- Fetch ISS Data ---
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
                insert_record(record)
                print(f"[INFO] Fetched record at {record['timestamp']}")
            else:
                print(f"[WARN] ISS API returned status {r.status_code}")
        except Exception as e:
            print(f"[ERROR] Fetching ISS data failed: {e}")
        time.sleep(FETCH_INTERVAL)

# --- Flask Routes ---
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/database.html')
def database():
    return send_from_directory('.', 'database.html')

@app.route('/api/preview')
def preview():
    day_index = int(request.args.get("day_index", 0))
    # TODO: implement day_index filtering if needed
    records = fetch_all_records()
    return jsonify({"records": records})

@app.route('/api/download')
def download():
    records = fetch_all_records()
    csv_data = "timestamp,latitude,longitude,altitude,velocity\n"
    for r in records:
        csv_data += f"{r['timestamp']},{r['latitude']},{r['longitude']},{r['altitude']},{r['velocity']}\n"
    return csv_data, 200, {
        "Content-Type": "text/csv",
        "Content-Disposition": "attachment; filename=iss_data.csv"
    }

# --- Main ---
if __name__ == '__main__':
    init_db()
    # Fetch one record immediately to prevent empty dashboard
    try:
        r = requests.get(ISS_API_URL, timeout=5).json()
        record = {
            "latitude": r.get("latitude",0),
            "longitude": r.get("longitude",0),
            "altitude": r.get("altitude",0),
            "velocity": r.get("velocity",0),
            "timestamp": int(time.time())
        }
        insert_record(record)
    except:
        print("[WARN] Initial fetch failed")

    # Start background thread
    threading.Thread(target=fetch_iss_data, daemon=True).start()
    app.run(debug=True, host='0.0.0.0')
