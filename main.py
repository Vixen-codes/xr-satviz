from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from skyfield.api import load, EarthSatellite, wgs84
from datetime import datetime, timedelta
import math

app = Flask(__name__)
CORS(app)

# Predefined satellites - NO API KEY NEEDED!
SATELLITES = {
    'iss': 'ISS (ZARYA)',
    'hubble': 'HST',
    'starlink': 'STARLINK-1007',
    'noaa': 'NOAA 18',
    'tiangong': 'CSS (TIANHE)',
    'gps': 'GPS BIIA-10',
    'aqua': 'AQUA',
    'terra': 'TERRA',
    'landsat': 'LANDSAT 8',
    'goes': 'GOES 16'
}

# Major cities for ground track
CITIES = {
    'London': (51.5074, -0.1278),
    'New York': (40.7128, -74.0060),
    'Tokyo': (35.6762, 139.6503),
    'Paris': (48.8566, 2.3522),
    'Beijing': (39.9042, 116.4074),
    'Sydney': (-33.8688, 151.2093),
    'Mumbai': (19.0760, 72.8777),
    'Los Angeles': (34.0522, -118.2437),
    'Dubai': (25.2048, 55.2708),
    'Singapore': (1.3521, 103.8198)
}

def find_satellite(prompt):
    """Extract satellite name from prompt"""
    prompt_lower = prompt.lower()
    for keyword, sat_name in SATELLITES.items():
        if keyword in prompt_lower:
            return sat_name
    # Default to ISS if nothing found
    return 'ISS (ZARYA)'

def fetch_tle(sat_name):
    """Fetch TLE data from Celestrak"""
    url = f"https://celestrak.org/NORAD/elements/gp.php?NAME={sat_name}&FORMAT=tle"
    response = requests.get(url, timeout=10)
    lines = response.text.strip().splitlines()
    
    if len(lines) < 3:
        raise ValueError(f"Satellite '{sat_name}' not found")
    
    return lines[0].strip(), lines[1].strip(), lines[2].strip()

def calculate_trajectory(satellite, ts, duration_minutes=90):
    """Calculate satellite trajectory over time"""
    trajectory = []
    now = ts.now()
    
    for i in range(0, duration_minutes * 6):  # 6 points per minute
        t = ts.tt_jd(now.tt + (i * 10) / 86400.0)  # 10 second intervals
        geocentric = satellite.at(t)
        pos = geocentric.position.km
        
        # Get ground position
        subpoint = wgs84.subpoint(geocentric)
        
        trajectory.append({
            'x': pos[0] / 1000,
            'y': pos[1] / 1000,
            'z': pos[2] / 1000,
            'lat': subpoint.latitude.degrees,
            'lon': subpoint.longitude.degrees,
            'alt': subpoint.elevation.km
        })
    
    return trajectory

def calculate_city_passes(satellite, ts, cities):
    """Calculate when satellite passes over cities"""
    passes = []
    now = ts.now()
    
    for city_name, (lat, lon) in cities.items():
        city_location = wgs84.latlon(lat, lon)
        
        # Check current position
        geocentric = satellite.at(now)
        subpoint = wgs84.subpoint(geocentric)
        
        # Calculate distance from city
        distance = math.sqrt(
            (subpoint.latitude.degrees - lat)**2 + 
            (subpoint.longitude.degrees - lon)**2
        )
        
        # If within ~10 degrees, it's "near"
        if distance < 10:
            passes.append({
                'city': city_name,
                'distance': round(distance * 111, 1),  # Convert to km
                'lat': lat,
                'lon': lon
            })
    
    return passes

@app.route('/', methods=['POST'])
def get_satellite():
    try:
        prompt = request.data.decode()
        print(f"Received prompt: {prompt}")
        
        # Extract satellite name
        sat_name = find_satellite(prompt)
        print(f"Looking for satellite: {sat_name}")
        
        # Fetch TLE
        name, line1, line2 = fetch_tle(sat_name)
        
        # Create satellite object
        ts = load.timescale()
        satellite = EarthSatellite(line1, line2, name, ts)
        
        # Get current position
        t = ts.now()
        geocentric = satellite.at(t)
        pos = geocentric.position.km
        
        # Get ground track position
        subpoint = wgs84.subpoint(geocentric)
        
        # Calculate distance and latency
        distance = math.sqrt(pos[0]**2 + pos[1]**2 + pos[2]**2)
        altitude = subpoint.elevation.km
        latency_ms = (distance / 299792.458) * 1000
        
        # Calculate velocity
        velocity_geocentric = geocentric.velocity.km_per_s
        velocity = math.sqrt(sum(v**2 for v in velocity_geocentric))
        
        # Get trajectory for animation
        trajectory = calculate_trajectory(satellite, ts, duration_minutes=90)
        
        # Check city passes
        city_passes = calculate_city_passes(satellite, ts, CITIES)
        
        return jsonify({
            'success': True,
            'name': name,
            'position': {
                'x': pos[0] / 1000,
                'y': pos[1] / 1000,
                'z': pos[2] / 1000
            },
            'groundTrack': {
                'lat': subpoint.latitude.degrees,
                'lon': subpoint.longitude.degrees,
                'alt': altitude
            },
            'stats': {
                'altitude': round(altitude, 1),
                'velocity': round(velocity, 2),
                'latency': round(latency_ms, 1),
                'distance': round(distance, 1)
            },
            'trajectory': trajectory,
            'cityPasses': city_passes,
            'cities': [{'name': k, 'lat': v[0], 'lon': v[1]} for k, v in CITIES.items()]
        })
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Try: ISS, Starlink, Hubble, NOAA, Tiangong'
        }), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'satellites': list(SATELLITES.keys())})

if __name__ == '__main__':
    print("🛰️  XR-SatViz Server Starting...")
    print("📡 Available satellites:", ', '.join(SATELLITES.keys()))
    print("🌍 Server running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)