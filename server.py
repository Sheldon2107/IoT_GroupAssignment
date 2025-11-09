from flask import Flask, jsonify, request, send_file
import sqlite3
import os

app = Flask(__name__)

DB_FILE = 'iss_data.db'

def get_db_connection():
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError(f"{DB_FILE} not found")
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/api/last3days')
def last_3_days():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT ts_utc, latitude, longitude, altitude
            FROM iss_telemetry
            ORDER BY ts_utc DESC
            LIMIT 3*24*60  -- approx last 3 days if 1-min interval
        """)
        rows = cur.fetchall()
        conn.close()
        # Convert to list of dicts
        data = [dict(row) for row in rows]
        return jsonify(data)
    except Exception as e:
        print("Error in /api/last3days:", e)
        return jsonify([]), 500

@app.route('/api/days-with-data')
def days_with_data():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT date(ts_utc) as day, COUNT(*) as record_count,
                   MIN(ts_utc) as first_record, MAX(ts_utc) as last_record
            FROM iss_telemetry
            GROUP BY day
            ORDER BY day
        """)
        rows = cur.fetchall()
        conn.close()
        days = [dict(row) for row in rows]
        return jsonify({"days": days})
    except Exception as e:
        print("Error in /api/days-with-data:", e)
        return jsonify({"days": []}), 500

@app.route('/api/all-records')
def all_records():
    day = request.args.get('day')
    per_page = int(request.args.get('per_page', 100))
    page = int(request.args.get('page', 1))
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = "SELECT ts_utc, latitude, longitude, altitude FROM iss_telemetry"
        params = []
        if day != 'all' and day is not None:
            query += " WHERE date(ts_utc) = ?"
            params.append(day)
        query += " ORDER BY ts_utc ASC LIMIT ? OFFSET ?"
        params.extend([per_page, (page-1)*per_page])
        cur.execute(query, params)
        rows = cur.fetchall()

        # Total count
        if day != 'all' and day is not None:
            cur.execute("SELECT COUNT(*) as total FROM iss_telemetry WHERE date(ts_utc)=?", (day,))
        else:
            cur.execute("SELECT COUNT(*) as total FROM iss_telemetry")
        total = cur.fetchone()['total']
        conn.close()
        return jsonify({
            "records": [dict(r) for r in rows],
            "total": total
        })
    except Exception as e:
        print("Error in /api/all-records:", e)
        return jsonify({"records": [], "total": 0}), 500

@app.route('/api/download-csv')
def download_csv():
    day = request.args.get('day', 'all')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if day == 'all':
            cur.execute("SELECT ts_utc, latitude, longitude, altitude FROM iss_telemetry ORDER BY ts_utc ASC")
        else:
            cur.execute("SELECT ts_utc, latitude, longitude, altitude FROM iss_telemetry WHERE date(ts_utc)=? ORDER BY ts_utc ASC", (day,))
        rows = cur.fetchall()
        conn.close()

        # Write CSV to temp file
        import csv
        from io import StringIO
        si = StringIO()
        writer = csv.writer(si)
        writer.writerow(['ts_utc','latitude','longitude','altitude'])
        for row in rows:
            writer.writerow([row['ts_utc'], row['latitude'], row['longitude'], row['altitude']])
        si.seek(0)
        return send_file(
            path_or_file=StringIO(si.getvalue()),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'ISS_data_{day}.csv'
        )
    except Exception as e:
        print("Error in /api/download-csv:", e)
        return "Error generating CSV", 500

if __name__ == '__main__':
    app.run(debug=True)
