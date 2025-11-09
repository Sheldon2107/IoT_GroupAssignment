from flask import Flask, jsonify, send_file, request, make_response
import requests, sqlite3, os, threading, time, csv, io
from datetime import datetime, timedelta

app = Flask(__name__)

DB_FILE = "iss_data.db"
API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 10  # seconds
MAX_RETENTION_DAYS = 3

# --- Initialize SQLite Database ---
def init_db():
    if not os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
        CREATE TABLE records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT,
            latitude REAL,
            longitude REAL,
            altitude REAL,
            velocity REAL
        )
        """)
        conn.commit()
        conn.close()

# --- Background Fetch Loop ---
def fetch_loop():
    while True:
        try:
            r = requests.get(API_URL, timeout=5)
            if r.status_code == 200:
                data = r.json()
                ts = datetime.utcfromtimestamp(data["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                lat = float(data["latitude"])
                lon = float(data["longitude"])
                alt = float(data["altitude"])
                vel = float(data.get("velocity", 0.0))

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("INSERT INTO records (ts_utc, latitude, longitude, altitude, velocity) VALUES (?,?,?,?,?)",
                          (ts, lat, lon, alt, vel))
                
                cutoff = datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)
                c.execute("DELETE FROM records WHERE ts_utc < ?", (cutoff.strftime("%Y-%m-%d %H:%M:%S"),))

                conn.commit()
                conn.close()
        except Exception as e:
            print("Fetch Error:", e)
        time.sleep(FETCH_INTERVAL)

# --- API Routes ---

@app.route("/")
def index():
    return send_file("index.html")

@app.route("/database.html")
def database():
    return send_file("database.html")

@app.route("/api/preview")
def api_preview():
    cutoff = datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT ts_utc, latitude, longitude, altitude, velocity
        FROM records
        WHERE ts_utc >= ?
        ORDER BY ts_utc ASC
    """, (cutoff.strftime("%Y-%m-%d %H:%M:%S"),))
    rows = c.fetchall()
    conn.close()
    records = [{"ts_utc": r[0], "latitude": r[1], "longitude": r[2], "altitude": r[3], "velocity": r[4]} for r in rows]
    return jsonify({"records": records})

@app.route("/api/download")
def api_download():
    return send_file(DB_FILE, as_attachment=True)

@app.route("/api/stats")
def api_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT MAX(latitude), MIN(latitude), MAX(longitude), MIN(longitude), MAX(altitude), MIN(altitude) FROM records")
    max_lat, min_lat, max_lon, min_lon, max_alt, min_alt = c.fetchone()
    conn.close()
    return jsonify({
        "min_latitude": min_lat,
        "max_latitude": max_lat,
        "min_longitude": min_lon,
        "max_longitude": max_lon,
        "min_altitude": min_alt,
        "max_altitude": max_alt
    })

# --- NEW: API to get days with data ---
@app.route("/api/days-with-data")
def api_days_with_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT DATE(ts_utc) as day, 
               COUNT(*) as record_count,
               MIN(ts_utc) as first_record,
               MAX(ts_utc) as last_record
        FROM records
        GROUP BY DATE(ts_utc)
        ORDER BY day ASC
    """)
    rows = c.fetchall()
    conn.close()
    
    days = [{"day": r[0], "record_count": r[1], "first_record": r[2], "last_record": r[3]} for r in rows]
    return jsonify({"days": days})

# --- NEW: API to get all records with pagination and filtering by day ---
@app.route("/api/all-records")
def api_all_records():
    day = request.args.get('day', None)
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 100))
    offset = (page - 1) * per_page
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    if day:
        # Filter by specific day
        c.execute("SELECT COUNT(*) FROM records WHERE DATE(ts_utc) = ?", (day,))
        total = c.fetchone()[0]
        
        c.execute("""
            SELECT id, ts_utc, latitude, longitude, altitude, velocity, DATE(ts_utc) as day
            FROM records
            WHERE DATE(ts_utc) = ?
            ORDER BY ts_utc ASC
            LIMIT ? OFFSET ?
        """, (day, per_page, offset))
    else:
        # Get all records
        c.execute("SELECT COUNT(*) FROM records")
        total = c.fetchone()[0]
        
        c.execute("""
            SELECT id, ts_utc, latitude, longitude, altitude, velocity, DATE(ts_utc) as day
            FROM records
            ORDER BY ts_utc ASC
            LIMIT ? OFFSET ?
        """, (per_page, offset))
    
    rows = c.fetchall()
    conn.close()
    
    records = [{
        "id": r[0],
        "ts_utc": r[1],
        "latitude": r[2],
        "longitude": r[3],
        "altitude": r[4],
        "velocity": r[5],
        "day": r[6]
    } for r in rows]
    
    return jsonify({
        "records": records,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page
    })

# --- NEW: Download CSV for specific day or all days ---
@app.route("/api/download-csv")
def api_download_csv():
    day = request.args.get('day', 'all')
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    if day == 'all':
        c.execute("""
            SELECT id, ts_utc, latitude, longitude, altitude, velocity
            FROM records
            ORDER BY ts_utc ASC
        """)
        filename = "iss_data_all_days.csv"
    else:
        c.execute("""
            SELECT id, ts_utc, latitude, longitude, altitude, velocity
            FROM records
            WHERE DATE(ts_utc) = ?
            ORDER BY ts_utc ASC
        """, (day,))
        filename = f"iss_data_{day}.csv"
    
    rows = c.fetchall()
    conn.close()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Timestamp (UTC)', 'Latitude', 'Longitude', 'Altitude (km)', 'Velocity (km/h)'])
    writer.writerows(rows)
    
    # Create response
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-Type"] = "text/csv"
    
    return response

# --- Start background fetch thread ---
if __name__ == "__main__":
    init_db()
    t = threading.Thread(target=fetch_loop, daemon=True)
    t.start()
    print(f"ISS Tracker running. Fetching every {FETCH_INTERVAL}s...")
    app.run(host="0.0.0.0", port=5000, debug=True)
