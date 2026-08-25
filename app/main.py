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

app = FastAPI(title="Cauvery Spawning & Mining Sentinel")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CAUVERY BASIN SCIENTIFIC BOUNDARIES ---
CAUVERY_CONSTRAINTS = {
    "lat_min": 10.0, "lat_max": 13.5,
    "lng_min": 75.0, "lng_max": 80.5,
    "tributaries": ["Moyar", "Kabini", "Bhavani", "Pambar", "Arkavathi", "Hemavati", "Shimsha"]
}

MINING_HOTSPOTS = [
    {"lat": 12.19, "lng": 76.90, "risk": 0.9, "name": "T. Narasipura Stretch"},
    {"lat": 12.27, "lng": 77.44, "risk": 0.8, "name": "Sangama Confluence"},
    {"lat": 11.50, "lng": 77.50, "risk": 0.85, "name": "Bhavani Silt Zone"},
    {"lat": 11.35, "lng": 76.95, "risk": 0.70, "name": "Moyar Valley Mining"}
]

def init_db():
    try:
        conn = sqlite3.connect("habitat_history.db")
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL, status_color TEXT, audit_log TEXT)")
        conn.commit(); conn.close()
    except Exception as e: print(f"❌ DB ERROR: {e}")

init_db()

class EnvironmentData(BaseModel):
    lat: float
    lng: float

def get_mining_risk(lat, lng):
    max_risk = 0.02
    for spot in MINING_HOTSPOTS:
        dist = ((lat - spot["lat"])**2 + (lng - spot["lng"])**2)**0.5
        if dist < 0.2: # Silt drift radius ~20km
            max_risk = max(max_risk, spot["risk"] * (1 - dist/0.2))
    return round(max_risk, 2)

def get_closest_tributary(lat, lng):
    # This simulates a spatial join to the river system
    if lat > 12.5: return "Hemavati/Shimsha System"
    if lat < 11.0: return "Pambar/Southern Basin"
    if lng < 76.5: return "Kabini/Moyar High Range"
    if lng > 78.5: return "Lower Cauvery/Puducherry System"
    return "Main Stem Cauvery / Bhavani"

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    # 1. GEOGRAPHIC LOCKDOWN (STRICT)
    in_cauvery = CAUVERY_CONSTRAINTS["lat_min"] <= data.lat <= CAUVERY_CONSTRAINTS["lat_max"] and \
                 CAUVERY_CONSTRAINTS["lng_min"] <= data.lng <= CAUVERY_CONSTRAINTS["lng_max"]

    tributary = get_closest_tributary(data.lat, data.lng)

    audit = {
        "range_valid": in_cauvery,
        "basin_name": tributary if in_cauvery else "INVALID: Non-Cauvery Domain",
        "mining_constraint": "Stable" if get_mining_risk(data.lat, data.lng) < 0.25 else "CRITICAL SILTATION",
        "fish_presence": "Orange-finned Mahseer Native" if in_cauvery else "Species absent in this region"
    }

    if not in_cauvery:
        return {
            "color": "gray",
            "alert": "⚠️ DOMAIN ERROR: You are outside the Cauvery River System. The Sentinel is restricted to the protection of Orange-finned Mahseer habitat in Karnataka, TN, Kerala, and Puducherry.",
            "audit": audit,
            "live": {}
        }

    # 2. HYDRO-BIOLOGICAL TELEMETRY
    try:
        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={data.lat}&longitude={data.lng}&current=temperature_2m,soil_temperature_0_to_7cm&daily=precipitation_sum&timezone=auto"
        w = requests.get(w_url, timeout=5).json()
        temp = w.get("current", {}).get("soil_temperature_0_to_7cm", 22.0)
        rain = w.get("daily", {}).get("precipitation_sum", [0.0])[0]

        mining_risk = get_mining_risk(data.lat, data.lng)

        # SCIENTIFIC THRESHOLDS
        if mining_risk > 0.65:
            color, alert = "red", f"🔴 RESTRICTED: Severe mining risk in {tributary}. Spawning beds suffocated by silt."
        elif 19.5 <= temp <= 25.5 and rain < 25:
            color, alert = "green", f"🟢 SANCTUARY: Ideal conditions in {tributary} for the Orange-finned Mahseer."
        else:
            color, alert = "yellow", f"🟡 MONITOR: Suboptimal spawning window in {tributary} due to climate factors."

        return {"color": color, "alert": alert, "audit": audit, "live": {"temp": temp, "rain": rain, "mining": int(mining_risk*100)}}
    except:
        return {"color": "red", "alert": "⚠️ TELEMETRY ERROR: Satellite link interrupted."}

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
@app.get("/")
async def read_index(): return FileResponse(os.path.join(frontend_path, "index.html"))
