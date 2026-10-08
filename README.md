# XR-SatViz

XR-SatViz is a 3D satellite tracking and visualisation project I built to mess around with orbital data and see if I could turn it into something that actually feels like a satellite tracking console.

It uses live public orbital data from CelesTrak, Skyfield for the orbital calculations, Flask for the backend and A-Frame for the 3D visualisation.

you can search for satellites by name or NORAD catalog number and then see where the satellite is, what its orbit looks like, which cities currently have it above the horizon, and its approximate coverage area.

## what it does

* tracks satellites using their NORAD catalog number or name
* pulls current GP/OMM orbital data from CelesTrak
* converts the orbital data into positions that can be displayed on a 3D Earth
* shows the satellite moving around its orbital path
* draws the full orbital path as a closed loop
* shows the satellite's current ground track
* calculates altitude, velocity, orbital period, inclination and eccentricity
* calculates approximate light-time from the Earth's centre to the satellite
* shows which of a set of major cities currently have the satellite above the horizon
* shows a geometric line-of-sight coverage footprint around the satellite
* lets you turn the orbit, coverage and city layers on and off
* includes a few common satellite shortcuts like ISS, Hubble, GOES-16 and Tiangong
* has a small interactive 3D satellite model instead of just showing a dot
* works locally with a Flask server and can use the deployed Render backend

## the tech

### frontend

* HTML
* CSS
* JavaScript
* A-Frame
* Three.js through A-Frame

The frontend handles the actual 3D scene, camera controls, satellite animation, orbit rendering, coverage footprint and UI.

The Earth is represented as a 3D sphere and the satellite is positioned using latitude, longitude and altitude. The orbit is rendered using a closed Catmull-Rom curve and Three.js TubeGeometry.

### backend

* Python
* Flask
* Flask-CORS
* Skyfield
* Requests

The backend is responsible for getting the orbital data and doing the calculations before sending the results to the frontend.

CelesTrak provides the public GP/OMM orbital data and Skyfield turns that data into an EarthSatellite object that can be used for position and orbital calculations.

## how it works

The basic flow is:

```text
user searches for satellite
        |
        v
frontend sends search to Flask
        |
        v
Flask cleans the search
        |
        v
CelesTrak returns current GP/OMM data
        |
        v
Skyfield parses the orbital data
        |
        v
backend calculates position + orbit + visibility
        |
        v
JSON response sent back to frontend
        |
        v
A-Frame/Three.js renders everything in 3D
```

There is also a small cache on the backend so repeated searches do not constantly request the same orbital data from CelesTrak. The cache currently lasts for 2 hours.

## orbital visualisation

One of the things I had to deal with was the difference between the coordinate systems used for the orbital calculations and the coordinate system needed by the 3D scene.

The backend converts latitude, longitude and altitude into scene coordinates using:

```text
x = R * cos(lat) * cos(lon)
y = R * sin(lat)
z = -R * cos(lat) * sin(lon)
```

The 3D scene uses Y as the vertical axis, so the conversion keeps the satellite, cities and coverage calculations in the same coordinate system.

The orbit is generated for one complete orbital period. I also freeze the Earth rotation for the trajectory calculation so the orbit closes back onto itself instead of turning into an open spiral on the static Earth model.

## coverage

The coverage circle is based on the geometric horizon of the satellite.

This is important because it is **not a sensor swath** or a prediction of what a specific satellite sensor can see.

It is basically asking:

> how far around the Earth could this satellite theoretically see based on line of sight?

The footprint is recalculated as the satellite moves, so it follows the satellite instead of staying fixed at its original position.

## searching for satellites

You can enter either a NORAD catalog number or a satellite name.

For example:

```text
25544
ISS
Hubble
GOES 16
Landsat 8
Tiangong
```

There are also some built-in aliases in the backend.

Featured targets currently include:

* ISS
* Hubble
* NOAA 18
* GOES 16
* Landsat 8
* GPS
* Tiangong

## information shown

Once a satellite is tracked, the interface shows:

```text
NORAD
Altitude
Velocity
Period
Inclination
Eccentricity
Light-time
Ground track
Trajectory duration
```

It also shows cities where the satellite is currently above the horizon, including their elevation angle.

## running it locally

You need Python installed.

Install the Python dependencies:

```bash
pip install flask flask-cors requests skyfield
```

Then start the backend:

```bash
python main.py
```

The Flask server runs on:

```text
http://localhost:5000
```

For the frontend, open the HTML file using something like the VS Code Live Server extension.

When running locally, the frontend automatically uses:

```text
http://localhost:5000
```

When it is not running on localhost, it uses the deployed Render backend.

## API

The backend currently has a few simple endpoints.

### health

```text
GET /health
```

Used to check that the backend is running.

### test CelesTrak

```text
GET /test-celestrak
```

Tests whether the backend can successfully retrieve the ISS orbital data from CelesTrak.

### satellite lookup

```text
POST /
```

The request body contains the satellite name or NORAD catalog number.

For example:

```text
25544
```

The response contains the satellite position, orbital information, trajectory, ground track, city visibility and coverage information.

## current limitations

This is mainly a visualisation project, so there are a few things it does not try to do.

* the orbital data comes from public CelesTrak GP/OMM data
* the visualised orbit is based on the available orbital elements and is not a precision mission-grade prediction
* the Earth is static in the visualisation
* the coverage calculation is geometric line of sight, not actual sensor coverage
* the list of cities is currently hardcoded
* the frontend currently uses a fixed set of featured satellites
* the Render backend can take a little while to respond after being idle because of cold starts

## why i made it

I wanted to build something where I could actually see orbital mechanics rather than just working with numbers and tables.

It also gave me a reason to work with a few things I had not really put together in one project before, especially Python, Skyfield, live external data, coordinate transformations, Flask APIs and 3D browser visualisation.

There was also a lot of trial and error involved in getting the orbit, Earth and coverage footprint to all line up properly.

## project structure

The project is split into two main parts:

```text
XR-SatViz/
|
├── frontend
│   └── HTML / CSS / JavaScript / A-Frame
|
└── main.py
    └── Flask backend
        ├── CelesTrak data retrieval
        ├── Skyfield calculations
        ├── coordinate conversion
        ├── orbital trajectory
        ├── city visibility
        └── coverage footprint
```

This is still a project I am working on, so there are definitely things I want to improve with it later.
