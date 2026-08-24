from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import requests
import sqlite3
import io
import csv
import os
import shutil
from datetime import datetime, timedelta

app = FastAPI(title="Mahseer Live Telemetry Spawning Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --- SPECIES DATABASE ---
SPECIES_DATA = {
    "golden": {
        "name": "Golden Mahseer (Tor putitora)",
        "temp_min": 18, "temp_max": 24, "do_min": 7.5, "flow_min": 0.8, "flow_max": 1.5,
        "desc": "Found in Himalayan foothills. Requires cold, highly oxygenated snow-fed waters."
    },
    "blue_finned": {
        "name": "Blue-Finned Mahseer (Tor khudree)",
        "temp_min": 22, "temp_max": 28, "do_min": 6.5, "flow_min": 0.5, "flow_max": 1.2,
        "desc": "Native to Deccan plateau rivers. More tolerant of slightly warmer tropical waters."
    },
    "hump_backed": {
        "name": "Hump-Backed Mahseer (Tor remadevii)",
        "temp_min": 20, "temp_max": 26, "do_min": 7.0, "flow_min": 0.7, "flow_max": 1.4,
        "desc": "The 'Tiger of the Cauvery'. Critically endangered. Extremely sensitive to siltation."
    },
    "chocolate": {
        "name": "Chocolate Mahseer (Neolissochilus hexagonolepis)",
        "temp_min": 15, "temp_max": 22, "do_min": 8.0, "flow_min": 0.6, "flow_max": 1.8,
        "desc": "Found in North-East India. Prefers very cool mountain torrents."
    }
}

def init_db():
    try:
        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                zone_id INTEGER,
                zone_name TEXT,
                status_color TEXT,
                rainfall_mm REAL,
                alert_message TEXT,
                species_name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incident_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                lat REAL,
                lng REAL,
                category TEXT,
                description TEXT,
                image_url TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ DATABASE ERROR: {e}")

init_db()

class EnvironmentData(BaseModel):
    zone_id: int
    zone_name: str
    lat: float
    lng: float
    species_id: str = "golden"
    sand_mining_present: bool = False
    upstream_mining_active: bool = False

class IncidentReport(BaseModel):
    lat: float
    lng: float
    category: str
    description: str

def fetch_live_environmental_data(lat: float, lng: float):
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,soil_temperature_0_to_7cm&daily=precipitation_sum,temperature_2m_max&timezone=auto"
    flood_url = f"https://flood-api.open-meteo.com/v1/flood?latitude={lat}&longitude={lng}&daily=river_discharge&timezone=auto"
    results = {"fetched": False, "temp": 24.0, "rain": 0.0, "discharge": 1.0, "soil_temp": 22.0, "forecast": []}
    try:
        w_res = requests.get(weather_url, timeout=10)
        if w_res.status_code == 200:
            w_data = w_res.json()
            results["temp"] = w_data.get("current", {}).get("temperature_2m", 24.0)
            results["soil_temp"] = w_data.get("current", {}).get("soil_temperature_0_to_7cm", 22.0)
            rain_list = w_data.get("daily", {}).get("precipitation_sum", [0.0])
            results["rain"] = rain_list[0] if rain_list and len(rain_list) > 0 else 0.0

            dates = w_data.get("daily", {}).get("time", [])
            rains = w_data.get("daily", {}).get("precipitation_sum", [])
            temps = w_data.get("daily", {}).get("temperature_2m_max", [])
            for i in range(min(len(dates), 7)):
                results["forecast"].append({"date": dates[i], "rain": rains[i], "temp": temps[i]})
            results["fetched"] = True

        f_res = requests.get(flood_url, timeout=10)
        if f_res.status_code == 200:
            f_data = f_res.json()
            discharges = f_data.get("daily", {}).get("river_discharge", [1.0])
            if discharges and len(discharges) > 0:
                results["discharge"] = discharges[0] if discharges[0] is not None else 1.0
    except Exception as e:
        print(f"⚠️ DATA FETCH ERROR: {e}")
    return results

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    try:
        env = fetch_live_environmental_data(data.lat, data.lng)
        species = SPECIES_DATA.get(data.species_id, SPECIES_DATA["golden"])

        data_temp = env.get("soil_temp", 22.0)
        rainfall = env.get("rain", 0.0)
        discharge = max(0.1, env.get("discharge", 1.0))
        flow = round(min(2.5, (discharge ** 0.4) * 0.5), 2)
        do = round(14.62 - (0.39 * data_temp) + (0.005 * (data_temp**2)), 1)

        source_tag = "📡 [Live Telemetry Synced]" if env.get("fetched") else "⚠️ [Modeling Active]"

        # --- SMART SPECIES LOGIC ---
        color, alert = "green", "🟢 PRIME SPAWNING ZONE: Optimal conditions."

        if do < species["do_min"]:
            color, alert = "red", f"🔴 CRITICAL: Low Oxygen ({do} mg/L) for {species['name']}."
        elif data_temp > species["temp_max"] or data_temp < species["temp_min"]:
            color, alert = "red", f"🔴 CRITICAL: Thermal Stress ({data_temp}°C) for {species['name']}."
        elif flow > species["flow_max"] or flow < species["flow_min"]:
            color, alert = "red", f"🔴 CRITICAL: Lethal Flow ({flow} m/s) for {species['name']}."
        elif data.sand_mining_present:
            color, alert = "red", f"🔴 CRITICAL: Sand Mining Destroying Habitat."
        elif rainfall > 40.0:
            color, alert = "red", f"🔴 UNSUITABLE: Extreme Flash Flood Risk."
        elif abs(data_temp - (species["temp_min"]+species["temp_max"])/2) > 3:
            color, alert = "yellow", f"🟡 MARGINAL ZONE: Suboptimal temperature for {species['name']}."

        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO assessments (timestamp, zone_id, zone_name, status_color, rainfall_mm, alert_message, species_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data.zone_id, data.zone_name, color, rainfall, alert, species['name']))
        conn.commit()
        conn.close()

        return {
            "color": color, "alert": alert, "species_name": species["name"],
            "live_fetched_data": {"temp_c": data_temp, "rainfall_mm": rainfall, "flow": flow, "do_mg_l": do}
        }
    except Exception as e:
        return {"color": "red", "alert": f"⚠️ ENGINE ERROR: {str(e)}"}

@app.post("/report-incident")
async def report_incident(lat: float = Form(...), lng: float = Form(...), category: str = Form(...), description: str = Form(...), image: Optional[UploadFile] = File(None)):
    image_url = ""
    if image:
        file_path = os.path.join(UPLOAD_DIR, f"{datetime.now().timestamp()}_{image.filename}")
        with open(file_path, "wb") as buffer: shutil.copyfileobj(image.file, buffer)
        image_url = f"/uploads/{os.path.basename(file_path)}"
    try:
        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO incident_reports (timestamp, lat, lng, category, description, image_url) VALUES (?, ?, ?, ?, ?, ?)",
                       (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), lat, lng, category, description, image_url))
        conn.commit(); conn.close()
        return {"status": "success", "message": "Incident reported. Thank you!"}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/get-trends")
def get_trends(lat: float, lng: float):
    now = datetime.now()
    labels = [(now - timedelta(hours=i)).strftime("%H:00") for i in range(24)][::-1]
    return {"labels": labels, "temp_data": [20 + (i % 5) for i in range(24)], "do_data": [8.5 - (i % 3) * 0.2 for i in range(24)]}

@app.get("/history-view")
async def history_view():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, zone_name, status_color, alert_message, species_name FROM assessments ORDER BY id DESC LIMIT 30")
    logs = cursor.fetchall()
    cursor.execute("SELECT timestamp, category, description, image_url FROM incident_reports ORDER BY id DESC LIMIT 20")
    incidents = cursor.fetchall()
    conn.close()
    html = "<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body { font-family: sans-serif; background: #121212; color: white; padding: 15px; } .card { background: #1e1e1e; padding: 12px; border-radius: 8px; margin-bottom: 10px; border-left: 5px solid #3b82f6; font-size: 0.9em; } .timestamp { color: #888; font-size: 0.8em; } .img-preview { width: 100%; border-radius: 4px; margin-top: 10px; } .species-tag { background: #3b82f6; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }</style></head><body>"
    html += "<h2>🚨 Reports</h2>"
    for inc in incidents:
        img = f"<img src='{inc[3]}' class='img-preview'>" if inc[3] else ""
        html += f"<div class='card'><div class='timestamp'>{inc[0]}</div><strong>[{inc[1]}]</strong><br>{inc[2]}{img}</div>"
    html += "<h2>📊 History</h2>"
    for log in logs:
        color = "#4caf50" if log[2] == "green" else "#fbc02d" if log[2] == "yellow" else "#e53935"
        html += f"<div class='card' style='border-left-color:{color}'><div class='timestamp'>{log[0]}</div><span class='species-tag'>{log[4]}</span><br><strong>{log[1]}</strong><br><small>{log[3]}</small></div>"
    html += "</body></html>"
    return HTMLResponse(content=html)

@app.get("/species-info")
async def species_info():
    html = "<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body { font-family: sans-serif; background: #121212; color: white; padding: 20px; } .card { background: #1e1e1e; padding: 20px; border-radius: 12px; margin-bottom: 20px; border: 1px solid #333; } h2 { color: #3b82f6; } .stat { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; font-size: 0.9em; color: #aaa; } </style></head><body><h2>Mahseer Species Catalog</h2>"
    for sid, s in SPECIES_DATA.items():
        html += f"<div class='card'><h3>{s['name']}</h3><p>{s['desc']}</p><div class='stat'><span>🌡️ {s['temp_min']}-{s['temp_max']}°C</span><span>🌊 {s['flow_min']}-{s['flow_max']}m/s</span><span>🧪 DO > {s['do_min']}mg/L</span></div></div>"
    html += "</body></html>"
    return HTMLResponse(content=html)

@app.get("/get-heatmap")
def get_heatmap():
    return {"points": [[12.27, 77.44, 0.8], [11.55, 76.95, 0.9], [10.28, 77.26, 0.7]]}

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
@app.get("/")
async def read_index(): return FileResponse(os.path.join(frontend_path, "index.html"))
