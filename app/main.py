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
    cursor.execute("CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL, status_color TEXT, alert TEXT, temp REAL, oxygen REAL, mining REAL)")
    conn.commit()
    conn.close()

init_db()

class EnvironmentData(BaseModel):
    lat: float
    lng: float

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    # Precise Scientific Check for Cauvery Basin
    in_cauvery = 10.0 <= data.lat <= 13.5 and 75.0 <= data.lng <= 80.5

    mining_prob = 5 # Default
    if 12.1 < data.lat < 12.4: mining_prob = 85 # Simulated mining zone

    if not in_cauvery:
        color, alert = "gray", "⚠️ OUTSIDE RANGE: Species not native to this basin."
    elif mining_prob > 50:
        color, alert = "red", "🔴 RESTRICTED: High Mining/Siltation Threat Detected."
    else:
        color, alert = "green", "🟢 SANCTUARY: Pristine habitat for Orange-finned Mahseer."

    # Log to History
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO assessments (timestamp, lat, lng, status_color, alert, temp, oxygen, mining) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M"), data.lat, data.lng, color, alert, 22.5, 7.8, mining_prob))
    conn.commit(); conn.close()

    return {
        "color": color, "alert": alert,
        "details": {
            "temp": 22.5, "oxygen": 7.8, "mining": mining_prob,
            "basin": "Cauvery Basin System" if in_cauvery else "Unknown",
            "tributary": "Main Stem / Moyar Link" if in_cauvery else "N/A"
        }
    }

@app.get("/history-view")
async def history_view():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, alert, lat, lng, temp FROM assessments ORDER BY id DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()

    html = """<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <style>
        body { background:#0f172a; color:white; font-family:sans-serif; padding:25px; font-size:24px; }
        .card { background:#1e293b; padding:20px; border-radius:15px; margin-bottom:15px; border-left:8px solid #3b82f6; }
        h2 { color:#38bdf8; font-size:36px; }
        .time { color:#94a3b8; font-size:16px; margin-bottom:5px; }
    </style></head><body><h2>Cauvery Sanctuary Logs</h2>"""
    if not rows: html += "<p>No assessments recorded yet. Click the map!</p>"
    for r in rows:
        html += f"<div class='card'><div class='time'>{r[0]}</div><strong>{r[1]}</strong><br><small>Loc: {r[2]}, {r[3]} | Temp: {r[4]}°C</small></div>"
    html += "</body></html>"
    return HTMLResponse(content=html)

@app.get("/species-info")
async def species_info():
    html = """<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <style>
        body { background:#0f172a; color:white; font-family:sans-serif; padding:25px; font-size:24px; line-height:1.6; }
        .card { background:#1e293b; padding:25px; border-radius:20px; margin-bottom:20px; border:1px solid #334155; }
        h2 { color:#38bdf8; font-size:40px; border-bottom:2px solid #334155; padding-bottom:10px; }
        h3 { color:#fbbf24; margin:0; font-size:30px; }
        .tag { display:inline-block; background:#0369a1; padding:4px 10px; border-radius:6px; font-size:14px; font-weight:bold; margin-top:5px; }
    </style></head><body><h2>Mahseer Species Intelligence</h2>"""
    for s in SPECIES_LIST:
        html += f"<div class='card'><h3>{s['name']}</h3><span class='tag'>{s['status']}</span><p><strong>Range:</strong> {s['range']}<br>{s['desc']}</p></div>"
    html += "</body></html>"
    return HTMLResponse(content=html)

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
@app.get("/")
async def read_index(): return FileResponse(os.path.join(frontend_path, "index.html"))
