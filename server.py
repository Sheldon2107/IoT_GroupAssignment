from flask import Flask, jsonify, send_file, request, make_response
import requests
import sqlite3
import os
import threading
import time
import csv
import io
from datetime import datetime, timedelta

app = Flask(__name__)

DB_FILE = "iss_data.db"
API_URL = "https://api.wheretheiss.at/v1/satellites/25544"
FETCH_INTERVAL = 60  # seconds
MAX_RETENTION_DAYS = 3

# --- Initialize SQLite Database ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        altitude REAL NOT NULL,
        velocity REAL NOT NULL
    )
    """)
    conn.commit()
    conn.close()
    print("✓ Database initialized")

# --- Background Fetch Loop ---
def fetch_loop():
    print("✓ Background fetch thread started")
    while True:
        try:
            r = requests.get(API_URL, timeout=10)
            if r.status_code == 200:
                data = r.json()
                ts = datetime.utcfromtimestamp(data["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                lat = float(data["latitude"])
                lon = float(data["longitude"])
                alt = float(data["altitude"])
                vel = float(data.get("velocity", 0.0))

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute(
                    "INSERT INTO records (ts_utc, latitude, longitude, altitude, velocity) VALUES (?,?,?,?,?)",
                    (ts, lat, lon, alt, vel)
                )
                
                cutoff = datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)
                c.execute("DELETE FROM records WHERE ts_utc < ?", (cutoff.strftime("%Y-%m-%d %H:%M:%S"),))

                conn.commit()
                conn.close()
                print(f"✓ Saved: {ts} | Lat: {lat:.2f} Lon: {lon:.2f} Alt: {alt:.2f}km")
            else:
                print(f"✗ API returned status {r.status_code}")
        except Exception as e:
            print(f"✗ Fetch Error: {e}")
        
        time.sleep(FETCH_INTERVAL)

# --- Routes ---

@app.route("/")
def index():
    if os.path.exists("index.html"):
        return send_file("index.html")
    return "index.html not found", 404

@app.route("/database.html")
def database():
    if os.path.exists("database.html"):
        return send_file("database.html")
    return "database.html not found", 404

@app.route("/api/preview")
def api_preview():
    try:
        cutoff = datetime.utcnow() - timedelta(days=MAX_RETENTION_DAYS)
        
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("""
            SELECT ts_utc, latitude, longitude, altitude, velocity
            FROM records
            WHERE ts_utc >= ?
            ORDER BY ts_utc ASC
        """, (cutoff.strftime("%Y-%m-%d %H:%M:%S"),))
        
        rows = c.fetchall()
        conn.close()
        
        records = []
        for row in rows:
            records.append({
                "ts_utc": row[0],
                "latitude": row[1],
                "longitude": row[2],
                "altitude": row[3],
                "velocity": row[4]
            })
        
        return jsonify({"records": records})
        
    except Exception as e:
        print(f"✗ Error in /api/preview: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"records": [], "error": str(e)}), 200

@app.route("/api/download")
def api_download():
    try:
        if os.path.exists(DB_FILE):
            return send_file(DB_FILE, as_attachment=True, download_name="iss_data.db")
        return "Database not found", 404
    except Exception as e:
        return str(e), 500

@app.route("/api/days-with-data")
def api_days_with_data():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute("""
            SELECT 
                DATE(ts_utc) as day,
                COUNT(*) as record_count,
                MIN(ts_utc) as first_record,
                MAX(ts_utc) as last_record
            FROM records
            GROUP BY DATE(ts_utc)
            ORDER BY day ASC
        """)
        
        rows = c.fetchall()
        conn.close()
        
        days = []
        for row in rows:
            days.append({
                "day": row[0],
                "record_count": row[1],
                "first_record": row[2],
                "last_record": row[3]
            })
        
        return jsonify({"days": days})
        
    except Exception as e:
        print(f"✗ Error in /api/days-with-data: {e}")
        return jsonify({"days": []}), 200

@app.route("/api/all-records")
def api_all_records():
    try:
        day = request.args.get('day', None)
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))
        offset = (page - 1) * per_page
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        if day:
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
        
        records = []
        for row in rows:
            records.append({
                "id": row[0],
                "ts_utc": row[1],
                "latitude": row[2],
                "longitude": row[3],
                "altitude": row[4],
                "velocity": row[5],
                "day": row[6]
            })
        
        total_pages = (total + per_page - 1) // per_page if total > 0 else 0
        
        return jsonify({
            "records": records,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages
        })
        
    except Exception as e:
        print(f"✗ Error in /api/all-records: {e}")
        return jsonify({"records": [], "total": 0}), 200

@app.route("/api/download-csv")
def api_download_csv():
    try:
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
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Timestamp (UTC)', 'Latitude', 'Longitude', 'Altitude (km)', 'Velocity (km/h)'])
        
        for row in rows:
            writer.writerow(row)
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        response.headers["Content-Type"] = "text/csv"
        
        return response
        
    except Exception as e:
        print(f"✗ Error in /api/download-csv: {e}")
        return str(e), 500

# --- Start Server ---
if __name__ == "__main__":
    print("🚀 Starting ISS Tracker Server...")
    
    # Initialize database
    init_db()
    
    # Start background thread
    fetch_thread = threading.Thread(target=fetch_loop, daemon=True)
    fetch_thread.start()
    
    print("="*50)
    print("✓ Server running on http://0.0.0.0:5000")
    print("✓ Press Ctrl+C to stop")
    print("="*50)
    
    # Run Flask (use debug=False for production)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
