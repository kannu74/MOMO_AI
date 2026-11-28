"""Weather from Open-Meteo (free, no API key).

Safety: the API returns only numbers and numeric weather codes. Codes are turned into
words with the local WMO table below, so no text from the internet reaches the LLM.
"""
import requests

import config

URL = "https://api.open-meteo.com/v1/forecast"

WMO = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


def get_weather(when: str = "now") -> dict:
    when = when if when in ("now", "today", "tomorrow") else "now"
    params = {
        "latitude": config.HOME_LAT, "longitude": config.HOME_LON, "timezone": config.HOME_TZ,
        "forecast_days": 2,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
    }
    r = requests.get(URL, params=params, timeout=8)
    r.raise_for_status()
    d = r.json()

    if when == "now":
        c = d["current"]
        return {"location": config.HOME_NAME, "when": "right now",
                "condition": WMO.get(int(c["weather_code"]), "unknown"),
                "temperature_c": round(float(c["temperature_2m"])),
                "feels_like_c": round(float(c["apparent_temperature"])),
                "humidity_pct": int(c["relative_humidity_2m"]),
                "wind_kmh": round(float(c["wind_speed_10m"])),
                "rain_mm_now": float(c["precipitation"])}
    i = 0 if when == "today" else 1
    day = d["daily"]
    return {"location": config.HOME_NAME, "when": when,
            "condition": WMO.get(int(day["weather_code"][i]), "unknown"),
            "high_c": round(float(day["temperature_2m_max"][i])),
            "low_c": round(float(day["temperature_2m_min"][i])),
            "rain_chance_pct": int(day["precipitation_probability_max"][i] or 0),
            "rain_mm": float(day["precipitation_sum"][i] or 0)}
