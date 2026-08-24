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
    """Fetches real-time weather and river discharge data from Open-Meteo APIs."""
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,relative_humidity_2m,soil_temperature_0_to_7cm&daily=precipitation_sum&timezone=auto"
    flood_url = f"https://flood-api.open-meteo.com/v1/flood?latitude={lat}&longitude={lng}&daily=river_discharge&timezone=auto"

    results = {"fetched": False, "temp": 24.0, "rain": 0.0, "discharge": 1.0, "soil_temp": 22.0}

    try:
        # 1. Fetch Weather & Soil Data
        w_res = requests.get(weather_url, timeout=10)
        if w_res.status_code == 200:
            w_data = w_res.json()
            results["temp"] = w_data.get("current", {}).get("temperature_2m", 24.0)
            results["soil_temp"] = w_data.get("current", {}).get("soil_temperature_0_to_7cm", 22.0)
            results["rain"] = w_data.get("daily", {}).get("precipitation_sum", [0.0])[0]
            results["fetched"] = True

        # 2. Fetch River Discharge (Flow) Data
        f_res = requests.get(flood_url, timeout=10)
        if f_res.status_code == 200:
            f_data = f_res.json()
            # Get today's estimated river discharge in m3/s
            discharges = f_data.get("daily", {}).get("river_discharge", [1.0])
            results["discharge"] = discharges[0] if discharges[0] is not None else 1.0

    except Exception as e:
        print(f"⚠️ DATA FETCH ERROR: {e}")
    
    return results

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    # --- 1. SCIENTIFIC DATA ACQUISITION ---
    env = fetch_live_environmental_data(data.lat, data.lng)
    
    # Real-world data mapping
    data.temp_c = env["soil_temp"] # Soil temp at 0-7cm is a better proxy for shallow river beds
    data.rainfall_mm_day = env["rain"]
    
    # Flow Velocity Calculation (Scientific Approximation)
    # Based on river discharge (m3/s). Typical spawning streams are 0.5-2.0m deep.
    # Velocity approx = Discharge / (Width * Depth). Using a regional stream average for dynamic estimation.
    data.flow_velocity_ms = round(min(2.5, (env["discharge"] ** 0.4) * 0.5), 2)

    # Dissolved Oxygen (DO) Calculation (Henry's Law approximation)
    # Oxygen solubility decreases as water temperature rises.
    data.do_mg_l = round(14.62 - (0.39 * data.temp_c) + (0.005 * (data.temp_c**2)), 1)

    data.ph = 7.8 # Baseline for Deccan/Himalayan river systems

    source_tag = "📡 [Real-Time Global Telemetry Synced]" if env["fetched"] else "⚠️ [Predictive Modeling Active]"

    # --- 2. STRICT BIO-CHEMICAL VETO RULES ---
    if data.do_mg_l < 5.0:
        color, alert = "red", f"CRITICAL: Lethal Low Oxygen ({data.do_mg_l} mg/L). Embryos suffocate. {source_tag}"
    elif data.temp_c > 28.0:
        color, alert = "red", f"CRITICAL: Thermal Spike ({data.temp_c}°C). Ideal spawning is 18-24°C. {source_tag}"
    elif data.ph < 6.5:
        color, alert = "red", f"CRITICAL: Acidic Danger (pH {data.ph}). Egg walls disintegrate. {source_tag}"
    elif data.ammonia_mg_l > 0.05:
        color, alert = "red", f"CRITICAL: Toxic Ammonia ({data.ammonia_mg_l} mg/L). Fatal to fry. {source_tag}"
    elif data.sand_mining_present:
        color, alert = "red", f"CRITICAL: Active Sand Mining. Gravel beds destroyed. {source_tag}"
    elif data.flow_velocity_ms < 0.3 or data.flow_velocity_ms > 2.2:
        color, alert = "red", f"CRITICAL: Lethal Flow Velocity ({data.flow_velocity_ms} m/s). {source_tag}"
    else:
        # --- 3. HABITAT SUITABILITY INDEX (HSI) ---
        # Scoring based on Optimal Range: Flow (0.8-1.5), Temp (20-24)
        score = 0
        if 0.8 <= data.flow_velocity_ms <= 1.5: score += 2
        if 20 <= data.temp_c <= 24: score += 2
        
        # --- 4. WEATHER & RUNOFF DYNAMICS ---
        if data.rainfall_mm_day > 40.0:
            color, alert = "red", f"🔴 UNSUITABLE: Extreme Flash Flood Risk ({data.rainfall_mm_day}mm rain). Eggs will wash away. {source_tag}"
        elif score >= 3:
            color, alert = "green", f"🟢 PRIME SPAWNING ZONE: Optimal chemical & physical habitat. {source_tag}"
        elif score >= 1:
            color, alert = "yellow", f"🟡 MARGINAL ZONE: Suboptimal conditions detected. {source_tag}"
        else:
            color, alert = "red", f"🔴 UNSUITABLE HABITAT: Environmental stress detected. {source_tag}"

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

@app.get("/history-view")
async def history_view():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, zone_name, status_color, alert_message FROM assessments ORDER BY id DESC LIMIT 100")
    logs = cursor.fetchall()
    conn.close()

    html_content = """
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: sans-serif; background: #121212; color: white; padding: 20px; }
            .log-card { background: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 5px solid #444; }
            .green { border-left-color: #4caf50; } .yellow { border-left-color: #fbc02d; } .red { border-left-color: #e53935; }
            .timestamp { color: #888; font-size: 0.8em; }
            .footer { text-align: center; margin-top: 30px; font-size: 0.8em; color: #555; }
        </style>
    </head>
    <body>
        <h2>Assessment History Logs</h2>
    """
    for log in logs:
        html_content += f"""
        <div class="log-card {log[2]}">
            <div class="timestamp">{log[0]}</div>
            <strong>{log[1]}</strong><br>
            <small>{log[3]}</small>
        </div>
        """
    html_content += """
        <div class="footer">© Developed by Ganta Obed</div>
    </body></html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)

@app.get("/species-info")
async def species_info():
    html_content = """
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: sans-serif; background: #121212; color: white; padding: 20px; line-height: 1.6; }
            .info-card { background: #1e1e1e; padding: 20px; border-radius: 12px; margin-bottom: 20px; border: 1px solid #333; }
            h2 { color: #3b82f6; }
            .tag { background: #3b82f6; padding: 4px 8px; border-radius: 4px; font-size: 0.8em; font-weight: bold; }
            .footer { text-align: center; margin-top: 30px; font-size: 0.8em; color: #555; }
        </style>
    </head>
    <body>
        <h2>Mahseer Spawning Intelligence</h2>

        <div class="info-card">
            <h3>🌊 Flow Dynamics</h3>
            <p>Mahseer require specific flow velocities (0.8 - 1.5 m/s) to ensure eggs are oxygenated but not washed away. High siltation from mining acts as a "suffocator" for the gravel beds.</p>
        </div>

        <div class="info-card">
            <h3>🌡️ Thermal Thresholds</h3>
            <p>Ideal spawning temperature is between <span class="tag">18°C - 24°C</span>. Temperatures above 28°C significantly reduce hatching success and increase fungal infections.</p>
        </div>

        <div class="info-card">
            <h3>🧪 Bio-Chemical Vetoes</h3>
            <p>Dissolved Oxygen (DO) must remain above 7.5 mg/L. Ammonia levels exceeding 0.05 mg/L are lethal to developing fry.</p>
        </div>

        <div class="footer">© Developed by Ganta Obed</div>
    </body></html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)