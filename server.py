from flask import Flask, jsonify, send_from_directory, request, make_response
import requests, csv, os, threading, time
from datetime import datetime

app = Flask(__name__)

CSV_FILE = 'iss_data.csv'
WTIA_URL = 'https://api.wheretheiss.at/v1/satellites/25544'

# === Ensure CSV exists ===
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'latitude', 'longitude', 'altitude'])

# === Function to fetch ISS telemetry and append to CSV ===
def fetch_iss_data():
    while True:
        try:
            resp = requests.get(WTIA_URL, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                ts = datetime.utcfromtimestamp(data['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                lat = data['latitude']
                lon = data['longitude']
                alt = data['altitude']  # km
                with open(CSV_FILE, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([ts, lat, lon, alt])
        except Exception as e:
            print("ISS Fetch Error:", e)
        time.sleep(1)  # respect rate limit (~1 request/sec)

# Start background thread for data fetching
threading.Thread(target=fetch_iss_data, daemon=True).start()

# === Helper to group data by day ===
def get_days_with_data():
    days = {}
    if not os.path.exists(CSV_FILE):
        return []
    with open(CSV_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            day = row['timestamp'].split(' ')[0]
            if day not in days:
                days[day] = {"day": day, "records": [], "first_record": row['timestamp'], "last_record": row['timestamp']}
            days[day]["records"].append(row)
            days[day]["last_record"] = row['timestamp']
    result = []
    for d in sorted(days.keys()):
        result.append({
            "day": d,
            "record_count": len(days[d]["records"]),
            "first_record": days[d]["first_record"],
            "last_record": days[d]["last_record"]
        })
    return result

# === Routes to serve static pages ===
@app.route('/')
def index():
    return send_from_directory('', 'index.html')

@app.route('/database')
def database():
    return send_from_directory('', 'database.html')

# === API: list of days with data ===
@app.route('/api/days-with-data')
def api_days():
    days = get_days_with_data()
    return jsonify({"days": days})

# === API: records for a specific day ===
@app.route('/api/all-records')
def api_all_records():
    day = request.args.get('day')
    per_page = int(request.args.get('per_page', 100))
    page = int(request.args.get('page', 1))

    all_records = []
    with open(CSV_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if day == 'all' or row['timestamp'].startswith(day):
                all_records.append(row)
    total = len(all_records)
    start = (page - 1) * per_page
    end = start + per_page
    records = all_records[start:end]

    return jsonify({"records": records, "total": total})

# === API: download CSV ===
@app.route('/api/download-csv')
def download_csv():
    day = request.args.get('day')
    filtered_records = []

    with open(CSV_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if day == 'all' or row['timestamp'].startswith(day):
                filtered_records.append(row)

    csv_filename = f"ISS_data_{day}.csv" if day != 'all' else "ISS_data_all.csv"
    si = [["Time (UTC)", "Latitude", "Longitude", "Altitude (km)"]]
    for r in filtered_records:
        si.append([r['timestamp'], r['latitude'], r['longitude'], r['altitude']])

    csv_content = "\n".join([",".join(map(str,row)) for row in si])
    response = make_response(csv_content)
    response.headers["Content-Disposition"] = f"attachment; filename={csv_filename}"
    response.headers["Content-Type"] = "text/csv"
    return response

if __name__ == '__main__':
    app.run(debug=True)
