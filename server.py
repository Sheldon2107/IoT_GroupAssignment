from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

DB_FILE = 'iss_data.db'

# Ensure database exists
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS iss_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            day INTEGER NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            altitude REAL NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Helper to query DB
def query_db(query, args=(), one=False):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, args)
    rv = cur.fetchall()
    conn.close()
    return (rv[0] if rv else None) if one else rv

# Serve index
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# Serve database page
@app.route('/database')
def database():
    return send_from_directory('.', 'database.html')

# API: last 3 days
@app.route('/api/last3days')
def last3days():
    # Get last 3 days
    three_days_ago = datetime.utcnow() - timedelta(days=3)
    rows = query_db('SELECT * FROM iss_positions WHERE ts_utc >= ? ORDER BY ts_utc ASC', (three_days_ago.isoformat(),))
    data = [dict(row) for row in rows]
    return jsonify(data)

# API: all records with pagination
@app.route('/api/all-records')
def all_records():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 100))
    day = request.args.get('day', None)

    query = 'SELECT * FROM iss_positions'
    params = []
    if day:
        query += ' WHERE day=?'
        params.append(int(day))
    query += ' ORDER BY ts_utc ASC'

    rows = query_db(query, params)
    total_records = len(rows)
    total_pages = (total_records + per_page - 1) // per_page

    start = (page-1)*per_page
    end = start + per_page
    page_rows = rows[start:end]

    # Extract available days for filter
    all_days = sorted(set([r['day'] for r in rows]))

    return jsonify({
        'records': [dict(r) for r in page_rows],
        'total_pages': total_pages,
        'available_days': all_days
    })

# Optional: endpoint to add data (simulate ISS updates)
@app.route('/api/add', methods=['POST'])
def add_record():
    data = request.json
    ts = data.get('ts_utc', datetime.utcnow().isoformat())
    day = data.get('day', 1)
    lat = data['latitude']
    lon = data['longitude']
    alt = data['altitude']
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT INTO iss_positions (ts_utc, day, latitude, longitude, altitude) VALUES (?,?,?,?,?)',
              (ts, day, lat, lon, alt))
    conn.commit()
    conn.close()
    return jsonify({'status':'ok'})

# Serve static files like CSS/JS if needed
@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory('.', path)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
