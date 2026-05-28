#!/usr/bin/env python3
"""
V2X Central Registry (Simple DDNS) — Conecta2030
Um servidor minimalista para mapear nomes (ex: obu-v2x) para IPs dinâmicos.
Sem dependências externas.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import threading
import time

# Banco de dados em arquivo
REGISTRY_FILE = "v2x_registry.json"
registry = {}
registry_lock = threading.Lock()

def load_registry():
    global registry
    try:
        with open(REGISTRY_FILE, 'r') as f:
            registry = json.load(f)
            print(f"[REGISTRY] Loaded {len(registry)} entries from {REGISTRY_FILE}")
    except (FileNotFoundError, json.JSONDecodeError):
        registry = {}

def save_registry():
    with registry_lock:
        with open(REGISTRY_FILE, 'w') as f:
            json.dump(registry, f, indent=2)

class RegistryHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == '/resolve':
            query = parse_qs(parsed_url.query)
            name = query.get('name', [None])[0]
            
            with registry_lock:
                entry = registry.get(name)
            
            if entry:
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(entry['ip'].encode())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
                
        elif parsed_url.path == '/list':
            with registry_lock:
                data = json.dumps(registry, indent=2)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(data.encode())
            
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"V2X Registry Active. Use /resolve?name=... or /list")

    def do_POST(self):
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == '/update':
            query = parse_qs(parsed_url.query)
            name = query.get('name', [None])[0]
            ip = query.get('ip', [None])[0]
            
            if name and ip:
                with registry_lock:
                    registry[name] = {
                        "ip": ip,
                        "last_seen": time.time(),
                        "time_str": time.strftime('%Y-%m-%d %H:%M:%S')
                    }
                print(f"[REGISTRY] Updated: {name} -> {ip}")
                save_registry()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing name or ip")
        else:
            self.send_response(404)
            self.end_headers()

def run_server(port=5000):
    load_registry()
    server_address = ('', port)
    httpd = HTTPServer(server_address, RegistryHandler)
    print(f"[REGISTRY] Servidor rodando na porta {port}...")
    print(f"[REGISTRY] Ex: http://localhost:{port}/update?name=obu-v2x&ip=fd00:5678::2")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
