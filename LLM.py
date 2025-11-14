from flask import Flask, request, jsonify
import openai
import requests
from skyfield.api import load
from skyfield.data import tle

app = Flask(__name__)
openai.api_key = "YOUR_KEY"

@app.route('/', methods=['POST'])
def llm():
    prompt = request.data.decode()

    # Extract satellite name using LLM
    res = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": f"Extract satellite name only (no extra text): {prompt}"}
        ]
    )
    sat_query = res.choices[0].message.content.strip()

    # Step 1: SEARCH Celestrak for satellite
    search_url = f"https://celestrak.org/NORAD/search.php?NAME={sat_query}&FORMAT=json"
    results = requests.get(search_url).json()

    if not results:
        return jsonify({"error": "Satellite not found"})

    # Take the first result (best match)
    sat = results[0]
    sat_id = sat["NORAD_CAT_ID"]
    sat_name = sat["OBJECT_NAME"]

    # Step 2: Fetch TLE by CATNR
    tle_url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={sat_id}&FORMAT=tle"
    tle_text = requests.get(tle_url).text.splitlines()

    # Extract TLE lines
    line1 = tle_text[1]
    line2 = tle_text[2]

    # Step 3: Propagate orbit
    ts = load.timescale()
    satellite = tle.TwoLineElement(line1, line2, sat_name)
    t = ts.now()
    geocentric = satellite.at(t)
    pos = geocentric.position.km

    # Step 4: Latency estimate
    distance = (pos[0]**2 + pos[1]**2 + pos[2]**2) ** 0.5
    latency = distance / 300

    return jsonify({
        "x": pos[0] / 50000,
        "y": pos[1] / 50000,
        "z": pos[2] / 50000,
        "latency": round(latency, 1),
        "name": sat_name
    })

if __name__ == "__main__":
    app.run(port=5000)
git add .
git commit -m "fix CORS + sat.glb + error handling"
git push