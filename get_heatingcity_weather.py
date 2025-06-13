#!/usr/bin/env python3
import os
import sys
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# Fetch heat district subjects, extract internalId, externalId & coords
def fetch_heat_districts():
    project_id       = os.environ['PROJECT_ID']
    subject_type_ids = os.environ['SUBJECT_TYPE_IDS']
    api_key          = os.environ['BLOCKBAX_API_KEY']
    if not all([project_id, subject_type_ids, api_key]):
        print("Error: PROJECT_ID, SUBJECT_TYPE_IDS, and BLOCKBAX_API_KEY must be set.")
        sys.exit(1)

    url     = f"https://api.blockbax.com/v1/projects/{project_id}/subjects"
    headers = {'Authorization': f"ApiKey {api_key}", 'Accept': 'application/json'}
    params  = {'subjectTypeIds': subject_type_ids}
    resp    = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()

    raw = resp.json().get('result', resp.json().get('data', []))
    districts = []
    for item in raw:
        internal_id = item['id']
        ext_id      = item['externalId']
        props       = item.get('properties', [])
        loc_prop    = next((p for p in props if 'location' in p), None)
        if not loc_prop:
            continue
        loc = loc_prop['location']
        lat, lon = loc.get('lat'), loc.get('lon')
        if lat is None or lon is None:
            continue
        districts.append({'internal_id': internal_id, 'subject_id': ext_id, 'lat': lat, 'lon': lon})
    return districts

# Fetch current weather for given lat/lon (128x128 icon)
def fetch_weather(lat, lon, api_key):
    url    = "http://api.weatherapi.com/v1/current.json"
    params = {'key': api_key, 'q': f"{lat},{lon}", 'aqi': 'no'}
    resp   = requests.get(url, params=params)
    resp.raise_for_status()

    c = resp.json()['current']
    icon_path = c['condition']['icon'].replace('/64x64/', '/128x128/')
    return {
        'temp_c':    c['temp_c'],
        'humidity':  c['humidity'],
        'cloud_pct': c['cloud'],
        'precip_mm': c['precip_mm'],
        'condition': c['condition']['text'],
        'icon_url':  'https:' + icon_path
    }

# Main: gather data, send measurements, and patch icons
if __name__ == '__main__':
    weather_api_key  = os.environ.get('WEATHERAPI_KEY')
    post_url         = os.environ.get('MEASUREMENTS_POST_URL')
    blockbax_key     = os.environ.get('BLOCKBAX_API_KEY')
    property_type_id = os.environ.get('PROPERTY_TYPE_ID')
    project_id       = os.environ.get('PROJECT_ID')
    if not all([weather_api_key, post_url, blockbax_key, property_type_id, project_id]):
        print("Error: Required environment variables are not all set.")
        sys.exit(1)

    tz        = os.environ.get('TZ', 'Europe/Amsterdam')
    timestamp = datetime.now(ZoneInfo(tz)).isoformat()

    # 1) Fetch districts
    districts = fetch_heat_districts()

    # 2) Build & send measurements payload
    measurements = []
    for d in districts:
        w = fetch_weather(d['lat'], d['lon'], weather_api_key)
        entry = {'subject_id': d['subject_id']}
        for key in ['temp_c', 'humidity', 'cloud_pct', 'precip_mm', 'condition']:
            entry[key] = w[key]
        measurements.append(entry)

    payload = {'timestamp': timestamp, 'measurements': measurements}
    headers = {'Content-Type': 'application/json', 'Authorization': f"ApiKey {blockbax_key}"}
    resp = requests.post(post_url, json=payload, headers=headers)
    print(f"Measurements POST → {resp.status_code}")

    # 3) PATCH icon_url per subject
    for d in districts:
        w = fetch_weather(d['lat'], d['lon'], weather_api_key)
        icon      = w['icon_url']
        patch_url = f"https://api.blockbax.com/v1/projects/{project_id}/subjects/{d['internal_id']}/properties"
        patch_payload = {'values': {property_type_id: {'text': icon}}}
        patch_resp    = requests.patch(patch_url, json=patch_payload, headers=headers)
        print(f"PATCH {d['subject_id']} → {patch_resp.status_code}")
