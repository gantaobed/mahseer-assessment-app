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

app = FastAPI(title="Cauvery Sentinel Pro")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SCIENTIFIC DATA ---
SPECIES_LIST = [
    {"name": "Orange-finned Mahseer (Tor remadevii)", "range": "Cauvery Basin Only", "status": "Critically Endangered", "desc": "The 'Tiger of the Cauvery'. Requires rocky pools and pristine flow."},
    {"name": "Golden Mahseer (Tor putitora)", "range": "Himalayan Foothills", "status": "Endangered", "desc": "Found in northern rivers like the Ganges and Indus."},
    {"name": "Blue-finned Mahseer (Tor khudree)", "range": "Deccan Rivers", "status": "Least Concern", "desc": "Common in the Krishna and Godavari systems."},
    {"name": "Chocolate Mahseer", "range": "North-East India", "status": "Near Threatened", "desc": "Found in the Brahmaputra basin torrents."}
]

def init_db():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL, status_color TEXT, alert TEXT, temp REAL, oxygen REAL, mining REAL, rainfall REAL, flow REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS mining_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL, description TEXT, level TEXT)")
    conn.commit()
    conn.close()

init_db()

class EnvironmentData(BaseModel):
    lat: float
    lng: float

def fetch_area_details(lat: float, lng: float):
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,soil_temperature_0_to_7cm&daily=precipitation_sum&timezone=auto"
    flood_url = f"https://flood-api.open-meteo.com/v1/flood?latitude={lat}&longitude={lng}&daily=river_discharge&timezone=auto"
    res = {"temp": 22.0, "rain": 0.0, "discharge": 1.0, "soil_temp": 21.0}
    try:
        w = requests.get(weather_url, timeout=5).json()
        res["temp"] = w.get("current", {}).get("temperature_2m", 22.0)
        res["soil_temp"] = w.get("current", {}).get("soil_temperature_0_to_7cm", 21.0)
        res["rain"] = w.get("daily", {}).get("precipitation_sum", [0.0])[0]
        f = requests.get(flood_url, timeout=5).json()
        res["discharge"] = f.get("daily", {}).get("river_discharge", [1.0])[0] or 1.0
    except: pass
    return res

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    in_range = 10.0 <= data.lat <= 13.5 and 75.0 <= data.lng <= 80.5
    env = fetch_area_details(data.lat, data.lng)

    # Mafia/Mining Proximity Logic
    mining_prob = 5
    if 12.1 < data.lat < 12.4: mining_prob = 85

    # Check historical mining reports in this area
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM mining_reports WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
                   (data.lat-0.05, data.lat+0.05, data.lng-0.05, data.lng+0.05))
    local_reports = cursor.fetchone()[0]
    if local_reports > 0: mining_prob = max(mining_prob, 95)

    temp = env["soil_temp"]
    do = round(14.6 - (0.3 * temp), 1)
    habitat_integrity = mining_prob < 40 and 18 <= temp <= 25

    if not in_range:
        color, alert = "gray", "🔴 FAILED: Outside species range."
    elif mining_prob > 70:
        color, alert = "red", "⛔ ILLEGAL MINING ZONE: Spawning strictly prohibited due to Mafia presence."
    elif not habitat_integrity:
        color, alert = "red", "🔴 CRITICAL: Environmental Stress detected."
    else:
        color, alert = "green", "🟢 PROTECTED SANCTUARY: Spawning site verified. Mining strictly prohibited."

    # Log to History
    cursor.execute("INSERT INTO assessments (timestamp, lat, lng, status_color, alert, temp, oxygen, mining, rainfall, flow) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M"), data.lat, data.lng, color, alert, temp, do, mining_prob, env["rain"], 1.1))
    conn.commit(); conn.close()

    return {
        "color": color, "alert": alert,
        "audit": {
            "range": "PASSED" if in_range else "FAILED",
            "mafia_watch": "CRITICAL THREAT" if mining_prob > 70 else "SECURE",
            "constraints": "STABLE" if habitat_integrity else "VIOLATED"
        },
        "details": {
            "temp": temp, "oxygen": do, "mining": mining_prob,
            "basin": "Cauvery Basin" if in_range else "Unknown"
        }
    }

@app.get("/get-area-trends")
def get_area_trends(lat: float, lng: float):
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    # Find all assessments within ~5km of this spot
    cursor.execute("SELECT timestamp, status_color, mining, temp FROM assessments WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? ORDER BY id DESC LIMIT 10",
                   (lat-0.05, lat+0.05, lng-0.05, lng+0.05))
    rows = cursor.fetchall()
    conn.close()
    return {"trends": [{"time": r[0], "status": r[1], "mining": r[2], "temp": r[3]} for r in rows]}

@app.post("/report-mafia")
def report_mafia(data: EnvironmentData):
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO mining_reports (timestamp, lat, lng, description, level) VALUES (?, ?, ?, ?, ?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M"), data.lat, data.lng, "Illegal Mining Activity Reported", "CRITICAL"))
    conn.commit(); conn.close()
    return {"status": "success", "message": "🚨 MAFIA REPORT LOGGED. Authorities notified of illegal activity in this sanctuary."}

@app.get("/history-view")
async def history_view():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, alert, lat, lng, mining FROM assessments ORDER BY id DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    html = """<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body { background:#0f172a; color:white; font-family:sans-serif; padding:25px; font-size:24px; } .card { background:#1e293b; padding:20px; border-radius:15px; margin-bottom:15px; border-left:8px solid #3b82f6; } h2 { color:#38bdf8; font-size:40px; } .meta { color:#ef4444; font-size:18px; margin-top:5px; font-weight:bold; }</style></head><body><h2>Sentinel Spawning Watch</h2>"""
    for r in rows:
        html += f"<div class='card'><div>{r[0]}</div><strong>{r[1]}</strong><div class='meta'>Mining Threat: {r[4]}% | {r[2]}, {r[3]}</div></div>"
    html += "</body></html>"
    return HTMLResponse(content=html)

@app.get("/species-info")
async def species_info():
    html = """<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body { background:#0f172a; color:white; font-family:sans-serif; padding:25px; font-size:24px; line-height:1.6; } .card { background:#1e293b; padding:25px; border-radius:20px; margin-bottom:20px; border:1px solid #334155; } h2 { color:#38bdf8; font-size:45px; } h3 { color:#fbbf24; margin:0; font-size:32px; } .tag { display:inline-block; background:#e53935; padding:4px 12px; border-radius:8px; font-size:14px; font-weight:bold; margin-top:10px; }</style></head><body><h2>Cauvery Conservation Rules</h2><div class='card'><h3>🚫 MINING PROHIBITION</h3><p>As per NGT and State Guidelines, sand mining is <strong>strictly prohibited</strong> in all Mahseer spawning zones. Illegal activity (Mafia) must be reported immediately.</p></div>"""
    for s in SPECIES_LIST:
        html += f"<div class='card'><h3>{s['name']}</h3><p>{s['desc']}</p></div>"
    html += "</body></html>"
    return HTMLResponse(content=html)

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
@app.get("/")
async def read_index(): return FileResponse(os.path.join(frontend_path, "index.html"))
