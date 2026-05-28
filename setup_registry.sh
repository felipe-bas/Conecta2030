#!/bin/bash
# setup_registry.sh — Conecta2030
# Executar no servidor central (10.147.17.110)

echo "[INFO] Iniciando setup do Registro V2X..."

# 1. Verificar se o Python 3 está instalado
if ! command -v python3 &> /dev/null; then
    echo "[ERRO] Python 3 não encontrado! Instalando..."
    sudo apt update && sudo apt install -y python3
fi

# 2. Criar o arquivo v2x_registry.py
cat << 'EOF' > v2x_registry.py
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

# Banco de dados em memória
registry = {}
registry_lock = threading.Lock()

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
    server_address = ('', port)
    httpd = HTTPServer(server_address, RegistryHandler)
    print(f"[REGISTRY] Servidor rodando na porta {port}...")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
EOF

# 3. Tornar executável
chmod +x v2x_registry.py

# 4. Iniciar em background
echo "[INFO] Iniciando o registro em background na porta 5000..."
nohup python3 v2x_registry.py > registry.log 2>&1 &

echo "[INFO] Registro iniciado com sucesso!"
echo "[INFO] Use 'tail -f registry.log' para monitorar."
echo "[INFO] Para parar: 'pkill -f v2x_registry.py'"
