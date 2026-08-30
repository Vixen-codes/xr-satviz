from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from skyfield.api import load, EarthSatellite, wgs84
from skyfield.framelib import itrs
import math
import os
import time
import re

app = Flask(__name__)
CORS(app)

# ============================================================
# CONFIGURATION
# ============================================================

EARTH_RADIUS_KM = 6371.0

# IMPORTANT: this must match the radius of the <a-sphere id="earth"> in the
# frontend (currently radius="3"). If you resize the Earth sphere in the
# HTML, update this constant to match, or satellites will render floating
# outside (or buried inside) the globe.
SCENE_EARTH_RADIUS = 3.0
SCALE = SCENE_EARTH_RADIUS / EARTH_RADIUS_KM

# How far above the surface (in scene units, as a multiplier) to draw the
# footprint polygon so it doesn't z-fight with the Earth sphere itself.
FOOTPRINT_LIFT = 1.01

TLE_CACHE_TTL_SECONDS = 2 * 60 * 60

CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"

_session = requests.Session()
_session.headers.update({
    "User-Agent": "XR-SatViz/1.0 satellite-visualisation-project"
})

_tle_cache = {}

TS = load.timescale()


# ============================================================
# CITY DATA
# ============================================================

CITIES = {
    "London": (51.5074, -0.1278),
    "New York": (40.7128, -74.0060),
    "Tokyo": (35.6762, 139.6503),
    "Paris": (48.8566, 2.3522),
    "Beijing": (39.9042, 116.4074),
    "Sydney": (-33.8688, 151.2093),
    "Mumbai": (19.0760, 72.8777),
    "Los Angeles": (34.0522, -118.2437),
    "Dubai": (25.2048, 55.2708),
    "Singapore": (1.3521, 103.8198),
}


# ============================================================
# COMMON SATELLITE SHORTCUTS
# ============================================================

SATELLITE_ALIASES = {
    "iss": "25544",
    "hubble": "20580",
    "hst": "20580",
    "tiangong": "48274",
    "css": "48274",
    "goes 16": "41866",
    "goes-16": "41866",
    "goes16": "41866",
    "landsat 8": "39084",
    "landsat-8": "39084",
    "aqua": "27424",
    "terra": "25994",
    "noaa 18": "28654",
    "noaa-18": "28654",
}


# ============================================================
# HELPERS
# ============================================================

def clean_query(prompt):
    """
    Turn user input into either:
      - CATNR=12345
      - NAME=STARLINK...
    """

    prompt = (prompt or "").strip()

    if not prompt:
        return {
            "type": "catnr",
            "value": "25544"
        }

    lower = prompt.lower()

    # Remove common natural-language prefixes.
    prefixes = [
        "track ",
        "find ",
        "show ",
        "locate ",
        "where is ",
        "look up ",
        "lookup ",
        "search for ",
    ]

    for prefix in prefixes:
        if lower.startswith(prefix):
            prompt = prompt[len(prefix):].strip()
            lower = prompt.lower()
            break

    # Known aliases
    if lower in SATELLITE_ALIASES:
        return {
            "type": "catnr",
            "value": SATELLITE_ALIASES[lower]
        }

    # Pure NORAD/catalog number.
    if re.fullmatch(r"\d{1,9}", prompt):
        return {
            "type": "catnr",
            "value": prompt
        }

    # Otherwise search by name.
    return {
        "type": "name",
        "value": prompt
    }


def make_celestrak_url(query_type, value, fmt="JSON"):
    if query_type == "catnr":
        return (
            f"{CELESTRAK_BASE}"
            f"?CATNR={value}"
            f"&FORMAT={fmt}"
        )

    return (
        f"{CELESTRAK_BASE}"
        f"?NAME={requests.utils.quote(value)}"
        f"&FORMAT={fmt}"
    )


def fetch_celestrak_json(query_type, value):
    """
    Fetch current GP/OMM data from CelesTrak.

    Returns:
        (data, url)

    Raises:
        RuntimeError with a useful diagnostic message.
    """

    url = make_celestrak_url(query_type, value, "JSON")

    last_exc = None
    response = None

    # One retry with a short backoff — CelesTrak occasionally responds
    # slowly under load, and a single retry smooths over that without
    # masking a genuine connectivity problem (which will fail both times).
    for attempt in range(2):
        try:
            response = _session.get(
                url,
                timeout=(8, 25)
            )
            last_exc = None
            break

        except requests.exceptions.Timeout as exc:
            last_exc = RuntimeError(
                "CelesTrak request timed out. This usually means either "
                "CelesTrak is slow/unreachable right now, or something on "
                "your network (firewall, VPN, proxy) is blocking the "
                "request. Try opening the CelesTrak URL directly in a "
                "browser to check."
            )

        except requests.exceptions.ConnectionError as exc:
            last_exc = RuntimeError(
                f"Could not connect to CelesTrak: {exc}"
            )

        except requests.exceptions.RequestException as exc:
            last_exc = RuntimeError(
                f"CelesTrak request failed: {exc}"
            )

        if attempt == 0:
            time.sleep(1.5)

    if last_exc is not None:
        raise last_exc

    if response.status_code == 404:
        raise RuntimeError(
            f"No current orbital data was found for '{value}'. "
            f"CelesTrak returned HTTP 404."
        )

    if response.status_code == 403:
        raise RuntimeError(
            "CelesTrak rejected the request with HTTP 403. "
            "This can happen if too many requests were made recently."
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"CelesTrak returned HTTP {response.status_code}."
        )

    text = response.text.strip()

    if not text:
        raise RuntimeError(
            "CelesTrak returned an empty response."
        )

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            "CelesTrak responded, but the response was not valid JSON."
        )

    if not isinstance(data, list):
        data = [data]

    if len(data) == 0:
        raise RuntimeError(
            f"No orbital data found for '{value}'."
        )

    return data, url


def select_satellite(data, query):
    """
    If NAME search returns several objects, select the best match.
    """

    if len(data) == 1:
        return data[0]

    query_upper = query.upper().strip()

    # Exact object-name match first.
    for item in data:
        name = str(item.get("OBJECT_NAME", "")).upper().strip()

        if name == query_upper:
            return item

    # Then starts-with.
    for item in data:
        name = str(item.get("OBJECT_NAME", "")).upper().strip()

        if name.startswith(query_upper):
            return item

    # Otherwise first result.
    return data[0]


def satellite_from_omm(fields):
    """
    Convert CelesTrak OMM JSON into a Skyfield EarthSatellite.
    """

    try:
        return EarthSatellite.from_omm(TS, fields)

    except Exception as exc:
        raise RuntimeError(
            f"Skyfield could not parse the orbital data: {exc}"
        )


def get_satellite_data(prompt):
    """
    Main satellite lookup function with caching.
    """

    query = clean_query(prompt)

    cache_key = f"{query['type']}:{query['value'].upper()}"

    cached = _tle_cache.get(cache_key)

    if cached:
        age = time.time() - cached["time"]

        if age < TLE_CACHE_TTL_SECONDS:
            return (
                cached["fields"],
                cached["satellite"],
                cached["url"]
            )

    fields_list, url = fetch_celestrak_json(
        query["type"],
        query["value"]
    )

    fields = select_satellite(
        fields_list,
        query["value"]
    )

    satellite = satellite_from_omm(fields)

    _tle_cache[cache_key] = {
        "time": time.time(),
        "fields": fields,
        "satellite": satellite,
        "url": url,
    }

    return fields, satellite, url


def safe_float(value):
    """Best-effort float conversion for values pulled out of OMM JSON."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# ============================================================
# COORDINATE CONVERSION
#
# Everything that gets DRAWN in the scene (satellite marker, trajectory,
# footprint) is built from geodetic-style lat/lon/altitude using the exact
# same formula the frontend already uses for its city markers:
#
#   x =  R * cos(lat) * cos(lon)
#   y =  R * sin(lat)                <- Y is "up" (the polar axis)
#   z = -R * cos(lat) * sin(lon)
#
# This keeps everything in one consistent, A-Frame-friendly (Y-up)
# convention. Raw Skyfield ITRS x/y/z (Z-up) is still used separately for
# the physics-only distance/light-time calculation below, since a vector's
# magnitude doesn't care which axis convention you use.
# ============================================================

def geo_to_scene(lat_deg, lon_deg, alt_km):
    radius_km = EARTH_RADIUS_KM + alt_km

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    x = radius_km * math.cos(lat) * math.cos(lon)
    y = radius_km * math.sin(lat)
    z = -radius_km * math.cos(lat) * math.sin(lon)

    return {
        "x": float(x * SCALE),
        "y": float(y * SCALE),
        "z": float(z * SCALE),
    }


def earth_fixed_km(geocentric):
    """
    Raw Earth-fixed (ITRS) position in km. Used ONLY for scalar distance /
    light-time physics, not for anything that gets rendered.
    """

    return geocentric.frame_xyz(itrs).km


# ============================================================
# ORBIT CALCULATIONS
# ============================================================

def calculate_orbit_period(satellite):
    """
    Calculate orbital period from mean motion.
    """

    try:
        mean_motion_rad_min = satellite.model.no_kozai

        if mean_motion_rad_min <= 0:
            return None

        period_minutes = (
            2 * math.pi / mean_motion_rad_min
        )

        return period_minutes

    except Exception:
        return None


def choose_trajectory_duration(satellite):
    """
    Always plot exactly one full orbital period. Combined with the
    "frozen frame" trick in calculate_trajectory(), this makes the plotted
    ground track close back on itself into a clean loop instead of an
    arbitrary open arc.
    """

    period = calculate_orbit_period(satellite)

    if period is None:
        return 90.0

    # Sanity bounds for degenerate/garbage orbital elements, so a bad TLE
    # can't ask us to generate a multi-day (or negative-length) trajectory.
    return max(10.0, min(1500.0, period))


def calculate_trajectory(satellite, duration_minutes=None, step_seconds=20):
    """
    Generate a trajectory that traces the satellite's actual orbital path
    as a closed loop around the (static) Earth model.

    Why "frozen frame": the frontend's Earth mesh never rotates in real
    time, so plotting the satellite using true Earth-fixed ground-track
    coordinates (which continuously factor in Earth's real rotation) would
    make the path drift westward orbit over orbit relative to the static
    globe — an open spiral that never closes and looks like it's
    disappearing/reappearing when the animation loops back to the start.

    Instead, we snapshot the GCRS -> Earth-fixed rotation ONCE at a single
    reference instant and reuse that same fixed rotation for every sampled
    point. This is equivalent to simulating "Earth stops rotating the
    instant we start tracking" — which matches a globe that, in this
    scene, never rotates either. The satellite's true orbital motion
    (ignoring small perturbation-driven drift) is periodic, so the
    resulting path is periodic too: it closes into a loop after exactly
    one orbital period.

    Returns (trajectory, duration_minutes).
    """

    if duration_minutes is None:
        duration_minutes = choose_trajectory_duration(satellite)

    trajectory = []

    t0 = TS.now()

    # Single fixed rotation snapshot, reused for every sample below.
    R0 = itrs.rotation_at(t0)

    steps = int(duration_minutes * 60 / step_seconds)

    # Avoid generating enormous responses.
    steps = min(steps, 5000)

    for i in range(steps):

        t = TS.tt_jd(
            t0.tt +
            (i * step_seconds) / 86400.0
        )

        geocentric = satellite.at(t)

        r_gcrs = geocentric.position.km
        rx, ry, rz = R0.dot(r_gcrs)

        r = math.sqrt(rx * rx + ry * ry + rz * rz)

        lat_deg = math.degrees(math.asin(rz / r))
        lon_deg = math.degrees(math.atan2(ry, rx))
        alt_km = r - EARTH_RADIUS_KM

        point = geo_to_scene(lat_deg, lon_deg, alt_km)

        point["lat"] = lat_deg
        point["lon"] = lon_deg
        point["alt"] = alt_km

        trajectory.append(point)

    # The step count is rounded down to fit whole steps into one period,
    # so the last sampled point normally falls just short of a full lap.
    # Snap it closed explicitly rather than leaving a small visible gap
    # (or relying on curve interpolation to paper over it).
    if len(trajectory) > 2:
        trajectory.append(dict(trajectory[0]))

    return trajectory, duration_minutes


# ============================================================
# CITY VISIBILITY
# ============================================================

def calculate_city_passes(satellite, cities):
    """
    Determine which tracked cities currently have the
    satellite above their horizon.
    """

    t = TS.now()

    passes = []

    for city_name, (lat, lon) in cities.items():

        observer = wgs84.latlon(lat, lon)

        topocentric = (satellite - observer).at(t)

        alt, az, distance = topocentric.altaz()

        if alt.degrees > 0:

            passes.append({
                "city": city_name,
                "elevation_deg": round(alt.degrees, 1),
                "azimuth_deg": round(az.degrees, 1),
                "distance_km": round(distance.km, 1),
                "lat": lat,
                "lon": lon,
            })

    passes.sort(key=lambda p: p["elevation_deg"], reverse=True)

    return passes


# ============================================================
# SATELLITE METADATA
# ============================================================

def get_metadata(fields, satellite):

    altitude = None
    velocity = None

    try:
        now = TS.now()

        geocentric = satellite.at(now)

        altitude = wgs84.subpoint(geocentric).elevation.km

        velocity = math.sqrt(
            sum(v ** 2 for v in geocentric.velocity.km_per_s)
        )

    except Exception:
        pass

    period = calculate_orbit_period(satellite)

    return {
        "noradId": fields.get("NORAD_CAT_ID"),
        "internationalDesignator": fields.get("OBJECT_ID"),
        "objectName": fields.get("OBJECT_NAME"),
        "classification": fields.get("CLASSIFICATION_TYPE"),
        "epoch": fields.get("EPOCH"),
        "inclination": fields.get("INCLINATION"),
        "eccentricity": fields.get("ECCENTRICITY"),
        "raan": fields.get("RA_OF_ASC_NODE"),
        "argOfPericenter": fields.get("ARG_OF_PERICENTER"),
        "meanAnomaly": fields.get("MEAN_ANOMALY"),
        "meanMotion": fields.get("MEAN_MOTION"),
        "bstar": fields.get("BSTAR"),
        "altitude": round(altitude, 2) if altitude is not None else None,
        "velocity": round(velocity, 3) if velocity is not None else None,
        "periodMinutes": round(period, 2) if period is not None else None,
    }


# ============================================================
# COVERAGE / FOOTPRINT
# ============================================================

def calculate_footprint(latitude_deg, longitude_deg, altitude_km, n=64):
    """
    Geometric horizon footprint, returned both as a scalar radius (for
    display) and as a polygon of scene-space points the frontend can draw
    directly as a line loop on the globe.

    NOTE: this is the geometric line-of-sight horizon, not a sensor swath.
    """

    if altitude_km is None or altitude_km <= 0:
        return {
            "points": [],
            "radiusKm": 0,
            "angularRadiusDeg": 0,
        }

    horizon_angle = math.acos(
        EARTH_RADIUS_KM / (EARTH_RADIUS_KM + altitude_km)
    )

    surface_radius_km = EARTH_RADIUS_KM * horizon_angle

    lat0 = math.radians(latitude_deg)
    lon0 = math.radians(longitude_deg)

    points = []

    for i in range(n):
        bearing = 2 * math.pi * i / n

        lat = math.asin(
            math.sin(lat0) * math.cos(horizon_angle) +
            math.cos(lat0) * math.sin(horizon_angle) * math.cos(bearing)
        )

        lon = lon0 + math.atan2(
            math.sin(bearing) * math.sin(horizon_angle) * math.cos(lat0),
            math.cos(horizon_angle) - math.sin(lat0) * math.sin(lat)
        )

        p = geo_to_scene(math.degrees(lat), math.degrees(lon), 0.0)

        points.append({
            "x": p["x"] * FOOTPRINT_LIFT,
            "y": p["y"] * FOOTPRINT_LIFT,
            "z": p["z"] * FOOTPRINT_LIFT,
        })

    return {
        "points": points,
        "centerLat": latitude_deg,
        "centerLon": longitude_deg,
        "radiusKm": round(surface_radius_km, 1),
        "angularRadiusDeg": round(math.degrees(horizon_angle), 2),
    }


# ============================================================
# ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "status": "ok",
        "message": "XR-SatViz API",
        "version": "3.2",
        "dataSource": "CelesTrak GP / OMM",
        "endpoints": [
            "/",
            "/health",
            "/test-celestrak",
        ]
    })


@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "status": "ok",
        "service": "XR-SatViz"
    })


@app.route("/test-celestrak", methods=["GET"])
def test_celestrak():

    try:

        data, url = fetch_celestrak_json("catnr", "25544")

        return jsonify({
            "success": True,
            "message": "CelesTrak connection is working.",
            "url": url,
            "objectsReturned": len(data),
            "object": data[0]
        })

    except Exception as exc:

        return jsonify({
            "success": False,
            "message": str(exc)
        }), 502


@app.route("/", methods=["POST"])
def get_satellite():

    try:

        prompt = request.data.decode("utf-8").strip()

        if not prompt:
            prompt = "ISS"

        fields, satellite, source_url = get_satellite_data(prompt)

        now = TS.now()

        geocentric = satellite.at(now)

        subpoint = wgs84.subpoint(geocentric)

        altitude = subpoint.elevation.km

        # Rendered scene position: lat/lon/alt based, matches city markers.
        scene_position = geo_to_scene(
            subpoint.latitude.degrees,
            subpoint.longitude.degrees,
            altitude
        )

        # Physics-only: raw ITRS vector, just used for its magnitude.
        raw_xyz_km = earth_fixed_km(geocentric)

        velocity = math.sqrt(
            sum(v ** 2 for v in geocentric.velocity.km_per_s)
        )

        distance_from_center = math.sqrt(sum(c ** 2 for c in raw_xyz_km))

        latency_ms = (distance_from_center / 299792.458) * 1000

        trajectory, trajectory_duration_minutes = calculate_trajectory(satellite)

        city_passes = calculate_city_passes(satellite, CITIES)

        metadata = get_metadata(fields, satellite)

        footprint = calculate_footprint(
            subpoint.latitude.degrees,
            subpoint.longitude.degrees,
            altitude
        )

        period = metadata["periodMinutes"]

        return jsonify({

            "success": True,

            "name": fields.get("OBJECT_NAME", "Unknown satellite"),
            "norad": fields.get("NORAD_CAT_ID"),

            "source": source_url,

            "position": scene_position,

            "groundTrack": {
                "lat": subpoint.latitude.degrees,
                "lon": subpoint.longitude.degrees,
                "alt": round(altitude, 1),
            },

            "stats": {
                "altitude": round(altitude, 1),
                "velocity": round(velocity, 3),
                "latency": round(latency_ms, 2),
                "lightTimeMs": round(latency_ms, 2),
                "distance": round(distance_from_center, 1),
                "periodMinutes": period,
                "inclinationDeg": safe_float(fields.get("INCLINATION")),
                "eccentricity": safe_float(fields.get("ECCENTRICITY")),
            },

            "metadata": metadata,

            "footprint": footprint,

            "trajectory": trajectory,
            "trajectoryDurationMinutes": round(trajectory_duration_minutes, 1),
            "trajectoryClosed": True,

            "cityPasses": city_passes,

            "cities": [
                {"name": name, "lat": coords[0], "lon": coords[1]}
                for name, coords in CITIES.items()
            ]

        })

    except Exception as exc:

        print("\n========== XR-SATVIZ ERROR ==========")
        print(repr(exc))
        print("======================================\n")

        return jsonify({
            "success": False,
            "error": type(exc).__name__,
            "message": str(exc),
            "hint": (
                "Try /test-celestrak in your browser "
                "to test the CelesTrak connection."
            )
        }), 500


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    print("\n=====================================")
    print("       XR-SATVIZ BACKEND")
    print("=====================================")
    print(f"Running on http://localhost:{port}")
    print(f"CelesTrak: {CELESTRAK_BASE}")
    print(f"Test: http://localhost:{port}/test-celestrak")
    print("=====================================\n")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )