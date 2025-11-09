from flask import Flask, send_from_directory, jsonify, request

app = Flask(__name__)

# --- Serve HTML pages ---
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/database')
def database():
    return send_from_directory('.', 'database.html')

# --- API endpoints for JS ---

@app.route('/api/days-with-data')
def days_with_data():
    # Example static data
    return jsonify(days=[
        {'day':'2025-11-01','record_count':5,'first_record':'2025-11-01 00:00:00','last_record':'2025-11-01 23:50:00'},
        {'day':'2025-11-02','record_count':3,'first_record':'2025-11-02 00:10:00','last_record':'2025-11-02 23:40:00'},
        {'day':'2025-11-03','record_count':4,'first_record':'2025-11-03 01:00:00','last_record':'2025-11-03 22:50:00'}
    ])

@app.route('/api/all-records')
def all_records():
    day = request.args.get('day', '2025-11-01')
    # Example data
    records = [
        {'ts_utc': f'{day} 00:00:00', 'latitude': 0.0, 'longitude': 0.0, 'altitude': 400},
        {'ts_utc': f'{day} 06:00:00', 'latitude': 10.1234, 'longitude': 20.5678, 'altitude': 401},
        {'ts_utc': f'{day} 12:00:00', 'latitude': -5.9876, 'longitude': 45.1234, 'altitude': 399.5}
    ]
    return jsonify(records=records, total=len(records))

@app.route('/api/download-csv')
def download_csv():
    day = request.args.get('day', 'all')
    csv_data = "time,latitude,longitude,altitude\n"
    if day == 'all':
        days = ['2025-11-01','2025-11-02','2025-11-03']
        for d in days:
            csv_data += f"{d} 00:00:00,0,0,400\n"
    else:
        csv_data += f"{day} 00:00:00,0,0,400\n"
    return csv_data, 200, {'Content-Type': 'text/csv'}

if __name__ == '__main__':
    app.run(debug=True)
