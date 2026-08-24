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
                alert_message TEXT
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
    flow_velocity_ms: Optional[float] = None
    substrate_weight: float = 1.0
    do_mg_l: Optional[float] = None
    temp_c: Optional[float] = None
    ph: Optional[float] = None
    ammonia_mg_l: float = 0.01
    sand_mining_present: bool = False
    upstream_mining_active: bool = False
    rainfall_mm_day: Optional[float] = None

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
                results["forecast"].append({
                    "date": dates[i], "rain": rains[i], "temp": temps[i],
                    "status": "Green" if rains[i] < 20 and 18 <= temps[i] <= 26 else "Yellow" if rains[i] < 40 else "Red"
                })
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
        data.temp_c = env.get("soil_temp", 22.0)
        data.rainfall_mm_day = env.get("rain", 0.0)
        discharge = max(0.1, env.get("discharge", 1.0))
        data.flow_velocity_ms = round(min(2.5, (discharge ** 0.4) * 0.5), 2)
        temp = max(0, data.temp_c)
        data.do_mg_l = round(14.62 - (0.39 * temp) + (0.005 * (temp**2)), 1)
        data.ph = 7.8
        source_tag = "📡 [Live Telemetry Synced]" if env.get("fetched") else "⚠️ [Modeling Active]"
        if data.do_mg_l < 5.0: color, alert = "red", f"🔴 CRITICAL: Low Oxygen ({data.do_mg_l} mg/L). {source_tag}"
        elif data.temp_c > 28.0: color, alert = "red", f"🔴 CRITICAL: Thermal Spike ({data.temp_c}°C). {source_tag}"
        elif data.sand_mining_present: color, alert = "red", f"🔴 CRITICAL: Sand Mining Active. {source_tag}"
        elif data.flow_velocity_ms < 0.3 or data.flow_velocity_ms > 2.2: color, alert = "red", f"🔴 CRITICAL: Lethal Flow ({data.flow_velocity_ms} m/s). {source_tag}"
        else:
            score = 0
            if 0.8 <= data.flow_velocity_ms <= 1.5: score += 2
            if 20 <= data.temp_c <= 24: score += 2
            if data.rainfall_mm_day > 40.0: color, alert = "red", f"🔴 UNSUITABLE: Flash Flood Risk ({data.rainfall_mm_day}mm rain). {source_tag}"
            elif score >= 3: color, alert = "green", f"🟢 PRIME SPAWNING ZONE: Optimal conditions. {source_tag}"
            elif score >= 1: color, alert = "yellow", f"🟡 MARGINAL ZONE: Suboptimal detected. {source_tag}"
            else: color, alert = "red", f"🔴 UNSUITABLE HABITAT. {source_tag}"
        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO assessments (timestamp, zone_id, zone_name, status_color, rainfall_mm, alert_message) VALUES (?, ?, ?, ?, ?, ?)",
                       (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data.zone_id, data.zone_name, color, data.rainfall_mm_day, alert))
        conn.commit()
        conn.close()
        return {"color": color, "alert": alert, "forecast": env.get("forecast", []), "live_fetched_data": {"temp_c": data.temp_c, "rainfall_mm": data.rainfall_mm_day, "flow": data.flow_velocity_ms, "do_mg_l": data.do_mg_l, "ph": data.ph, "internet_synced": env.get("fetched", False)}}
    except Exception as e: return {"color": "red", "alert": f"⚠️ ENGINE ERROR: {str(e)}"}

@app.post("/report-incident")
async def report_incident(
    lat: float = Form(...),
    lng: float = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    image: Optional[UploadFile] = File(None)
):
    image_url = ""
    if image:
        file_path = os.path.join(UPLOAD_DIR, f"{datetime.now().timestamp()}_{image.filename}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        image_url = f"/uploads/{os.path.basename(file_path)}"

    try:
        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO incident_reports (timestamp, lat, lng, category, description, image_url) VALUES (?, ?, ?, ?, ?, ?)",
                       (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), lat, lng, category, description, image_url))
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Incident reported with photo. Thank you!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/get-trends")
def get_trends(lat: float, lng: float):
    # Simulate a 24-hour trend for visualization
    now = datetime.now()
    labels = [(now - timedelta(hours=i)).strftime("%H:00") for i in range(24)][::-1]
    temp_data = [20 + (i % 5) for i in range(24)]
    do_data = [8.5 - (i % 3) * 0.2 for i in range(24)]
    return {"labels": labels, "temp_data": temp_data, "do_data": do_data}

@app.get("/history-view")
async def history_view():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, category, description, image_url FROM incident_reports ORDER BY id DESC LIMIT 50")
    incidents = cursor.fetchall()
    conn.close()
    html = "<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body { font-family: sans-serif; background: #121212; color: white; padding: 20px; } .card { background: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 5px solid #3b82f6; } .timestamp { color: #888; font-size: 0.8em; } .img-preview { width: 100%; border-radius: 4px; margin-top: 10px; }</style></head><body><h2>🚨 Recent Incident Reports</h2>"
    for inc in incidents:
        img_tag = f"<img src='{inc[3]}' class='img-preview'>" if inc[3] else ""
        html += f"<div class='card'><div class='timestamp'>{inc[0]}</div><strong>[{inc[1]}]</strong><br><small>{inc[2]}</small>{img_tag}</div>"
    html += "</body></html>"
    return HTMLResponse(content=html)

@app.get("/get-heatmap")
def get_heatmap():
    # Dynamic heatmap generator based on current regional suitability
    # In a real app, this would query a grid of points
    return {"points": [
        [12.27, 77.44, 0.8], [12.19, 76.90, 0.2], [12.54, 77.42, 0.6],
        [11.55, 76.95, 0.9], [10.28, 77.26, 0.7], [12.85, 77.58, 0.4]
    ]}

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
@app.get("/")
async def read_index(): return FileResponse(os.path.join(frontend_path, "index.html"))
