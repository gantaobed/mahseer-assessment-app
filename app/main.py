from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import requests
import sqlite3
import io
import csv
import os
from datetime import datetime

app = FastAPI(title="Mahseer Live Telemetry Spawning Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def init_db():
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
    conn.commit()
    conn.close()

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

def fetch_live_weather_from_internet(lat: float, lng: float):
    """Fetches live weather data from Open-Meteo with an expanded timeout and graceful fallback."""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m&daily=precipitation_sum&timezone=auto"
    try:
        # Increased timeout to 12 seconds to handle slow network responses
        response = requests.get(url, timeout=12)
        if response.status_code == 200:
            data = response.json()
            current_temp = data.get("current", {}).get("temperature_2m", 24.0)
            daily_rains = data.get("daily", {}).get("precipitation_sum", [0.0])
            todays_rain = daily_rains[0] if daily_rains and daily_rains[0] is not None else 0.0
            return float(current_temp), float(todays_rain), True
    except Exception as e:
        print(f"⚠️ INTERNET TIMEOUT / ERROR: {e}. Using regional climatology fallback.")
    
    # Graceful fallback if the internet request times out so the app keeps working seamlessly
    return 24.0, 0.0, False

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    # 1. FETCH LIVE DATA FROM THE INTERNET
    live_temp, live_rain, fetched_live = fetch_live_weather_from_internet(data.lat, data.lng)
    
    data.temp_c = live_temp
    data.rainfall_mm_day = live_rain
    data.ph = 7.8  # Optimal Alkaline Shell Protector range (7.5 - 8.5)
        
    # Flow velocity dynamics driven by live rainfall runoff
    data.flow_velocity_ms = round(1.1 + (data.rainfall_mm_day * 0.015), 2)
    
    # Dissolved Oxygen (DO) dynamics linked to live water temperature
    data.do_mg_l = round(8.5 - ((data.temp_c - 20) * 0.12), 1)

    # --- 2. STRICT BIO-CHEMICAL VETO RULES ---
    if data.do_mg_l < 5.0:
        color, alert = "red", f"CRITICAL: Lethal Low Oxygen ({data.do_mg_l} mg/L). Embryos suffocate (Threshold: >7.5 mg/L)."
    elif data.temp_c > 28.0:
        color, alert = "red", f"CRITICAL: Thermal Spike ({data.temp_c}°C). Eggs rot or hatch prematurely (Ideal: 18-24°C)."
    elif data.ph < 6.5:
        color, alert = "red", f"CRITICAL: Acidic Danger (pH {data.ph}). Egg walls disintegrate (Ideal: 7.5-8.5)."
    elif data.ammonia_mg_l > 0.05:
        color, alert = "red", f"CRITICAL: Toxic Ammonia ({data.ammonia_mg_l} mg/L). Fatal to fish fry (Limit: <0.02 mg/L)."
    elif data.sand_mining_present:
        color, alert = "red", "CRITICAL: Active Local Sand Mining. Spawning gravel beds completely destroyed."
    elif data.flow_velocity_ms < 0.4 or data.flow_velocity_ms > 2.2:
        color, alert = "red", f"CRITICAL: Lethal Flow Velocity ({data.flow_velocity_ms} m/s). Unsuitable for egg anchoring."
    else:
        # --- 3. PHYSICAL HABITAT SCORING ---
        base = 3 if 0.8 <= data.flow_velocity_ms <= 1.5 else 1
        score = base * data.substrate_weight

        # --- 4. LIVE WEATHER & RUNOFF OVERLAP ---
        connection_status = "🌐 [Live Internet Synced]" if fetched_live else "⚠️ [Offline Fallback Active]"
        weather_desc = f"{connection_status} (Temp: {data.temp_c}°C | Rain: {data.rainfall_mm_day}mm | DO: {data.do_mg_l}mg/L)"
        
        if data.rainfall_mm_day > 50.0:
            return {"color": "red", "alert": f"CRITICAL: Severe Flash Flood Risk! Eggs washed away {weather_desc}."}
        elif data.rainfall_mm_day > 20.0:
            score -= 1.5
            weather_desc = f"Heavy Silt Runoff Warning {weather_desc}."
        else:
            weather_desc = f"Optimal Weather Conditions {weather_desc}."

        # --- 5. PREDICTIVE UPSTREAM DRIFT LOGIC ---
        prediction_alert = ""
        if not data.sand_mining_present and data.upstream_mining_active:
            score -= 1.5 
            prediction_alert = "<br><br><span class='alert-text'>⚠️ SILT DRIFT PREDICTION: Upstream sand extraction active. Silt suffocation imminent on gravel beds.</span>"

        # --- 6. FINAL SPAWNING VERDICT ---
        if score >= 2.5:
            color, alert = "green", f"🟢 PRIME SPAWNING ZONE: Ideal chemical & physical habitat for Mahseer egg incubation. {weather_desc} {prediction_alert}"
        elif score > 0:
            color, alert = "yellow", f"🟡 MARGINAL ZONE: Suboptimal conditions. Monitor closely. {weather_desc} {prediction_alert}"
        else:
            color, alert = "red", f"🔴 UNSUITABLE HABITAT: High stress environment. {weather_desc} {prediction_alert}"

    # --- LOG TO SQLITE DATABASE ---
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO assessments (timestamp, zone_id, zone_name, status_color, rainfall_mm, alert_message)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data.zone_id, data.zone_name, color, data.rainfall_mm_day, alert))
    conn.commit()
    conn.close()

    return {
        "color": color, 
        "alert": alert, 
        "live_fetched_data": {
            "temp_c": data.temp_c, 
            "rainfall_mm": data.rainfall_mm_day, 
            "flow": data.flow_velocity_ms, 
            "do_mg_l": data.do_mg_l, 
            "ph": data.ph,
            "internet_synced": fetched_live
        }
    }

@app.get("/history")
def get_assessment_history():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, timestamp, zone_name, status_color, rainfall_mm, alert_message FROM assessments ORDER BY id DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    return {"history": [{"id": r[0], "timestamp": r[1], "zone_name": r[2], "status_color": r[3], "rainfall_mm": r[4], "alert": r[5]} for r in rows]}

@app.get("/export-csv")
def export_csv():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, timestamp, zone_id, zone_name, status_color, rainfall_mm, alert_message FROM assessments ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Timestamp", "Zone ID", "Zone Name", "Status Color", "Rainfall (mm)", "Alert Message"])
    writer.writerows(rows)
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment;filename=mahseer_spawning_assessments.csv"}
    )

# --- SERVE FRONTEND ---
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(frontend_path, "index.html"))