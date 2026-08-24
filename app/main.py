from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import requests

app = FastAPI(title="Mahseer Habitat Assessment")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class EnvironmentData(BaseModel):
    zone_id: int
    zone_name: str
    lat: float
    lng: float
    flow_velocity_ms: float
    substrate_weight: float
    do_mg_l: float
    temp_c: float
    ph: float
    ammonia_mg_l: float
    sand_mining_present: bool
    # Make rainfall optional; the engine will fetch it if missing
    rainfall_mm_day: Optional[float] = None 

def get_live_rainfall(lat: float, lng: float) -> float:
    """Fetches real-time daily precipitation from Open-Meteo."""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&daily=precipitation_sum&timezone=auto"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        # Extract today's forecasted rainfall in mm
        todays_rain = data["daily"]["precipitation_sum"][0]
        return todays_rain if todays_rain is not None else 0.0
    except Exception as e:
        print(f"Weather API Error: {e}")
        return 0.0 # Default failsafe

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    # 1. Fetch Live Weather if not provided
    if data.rainfall_mm_day is None:
        data.rainfall_mm_day = get_live_rainfall(data.lat, data.lng)

    # 2. Chemical & Physical Vetoes
    if data.do_mg_l < 5.0 or data.temp_c > 28.0 or data.ph < 6.5 or data.ammonia_mg_l > 0.05:
        return {"color": "red", "alert": "CRITICAL: Chemical parameters toxic."}
    if data.sand_mining_present:
        return {"color": "red", "alert": "CRITICAL: Active mining detected."}
    if data.flow_velocity_ms < 0.4 or data.flow_velocity_ms > 2.2:
        return {"color": "red", "alert": "CRITICAL: Lethal flow velocity."}

    # 3. Physical Scoring
    base = 3 if 0.8 <= data.flow_velocity_ms <= 1.5 else 1
    score = base * data.substrate_weight

    # 4. Rainfall Overlap
    weather_alert = f"(Live Rain: {data.rainfall_mm_day}mm)"
    if data.rainfall_mm_day > 50.0:
        return {"color": "red", "alert": f"CRITICAL: Extreme rain flash flood risk {weather_alert}."}
    elif data.rainfall_mm_day > 20.0:
        score -= 2
        weather_alert = f"Warning: Heavy rain {weather_alert}."
    else:
        weather_alert = f"Normal Weather {weather_alert}."

    # 5. Final Output
    color = "green" if score >= 2.5 else "yellow" if score > 0 else "red"
    return {"color": color, "alert": f"Status: {color.upper()} | {weather_alert}"}