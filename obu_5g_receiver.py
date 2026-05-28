#!/usr/bin/env python3
"""
OBU 5G Receiver — Conecta2030 (IPv6 Dual-Stack)
Roda ao lado do obu_alert_server.c existente (C-V2X/DSRC).
Recebe mensagens V2X via UDP na interface 5G (uesimtun),
decodifica de ASN.1 UPER para JSON (SAE J2735),
e faz broadcast para tablets conectados via TCP.

Dual-Stack: Aceita IPv4 (via mapped ::ffff:x.x.x.x) e IPv6 nativo.
Subnet IPv6 V2X: fd00:5678::/64 (ULA)
Usa porta TCP 8081 para não conflitar com o OBU C-V2X (8080).

Uso:
    python3 obu_5g_receiver.py [--v2x-port 9090] [--tablet-port 8081]

Arquitetura:
    [RSU 5G Forwarder] --UDP:9090 UPER--> [Este Receiver] --TCP:8081 JSON--> [Tablet]
                        via 5G core (fd00:5678::/64)        via rede local
"

import socket
import json
import threading
import argparse
import signal
import sys
import time
from datetime import datetime

# Importar codec UPER J2735
import j2735_codec

DEFAULT_V2X_PORT = 9090
DEFAULT_TABLET_PORT = 8081
MAX_CLIENTS = 10
BUFFER_SIZE = 65535

CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
MAGENTA = "\033[95m"
RESET   = "\033[0m"

def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}", flush=True)


class TabletManager:
    """Gerencia conexões TCP com tablets."""

    def __init__(self, port):
        self.port = port
        self.server_fd = None
        self.clients = {}
        self.lock = threading.Lock()
        self.running = True

    def start(self):
        self.server_fd = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        self.server_fd.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        self.server_fd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_fd.bind(("::", self.port))
        self.server_fd.listen(MAX_CLIENTS)
        self.server_fd.settimeout(1.0)
        log(f"[TABLET] TCP Server na porta {self.port} aguardando tablets...", CYAN)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.running:
            try:
                sock, addr = self.server_fd.accept()
                with self.lock:
                    self.clients[sock.fileno()] = (sock, addr)
                    log(f"[TABLET] Conectou: {addr[0]}:{addr[1]} (total: {len(self.clients)})", GREEN)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    log(f"[TABLET] Erro accept: {e}", RED)
                break

    def broadcast(self, data):
        if not self.clients:
            return 0
        message = data if isinstance(data, bytes) else data.encode('utf-8')
        if not message.endswith(b'\n'):
            message += b'\n'
        sent = 0
        dead = []
        with self.lock:
            for cid, (sock, addr) in self.clients.items():
                try:
                    sock.sendall(message)
                    sent += 1
                except:
                    dead.append(cid)
            for cid in dead:
                sock, addr = self.clients.pop(cid)
                log(f"[TABLET] Removido: {addr[0]}:{addr[1]}", YELLOW)
                try: sock.close()
                except: pass
        return sent

    @property
    def count(self):
        return len(self.clients)

    def close(self):
        self.running = False
        with self.lock:
            for _, (sock, _) in self.clients.items():
                try: sock.close()
                except: pass
            self.clients.clear()
        if self.server_fd:
            self.server_fd.close()


class FragmentBuffer:
    """Bufferiza BSM+PSM+TIM. Quando os 3 estão presentes, unifica."""

    def __init__(self):
        self.bsm = None
        self.psm = None
        self.tim = None

    def store(self, msg_type, data):
        if msg_type == "bsm":
            self.bsm = data
        elif msg_type == "psm":
            self.psm = data
        elif msg_type == "tim":
            self.tim = data
        else:
            return None

        if self.bsm and self.psm and self.tim:
            unified = {"bsm": self.bsm, "psm": self.psm, "tim": self.tim}
            self.bsm = self.psm = self.tim = None
            return unified
        return None

    @property
    def status(self):
        b = "✓" if self.bsm else "✗"
        p = "✓" if self.psm else "✗"
        t = "✓" if self.tim else "✗"
        return f"bsm={b} psm={p} tim={t}"


def main():
    parser = argparse.ArgumentParser(description="OBU 5G Receiver — Conecta2030")
    parser.add_argument("--v2x-port", type=int, default=DEFAULT_V2X_PORT,
                        help=f"Porta UDP para receber V2X via 5G (default: {DEFAULT_V2X_PORT})")
    parser.add_argument("--tablet-port", type=int, default=DEFAULT_TABLET_PORT,
                        help=f"Porta TCP para tablets (default: {DEFAULT_TABLET_PORT})")
    parser.add_argument("--v2x-ip", default="::",
                        help="IP para bind dual-stack do listener UDP (default: :: = IPv4+IPv6)")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    use_uper = j2735_codec.is_available()

    log("=" * 60, CYAN)
    log("  OBU 5G Receiver — Conecta2030 (IPv6 Dual-Stack)", CYAN)
    log("  Recebe V2X via 5G Slice (SST=2, fd00:5678::/64)", CYAN)
    log("=" * 60, CYAN)
    log(f"  V2X UDP:    [{args.v2x_ip}]:{args.v2x_port}", CYAN)
    log(f"  Tablet TCP: [::]:{args.tablet_port}", CYAN)
    log(f"  Decoding:   {'ASN.1 UPER (J2735)' if use_uper else 'JSON puro'}", CYAN)
    log(f"  Stack:      AF_INET6 dual-stack (IPV6_V6ONLY=0)", CYAN)
    log("=" * 60, CYAN)

    tablets = TabletManager(args.tablet_port)
    fragments = FragmentBuffer()
    msg_count = 0
    uper_count = 0
    json_count = 0

    # UDP socket — AF_INET6 dual-stack
    udp_sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sock.bind((args.v2x_ip, args.v2x_port))
    udp_sock.settimeout(2.0)

    log(f"[5G-V2X] Aguardando mensagens na porta UDP {args.v2x_port}...", MAGENTA)

    try:
        tablets.start()

        while True:
            try:
                data, addr = udp_sock.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue
            except Exception as e:
                log(f"[5G-V2X] Erro recv: {e}", RED)
                time.sleep(0.1)
                continue

            msg_count += 1
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            try:
                # Tentar decodar como UPER primeiro
                uper_bytes, wire_msg_id = j2735_codec.unpack_from_wire(data)

                if uper_bytes is not None and use_uper:
                    # ===== MODO UPER =====
                    json_dict, msg_type = j2735_codec.uper_to_json(uper_bytes)
                    uper_count += 1

                    if json_dict is None:
                        log(f"[{ts}] ✗ #{msg_count} UPER decode falhou (msg_id={wire_msg_id})", RED)
                        continue

                    log(f"[{ts}] ✓ #{msg_count} UPER→JSON '{msg_type}' "
                        f"de {addr[0]} ({len(uper_bytes)}B UPER)", GREEN)

                    msg = json_dict

                elif j2735_codec.is_json_wire(data):
                    # ===== MODO JSON FALLBACK =====
                    text = data.decode('utf-8').strip()
                    msg = json.loads(text.split('\n')[0])
                    msg_type = "unknown"
                    for key in ["bsm", "psm", "tim", "mapData", "spat", "rsa"]:
                        if key in msg:
                            msg_type = key
                            break
                    json_count += 1
                    log(f"[{ts}] ✓ #{msg_count} JSON '{msg_type}' "
                        f"de {addr[0]} ({len(data)}B)", GREEN)
                else:
                    log(f"[{ts}] ✗ #{msg_count} Formato desconhecido ({len(data)}B)", RED)
                    continue

                # Processar mensagem
                if msg_type in ("bsm", "psm", "tim"):
                    content = msg.get(msg_type, {}).get("value", msg.get(msg_type, msg))
                    unified = fragments.store(msg_type, content)
                    log(f"  Fragmento bufferizado ({fragments.status})", CYAN)

                    if unified:
                        payload = json.dumps(unified)
                        n = tablets.broadcast(payload)
                        log(f"  >>> 3 FRAGMENTOS! Broadcast → {n} tablet(s) ({len(payload)}B)", GREEN)
                else:
                    # MAP, SPAT, RSA → direto
                    payload = json.dumps(msg)
                    n = tablets.broadcast(payload)
                    if n > 0:
                        log(f"  '{msg_type}' → {n} tablet(s)", CYAN)

            except json.JSONDecodeError as e:
                log(f"[{ts}] ✗ JSON inválido: {e}", RED)
            except Exception as e:
                log(f"[{ts}] ✗ Erro: {e}", RED)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        log(f"\n[INFO] Total: {msg_count} | UPER: {uper_count} | JSON: {json_count}", YELLOW)
        udp_sock.close()
        tablets.close()


if __name__ == "__main__":
    main()
