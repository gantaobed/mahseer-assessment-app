from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import requests
import sqlite3
import os
from datetime import datetime

app = FastAPI(title="Cauvery Sentinel")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure database exists
def init_db():
    conn = sqlite3.connect("habitat_history.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL, status_color TEXT, alert TEXT)")
    conn.commit()
    conn.close()

init_db()

class EnvironmentData(BaseModel):
    lat: float
    lng: float

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    # Quick scientific check for Cauvery region
    in_cauvery = 10.0 <= data.lat <= 13.5 and 75.0 <= data.lng <= 80.5
    if not in_cauvery:
        return {"color": "gray", "alert": "⚠️ OUTSIDE RANGE: Species not native to this coordinate."}

    # Simple logic for stability
    color, alert = "green", "🟢 SANCTUARY: Stable habitat detected."
    if data.lat > 12.1 and data.lat < 12.3: # Mining area simulation
        color, alert = "red", "🔴 RESTRICTED: Active mining threat detected."

    return {"color": color, "alert": alert, "live": {"temp": 22.5, "do": 7.8, "mining": 5}}

@app.get("/history-view")
async def history_view():
    return HTMLResponse(content="<html><body style='background:#0f172a; color:white; padding:20px; font-family:sans-serif;'><h2>Cauvery Sentinel Logs</h2><p>No recent reports in this region.</p></body></html>")

@app.get("/species-info")
async def species_info():
    return HTMLResponse(content="<html><body style='background:#0f172a; color:white; padding:20px; font-family:sans-serif;'><h2>Orange-finned Mahseer</h2><p>The endemic 'Tiger of the Cauvery'. Needs rocky pools and clean water.</p></body></html>")

# Serve the map
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(frontend_path, "index.html"))
