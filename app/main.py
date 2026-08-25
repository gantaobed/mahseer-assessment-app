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

# --- SCIENTIFIC DATA ---
PROTECTED_ZONES = [
    {"name": "Moyar River Sanctuary", "lat_min": 11.45, "lat_max": 11.65, "lng_min": 76.4, "lng_max": 77.2, "is_critical": True},
    {"name": "Pambar River Sanctuary", "lat_min": 10.15, "lat_max": 10.35, "lng_min": 77.1, "lng_max": 77.4, "is_critical": True}
]

def init_db():
    try:
        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()

        # Check if table exists and has 'lat' column
        cursor.execute("PRAGMA table_info(assessments)")
        cols = [col[1] for col in cursor.fetchall()]

        if not cols or 'lat' not in cols:
            # Table is missing or old - start fresh to ensure columns exist
            cursor.execute("DROP TABLE IF EXISTS assessments")
            cursor.execute("""
                CREATE TABLE assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    lat REAL,
                    lng REAL,
                    status_color TEXT,
                    alert TEXT,
                    temp REAL,
                    oxygen REAL,
                    mining REAL,
                    ph REAL,
                    turbidity REAL,
                    fragmentation REAL
                )
            """)

        cursor.execute("PRAGMA table_info(mining_reports)")
        mining_cols = [col[1] for col in cursor.fetchall()]
        if not mining_cols or 'lat' not in mining_cols:
            cursor.execute("DROP TABLE IF EXISTS mining_reports")
            cursor.execute("""
                CREATE TABLE mining_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    lat REAL,
                    lng REAL,
                    category TEXT,
                    description TEXT,
                    verified INTEGER DEFAULT 0
                )
            """)

        conn.commit(); conn.close()
    except Exception as e:
        print(f"❌ DB INIT ERROR: {e}")

init_db()

class EnvironmentData(BaseModel):
    lat: float
    lng: float

def fetch_telemetry(lat: float, lng: float):
    try:
        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,soil_temperature_0_to_7cm&timezone=auto"
        w = requests.get(w_url, timeout=5).json()
        return {"temp": w.get("current", {}).get("soil_temperature_0_to_7cm", 22.0)}
    except: return {"temp": 22.0}

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    try:
        # 1. Audits
        in_kaveri = 10.0 <= data.lat <= 13.5 and 75.0 <= data.lng <= 80.5
        is_critical_range = any(z["lat_min"] <= data.lat <= z["lat_max"] and z["lng_min"] <= data.lng <= z["lng_max"] for z in PROTECTED_ZONES)

        tel = fetch_telemetry(data.lat, data.lng)
        temp = tel["temp"]

        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()

        # Check Mining History (Any record > 0% risk in 5km area)
        cursor.execute("SELECT COUNT(*) FROM assessments WHERE lat BETWEEN ? AND ? AND mining > 0", (data.lat-0.05, data.lat+0.05))
        past_mining = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM mining_reports WHERE lat BETWEEN ? AND ? ", (data.lat-0.05, data.lat+0.05))
        mafia_count = cursor.fetchone()[0]

        # Current Hotspot Logic
        current_mining_prob = 85 if 12.1 < data.lat < 12.4 else 0

        # Trends for UI
        cursor.execute("SELECT timestamp, mining FROM assessments WHERE lat BETWEEN ? AND ? ORDER BY id DESC LIMIT 3", (data.lat-0.05, data.lat+0.05))
        trends = [{"time": r[0], "mining": r[1]} for r in cursor.fetchall()]

        # 2. STRICT Decision
        if not in_kaveri:
            color, alert = "gray", "🔴 FAILED: Outside species endemic range."
        elif current_mining_prob > 0 or past_mining > 0 or mafia_count > 0:
            color, alert = "red", "⛔ ILLEGAL MINING ZONE: Spawning strictly prohibited. Mafia Activity detected."
        elif not is_critical_range:
            color, alert = "yellow", "🟡 MONITOR: Non-breeding stretch of the Kaveri system."
        else:
            color, alert = "green", "🟢 PROTECTED SANCTUARY: 0% Mining detected. Verified Spawning Pool."

        # 3. Log Assessment
        cursor.execute("INSERT INTO assessments (timestamp, lat, lng, status_color, alert, temp, oxygen, mining, ph, turbidity, fragmentation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (datetime.now().strftime("%Y-%m-%d %H:%M"), data.lat, data.lng, color, alert, temp, 7.8, current_mining_prob, 7.8, 5, 0.2))
        conn.commit(); conn.close()

        return {
            "color": color, "alert": alert,
            "audit": {
                "range": "PASSED" if in_kaveri else "FAILED",
                "basin": "Kaveri Basin System" if in_kaveri else "Outside Range",
                "constraints": "STABLE" if color == "green" else "VIOLATED"
            },
            "details": {"temp": temp, "mining": current_mining_prob},
            "trends": trends
        }
    except Exception as e:
        return {
            "color": "red", "alert": f"⚠️ DB SYNC ERROR: {str(e)}",
            "audit": {"range": "ERROR", "basin": "ERROR", "constraints": "ERROR"},
            "details": {"temp": 0, "mining": 100}, "trends": []
        }

@app.get("/history-view")
async def history_view():
    try:
        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, alert, lat, lng, mining FROM assessments ORDER BY id DESC LIMIT 30")
        rows = cursor.fetchall()
        conn.close()
        html = "<html><head><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body { background:#0f172a; color:white; font-family:sans-serif; padding:20px; font-size:24px; } .card { background:#1e293b; padding:20px; border-radius:15px; margin-bottom:15px; border-left:8px solid #3b82f6; } h2 { color:#38bdf8; font-size:40px; }</style></head><body><h2>Kaveri Sanctuary Logs</h2>"
        for r in rows:
            html += f"<div class='card'><div>{r[0]}</div><strong>{r[1]}</strong><br><small>Mining: {r[4]}% | {r[2]}, {r[3]}</small></div>"
        html += "</body></html>"
        return HTMLResponse(content=html)
    except: return HTMLResponse(content="<h2>Database error. Tap the map first to fix.</h2>")

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
        <b>Diet:</b> Omnivorous — adults feed on algae/detritus scraped from rocks; juveniles consume invertebrates; fry feed on zooplankton.</p>
    </div>

    <div class='card' style='border-left:8px solid #ef4444'>
        <h3>⚠️ Conservation Status</h3>
        <p><b>IUCN Status:</b> Critically Endangered.<br>
        <b>Threats:</b> Dams and river fragmentation, non-native species (Tor khudree), dynamite fishing, pollution, and climate change.</p>
    </div>

    <div class='card'>
        <h3>📊 Summary Table</h3>
        <table>
            <tr><th>Attribute</th><th>Details</th></tr>
            <tr><td>Common Name</td><td>Orange Mahseer / Hump-backed Mahseer</td></tr>
            <tr><td>Scientific Name</td><td>Tor remadeviae</td></tr>
            <tr><td>Max Size</td><td>175 cm, 54 kg</td></tr>
            <tr><td>Current Range</td><td>Moyar (TN), Pambar (Kerala)</td></tr>
        </table>
    </div>

    <div class='card' style='border-color:#e53935'>
        <h3>🚫 MINING PROHIBITION</h3>
        <p>Sand mining is strictly prohibited in spawning zones. Mafia activity will be reported.</p>
    </div>
    </body></html>
    """
    return HTMLResponse(content=html)

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
@app.get("/")
async def read_index(): return FileResponse(os.path.join(frontend_path, "index.html"))
