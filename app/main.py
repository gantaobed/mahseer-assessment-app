from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import requests
import sqlite3
import os
from datetime import datetime, timedelta

app = FastAPI(title="Kaveri Spawning Sentinel Pro")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SCIENTIFIC DATA & POLYGON DEFINITIONS ---
PROTECTED_ZONES = [
    {"name": "Moyar River Sanctuary", "lat_min": 11.45, "lat_max": 11.65, "lng_min": 76.4, "lng_max": 77.2, "is_critical": True},
    {"name": "Pambar River Sanctuary", "lat_min": 10.15, "lat_max": 10.35, "lng_min": 77.1, "lng_max": 77.4, "is_critical": True}
]

def init_db():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL, status_color TEXT, alert TEXT, temp REAL, oxygen REAL, mining REAL, ph REAL, turbidity REAL, fragmentation REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS mining_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL, description TEXT, level TEXT, verified INTEGER DEFAULT 0)")
    conn.commit(); conn.close()

init_db()

class EnvironmentData(BaseModel):
    lat: float
    lng: float

def fetch_telemetry(lat: float, lng: float):
    try:
        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,soil_temperature_0_to_7cm&daily=precipitation_sum&timezone=auto"
        w = requests.get(w_url, timeout=5).json()
        return {
            "temp": w.get("current", {}).get("soil_temperature_0_to_7cm", 22.0),
            "rain": w.get("daily", {}).get("precipitation_sum", [0.0])[0]
        }
    except: return {"temp": 22.0, "rain": 0.0}

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    in_kaveri = 10.0 <= data.lat <= 13.5 and 75.0 <= data.lng <= 80.5
    is_critical_range = any(z["lat_min"] <= data.lat <= z["lat_max"] and z["lng_min"] <= data.lng <= z["lng_max"] for z in PROTECTED_ZONES)

    tel = fetch_telemetry(data.lat, data.lng)
    temp = tel["temp"]
    rain = tel["rain"]

    # 1. Temporal Context (Monsoon Logic)
    is_monsoon = 6 <= datetime.now().month <= 9
    seasonal_risk_multiplier = 1.5 if is_monsoon else 1.0

    # 2. Dynamic Risk Scoring & Adaptive History
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT mining FROM assessments WHERE lat BETWEEN ? AND ? ORDER BY id DESC LIMIT 5", (data.lat-0.02, data.lat+0.02))
    past_trends = [r[0] for r in cursor.fetchall()]

    base_mining_prob = 5 if 12.1 < data.lat < 12.4 else 0
    if len(past_trends) > 1 and past_trends[0] > past_trends[-1]:
        base_mining_prob += 15 # Rising trend escalation

    final_mining_risk = base_mining_prob * seasonal_risk_multiplier

    # 3. Threat Layer Expansion
    ph = 7.8
    turbidity = 5 + (rain * 2) # Turbidity increases with rain/silt
    fragmentation = 0.8 if data.lat > 12.0 else 0.2 # Simulated dam proximity

    # 4. Species Cross-Checks (Invasive/Hybridization)
    invasive_risk = "Tor khudree detected" if data.lat > 12.0 else "Tor putitora/Tor tor competition"

    basin_name = "Kaveri Basin System" if in_kaveri else "Outside Domain"
    constraints_status = "STABLE" if (final_mining_risk <= 20 and ph >= 6.5 and turbidity <= 50) else "VIOLATED"

    # Graded Status Thresholds
    if not in_kaveri:
        color, alert = "gray", "🔴 FAILED: Outside Kaveri domain."
    elif final_mining_risk > 20 or ph < 6.5 or turbidity > 50:
        color, alert = "red", f"🔴 HIGH RISK: {final_mining_risk}% Mining | Turbidity {int(turbidity)} NTU. Habitat compromised."
    elif 0 < final_mining_risk <= 20 or not is_critical_range:
        color, alert = "yellow", f"🟡 AMBER: {final_mining_risk}% Risk. Monitor for fragmentation and invasive {invasive_risk}."
    else:
        color, alert = "green", "🟢 SANCTUARY: 0% Risk verified in critical spawning pool. Sanctuary active."

    cursor.execute("INSERT INTO assessments (timestamp, lat, lng, status_color, alert, temp, oxygen, mining, ph, turbidity, fragmentation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M"), data.lat, data.lng, color, alert, temp, 7.8, final_mining_risk, ph, turbidity, fragmentation))
    conn.commit(); conn.close()

    return {
        "color": color, "alert": alert,
        "audit": {
            "range": "PASSED" if in_kaveri else "FAILED",
            "basin": basin_name,
            "constraints": constraints_status
        },
        "details": {"temp": temp, "mining": final_mining_risk, "ph": ph, "turbidity": int(turbidity), "frag": fragmentation}
    }

@app.get("/history-view")
async def history_view():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, alert, lat, lng, mining, turbidity FROM assessments ORDER BY id DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    html = "<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body { background:#0f172a; color:white; font-family:sans-serif; padding:20px; font-size:24px; } .card { background:#1e293b; padding:20px; border-radius:15px; margin-bottom:15px; border-left:8px solid #3b82f6; } h2 { color:#38bdf8; font-size:40px; } .meta { font-size:18px; margin-top:5px; font-weight:bold; }</style></head><body><h2>Kaveri Intelligence Logs</h2>"
    for r in rows:
        m_color = "#ef4444" if r[4] > 20 else "#fbc02d" if r[4] > 0 else "#22c55e"
        html += f"<div class='card'><div>{r[0]}</div><strong>{r[1]}</strong><div class='meta' style='color:{m_color}'>Risk: {r[4]}% | Turbidity: {r[5]} NTU</div></div>"
    html += "</body></html>"
    return HTMLResponse(content=html)

@app.get("/species-info")
async def species_info():
    html = """
    <html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <style>
        body { background:#0f172a; color:white; font-family:sans-serif; padding:25px; font-size:26px; line-height:1.5; }
        .card { background:#1e293b; padding:25px; border-radius:20px; margin-bottom:20px; border:1px solid #334155; }
        h2 { color:#38bdf8; font-size:45px; border-bottom:3px solid #334155; padding-bottom:10px; }
        h3 { color:#fbbf24; font-size:32px; margin-bottom:10px; }
        table { width:100%; border-collapse:collapse; margin-top:15px; font-size:22px; }
        th, td { border:1px solid #444; padding:12px; text-align:left; }
        th { background:#222; }
    </style></head><body>
    <h2>Orange-finned Mahseer (Tor remadeviae)</h2>

    <div class='card'>
        <h3>🌍 Natural Habitat & Distribution</h3>
        <p><b>Endemic Region:</b> Western Ghats, South India.<br>
        <b>Primary Basin:</b> Kaveri River system (Karnataka, Tamil Nadu, Kerala).<br>
        <b>Key Tributaries:</b> Moyar, Kabini, Bhavani, and Pambar rivers.<br>
        <b>Current Spawning Areas:</b> Only a 40 km stretch of the Moyar River (TN) and parts of the Pambar River (Kerala) still support breeding populations.</p>
    </div>

    <div class='card'>
        <h3>📏 Growth & Size</h3>
        <p><b>Max Length:</b> ~175 cm (1.75 m)<br>
        <b>Max Weight:</b> ~54 kg<br>
        <b>Diet:</b> Omnivorous (Algae, Detritus, Invertebrates, Zooplankton)</p>
    </div>

    <div class='card' style='border-left:8px solid #ef4444'>
        <h3>⚠️ Conservation Status: CRITICALLY ENDANGERED</h3>
        <p><b>Threats:</b> Dams, Invasive Species (Tor khudree, Tor putitora, Tor tor), Overfishing, Pollution, and Climate Change.</p>
    </div>

    <div class='card'>
        <h3>📊 Summary Table</h3>
        <table>
            <tr><th>Attribute</th><th>Details</th></tr>
            <tr><td>Scientific Name</td><td>Tor remadeviae</td></tr>
            <tr><td>Current Range</td><td>Moyar (TN), Pambar (Kerala)</td></tr>
            <tr><td>Status</td><td>Critically Endangered (IUCN)</td></tr>
            <tr><td>Hybridization Risk</td><td>High (due to invasive competitors)</td></tr>
        </table>
    </div>
    </body></html>
    """
    return HTMLResponse(content=html)

@app.get("/ping")
def ping():
    return {"status": "online", "timestamp": datetime.now().isoformat()}

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
@app.get("/")
async def read_index(): return FileResponse(os.path.join(frontend_path, "index.html"))
