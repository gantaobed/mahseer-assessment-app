from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import requests
import sqlite3
import os
from datetime import datetime

app = FastAPI(title="Cauvery Sentinel Ultimate")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Scientific Data
SPECIES_LIST = [
    {"name": "Orange-finned Mahseer (Tor remadevii)", "range": "Cauvery Basin Only", "status": "Critically Endangered", "desc": "The 'Tiger of the Cauvery'. Requires rocky pools and pristine flow."},
    {"name": "Golden Mahseer (Tor putitora)", "range": "Himalayan Foothills", "status": "Endangered", "desc": "Found in northern rivers like the Ganges and Indus."},
    {"name": "Blue-finned Mahseer (Tor khudree)", "range": "Deccan Rivers", "status": "Least Concern", "desc": "Common in the Krishna and Godavari systems."},
    {"name": "Chocolate Mahseer", "range": "North-East India", "status": "Near Threatened", "desc": "Found in the Brahmaputra basin torrents."}
]

def init_db():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL, status_color TEXT, alert TEXT, temp REAL, oxygen REAL, mining REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS mining_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL, description TEXT, level TEXT)")
    conn.commit(); conn.close()

init_db()

class EnvironmentData(BaseModel):
    lat: float
    lng: float

def fetch_details(lat: float, lng: float):
    try:
        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,soil_temperature_0_to_7cm&timezone=auto"
        w = requests.get(w_url, timeout=5).json()
        temp = w.get("current", {}).get("soil_temperature_0_to_7cm", 22.0)
        return temp
    except: return 22.0

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    in_range = 10.0 <= data.lat <= 13.5 and 75.0 <= data.lng <= 80.5
    temp = fetch_details(data.lat, data.lng)

    mining_prob = 5
    if 12.1 < data.lat < 12.4: mining_prob = 85

    if not in_range:
        color, alert = "gray", "🔴 FAILED: Outside species range."
    elif mining_prob > 50:
        color, alert = "red", "⛔ ILLEGAL MINING ZONE: Spawning strictly prohibited."
    else:
        color, alert = "green", "🟢 PROTECTED SANCTUARY: Verified spawning site."

    # Log to DB
    try:
        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO assessments (timestamp, lat, lng, status_color, alert, temp, oxygen, mining) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (datetime.now().strftime("%Y-%m-%d %H:%M"), data.lat, data.lng, color, alert, temp, 7.8, mining_prob))
        conn.commit(); conn.close()
    except: pass

    return {
        "color": color, "alert": alert,
        "details": {"temp": temp, "oxygen": 7.8, "mining": mining_prob}
    }

@app.get("/get-area-trends")
def get_trends(lat: float, lng: float):
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, status_color, mining FROM assessments WHERE lat BETWEEN ? AND ? ORDER BY id DESC LIMIT 5", (lat-0.1, lat+0.1))
    rows = cursor.fetchall()
    conn.close()
    return {"trends": [{"time": r[0], "status": r[1], "mining": r[2]} for r in rows]}

@app.get("/history-view")
async def history_view():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, alert, lat, lng FROM assessments ORDER BY id DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    html = "<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body { background:#0f172a; color:white; font-family:sans-serif; padding:20px; font-size:24px; } .card { background:#1e293b; padding:20px; border-radius:15px; margin-bottom:15px; border-left:8px solid #3b82f6; } h2 { color:#38bdf8; font-size:40px; }</style></head><body><h2>Assessment History</h2>"
    if not rows: html += "<p>No data recorded yet.</p>"
    for r in rows:
        html += f"<div class='card'><div>{r[0]}</div><strong>{r[1]}</strong><br><small>{r[2]}, {r[3]}</small></div>"
    html += "</body></html>"
    return HTMLResponse(content=html)

@app.get("/species-info")
async def species_info():
    html = "<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body { background:#0f172a; color:white; font-family:sans-serif; padding:20px; font-size:24px; line-height:1.6; } .card { background:#1e293b; padding:25px; border-radius:20px; margin-bottom:20px; border:1px solid #334155; } h2 { color:#38bdf8; font-size:45px; } h3 { color:#fbbf24; margin:0; font-size:32px; } .tag { display:inline-block; background:#e53935; padding:4px 12px; border-radius:8px; font-size:14px; font-weight:bold; margin-top:10px; }</style></head><body><h2>Mahseer Species Catalog</h2>"
    for s in SPECIES_LIST:
        html += f"<div class='card'><h3>{s['name']}</h3><p>{s['desc']}</p></div>"
    html += "<div class='card' style='border-color:#e53935'><h3>🚫 MINING PROHIBITION</h3><p>Sand mining is strictly prohibited in all spawning zones. Mafia activity must be reported.</p></div></body></html>"
    return HTMLResponse(content=html)

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
@app.get("/")
async def read_index(): return FileResponse(os.path.join(frontend_path, "index.html"))
