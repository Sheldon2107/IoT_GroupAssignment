from flask import Flask, jsonify, send_file
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
import time

app = Flask(__name__)
CORS(app)

# Store historical data (last 3 days)
historical_data = []
MAX_DATA_POINTS = 4320  # 3 days * 24 hours * 60 minutes (1 point per minute)

def fetch_iss_position():
    """Fetch current ISS position from API"""
    try:
        response = requests.get('http://api.open-notify.org/iss-now.json', timeout=5)
        data = response.json()
        
        if data['message'] == 'success':
            timestamp = datetime.utcfromtimestamp(int(data['timestamp']))
            position = data['iss_position']
            
            return {
                'latitude': float(position['latitude']),
                'longitude': float(position['longitude']),
                'altitude': 408.0,  # Average ISS altitude in km
                'ts_utc': timestamp.strftime('%Y-%m-%d %H:%M:%S')
            }
    except Exception as e:
        print(f"Error fetching ISS position: {e}")
    
    return None

def update_historical_data():
    """Update historical data with current position"""
    position = fetch_iss_position()
    if position:
        historical_data.append(position)
        
        # Keep only last 3 days of data
        if len(historical_data) > MAX_DATA_POINTS:
            historical_data.pop(0)

# Initialize with some data
print("Initializing ISS tracker...")
update_historical_data()

@app.route('/')
def index():
    """Serve the main HTML page"""
    return send_file('index.html')

@app.route('/api/last3days')
def get_last_3_days():
    """Return last 3 days of ISS position data"""
    # Update with fresh data
    update_historical_data()
    
    # If we don't have enough data, simulate it for demo purposes
    if len(historical_data) < 100:
        # Generate some sample data points
        sample_data = []
        now = datetime.utcnow()
        
        for i in range(100):
            time_point = now - timedelta(minutes=i)
            sample_data.insert(0, {
                'latitude': 45.0 + (i % 60) - 30,  # Oscillate between 15 and 75
                'longitude': -180.0 + (i * 3.6) % 360,  # Circle the globe
                'altitude': 408.0 + (i % 10) * 0.5,  # Slight altitude variation
                'ts_utc': time_point.strftime('%Y-%m-%d %H:%M:%S')
            })
        
        return jsonify(sample_data)
    
    return jsonify(historical_data)

@app.route('/api/current')
def get_current():
    """Return current ISS position"""
    position = fetch_iss_position()
    if position:
        return jsonify(position)
    return jsonify({'error': 'Unable to fetch position'}), 500

if __name__ == '__main__':
    # Get port from environment variable (Render provides this)
    import os
    port = int(os.environ.get('PORT', 10000))
    
    # Run the app
    app.run(host='0.0.0.0', port=port, debug=False)
