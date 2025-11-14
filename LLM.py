from flask import Flask, request, jsonify
import openai
import requests
from skyfield.api import load, wgs84
from skyfield.data import tle

app = Flask(__name__)
openai.api_key = "YOUR_KEY"  # Use free tier or Llama via HuggingFace

@app.route('/', methods=['POST'])
def llm():
    prompt = request.data.decode()
    # LLM: extract satellite name
    res = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Extract satellite name from: {prompt}"}]
    )
    sat_name = res.choices[0].message.content.strip()

    # Fetch TLE
    url = f"https://celestrak.org/NORAD/elements/gp.php?NAME={sat_name}&FORMAT=tle"
    tle_lines = requests.get(url).text.splitlines()
    if len(tle_lines) < 3:
        return jsonify({"error": "Not found"})

    # Propagate orbit
    ts = load.timescale()
    satellite = tle.TwoLineElement(tle_lines[1], tle_lines[2], sat_name)
    t = ts.now()
    geocentric = satellite.at(t)
    pos = geocentric.position.km

    # 5G latency estimate (simplified)
    distance = (pos[0]**2 + pos[1]**2 + pos[2]**2)**0.5
    latency = distance / 300  # light speed approx

    return jsonify({
        "x": pos[0]/100, "y": pos[1]/100, "z": pos[2]/100,
        "latency": round(latency, 1),
        "name": sat_name
    })

if __name__ == "__main__":
    app.run(port=5000)