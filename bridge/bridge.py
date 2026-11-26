import hmac
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

base = Path.home() / '.local/state/agents/inkwell-demo'
ha_token = (base / 'ha-token').read_text().strip()
ink_token = (base / 'inkwell-token').read_text().strip()
entities = [
    ('Last vessel', 'sensor.ais_vessel_tracker_home_last_passing_vessel', ''),
    ('Vessels today', 'sensor.ais_vessel_tracker_home_vessels_today', ''),
    ('Home', 'sensor.home_temperature_filtered', '°C'),
    ('Living room', 'sensor.living_room_temperature_filtered', '°C'),
    ('Office', 'sensor.office_temperature_filtered', '°C'),
    ('Bedroom', 'sensor.bedroom_temperature_filtered', '°C'),
    ('Outside', 'sensor.outdoor_temperature_filtered', '°C'),
    ('Power', 'sensor.total_power_consumption', 'W'),
]

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/kindle', '/photo') or not hmac.compare_digest(self.headers.get('X-Inkwell-Token', ''), ink_token):
            self.send_error(403)
            return
        try:
            request = Request('http://10.5.1.1:8123/api/states', headers={'Authorization': 'Bearer ' + ha_token})
            with urlopen(request, timeout=10) as response:
                states = {item['entity_id']: item['state'] for item in json.load(response)}
            vessel_request = Request('http://10.5.1.1:8123/api/states/sensor.ais_vessel_tracker_home_last_passing_vessel', headers={'Authorization': 'Bearer ' + ha_token})
            with urlopen(vessel_request, timeout=10) as response:
                vessel = json.load(response)
            if self.path == '/photo':
                if self.headers.get('X-Inkwell-MMSI', '') != str(vessel['attributes'].get('mmsi', '')):
                    self.send_error(409)
                    return
                path = vessel['attributes'].get('picture_url', '')
                if not path.startswith('/api/ais_vessel_tracker/photo/'):
                    self.send_error(404)
                    return
                request = Request('http://10.5.1.1:8123' + path, headers={'Authorization': 'Bearer ' + ha_token})
                with urlopen(request, timeout=15) as response:
                    photo = response.read(10000000)
                body = subprocess.run(['magick', '-', '-auto-orient', '-resize', '520x300^', '-gravity', 'center', '-extent', '520x300', '-colorspace', 'gray', '-depth', '8', 'gray:-'], input=photo, capture_output=True, check=True, timeout=20).stdout
                if len(body) != 520 * 300:
                    raise ValueError('invalid photo size')
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            lines = []
            for label, entity, unit in entities:
                value = states.get(entity, 'unavailable')
                try:
                    if not unit:
                        raise ValueError
                    value = f'{float(value):.0f}' if unit == 'W' else f'{float(value):.1f}'
                    value += ' ' + unit
                except ValueError:
                    if unit:
                        value = 'unavailable'
                lines.append({'label': label, 'value': value})
            author = vessel['attributes'].get('photo_author', '')
            if author:
                lines.append({'label': 'Photo', 'value': author})
            body = json.dumps({'title': 'Home Assistant', 'lines': lines, 'buttons': [], 'mmsi': str(vessel['attributes'].get('mmsi', ''))}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_error(502, 'Home Assistant unavailable')

    def log_message(self, fmt, *args):
        pass

ThreadingHTTPServer(('10.5.0.14', 18765), Handler).serve_forever()
