#!/usr/bin/env python3
"""
RSU 5G Forwarder — Conecta2030 (IPv6 Dual-Stack)
Proxy no lado da infraestrutura. Recebe JSON V2X do CARLA via UDP,
codifica em ASN.1 UPER (SAE J2735) e encaminha via UDP para o OBU
pela rede 5G (slice V2X, SST=2).

Dual-Stack: Aceita IPv4 (via mapped ::ffff:x.x.x.x) e IPv6 nativo.
Subnet IPv6 V2X: fd00:5678::/64 (ULA)
Subnet IPv4 V2X: 192.168.200.0/24 (legado)

Uso:
    python3 rsu_5g_forwarder.py --obu-ip fd00:5678::2 [--listen-port 9090]
    python3 rsu_5g_forwarder.py --obu-ip 192.168.200.2 [--listen-port 9090]  # legado IPv4

Arquitetura:
    [CARLA UDPSender] --UDP:9090 JSON--> [Este Forwarder] --UDP:9090 UPER--> [OBU 5G Receiver]
       (PC Windows)                       (host Docker)                       (UE fd00:5678::2)
"""

import socket
import json
import argparse
import signal
import sys
import time
import ipaddress
from datetime import datetime

# Importar codec UPER J2735
import j2735_codec

DEFAULT_LISTEN_PORT = 9090
DEFAULT_OBU_PORT = 9090
BUFFER_SIZE = 65535

CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
MAGENTA = "\033[95m"
RESET   = "\033[0m"

def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="RSU 5G Forwarder — Conecta2030")
    parser.add_argument("--obu-ip", required=True,
                        help="IP do OBU na slice V2X 5G (ex: fd00:5678::2 ou 192.168.200.2)")
    parser.add_argument("--obu-port", type=int, default=DEFAULT_OBU_PORT,
                        help=f"Porta UDP destino no OBU (default: {DEFAULT_OBU_PORT})")
    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT,
                        help=f"Porta UDP local para receber do CARLA (default: {DEFAULT_LISTEN_PORT})")
    parser.add_argument("--listen-ip", default="::",
                        help="IP para bind dual-stack (default: :: = IPv4+IPv6)")
    parser.add_argument("--no-uper", action="store_true",
                        help="Desabilitar encoding UPER, enviar JSON puro")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    use_uper = j2735_codec.is_available() and not args.no_uper

    # Normalizar OBU IP — se for IPv4, mapear para IPv6-mapped
    try:
        obu_addr = ipaddress.ip_address(args.obu_ip)
        if isinstance(obu_addr, ipaddress.IPv4Address):
            obu_ip_str = f"::ffff:{args.obu_ip}"
            log(f"[INFO] OBU IPv4 {args.obu_ip} → mapeado para {obu_ip_str}", YELLOW)
        else:
            obu_ip_str = str(obu_addr)
    except ValueError:
        obu_ip_str = args.obu_ip  # hostname, deixar resolver

    log("=" * 60, MAGENTA)
    log("  RSU 5G Forwarder — Conecta2030 (IPv6 Dual-Stack)", MAGENTA)
    log("  CARLA V2X → 5G Slice (SST=2, DNN=v2x)", MAGENTA)
    log("=" * 60, MAGENTA)
    log(f"  Escuta UDP:    [{args.listen_ip}]:{args.listen_port}  (← CARLA)", CYAN)
    log(f"  OBU 5G UDP:    [{obu_ip_str}]:{args.obu_port}       (→ via 5G)", CYAN)
    log(f"  Encoding:      {'ASN.1 UPER (J2735)' if use_uper else 'JSON puro (passthrough)'}", CYAN)
    log(f"  Stack:         AF_INET6 dual-stack (IPV6_V6ONLY=0)", CYAN)
    log("=" * 60, MAGENTA)

    # Sockets — AF_INET6 dual-stack
    recv_sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    recv_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind((args.listen_ip, args.listen_port))
    recv_sock.settimeout(2.0)

    send_sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    send_sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)

    msg_count = 0
    uper_count = 0
    json_count = 0
    stats = {}

    log(f"[5G-FWD] Aguardando mensagens V2X do CARLA...", CYAN)

    try:
        while True:
            try:
                data, addr = recv_sock.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue

            msg_count += 1
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            try:
                text = data.decode('utf-8').strip()
                for line in text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue

                    msg = json.loads(line)

                    # Detectar tipo
                    msg_type = "?"
                    for key in ["bsm", "psm", "tim", "mapData", "spat", "rsa"]:
                        if key in msg:
                            msg_type = key
                            stats[key] = stats.get(key, 0) + 1
                            break

                    if use_uper:
                        # Codificar em UPER
                        uper_bytes, _ = j2735_codec.json_to_uper(msg)
                        if uper_bytes:
                            wire = j2735_codec.pack_for_wire(
                                uper_bytes,
                                j2735_codec.MSG_TYPE_TO_ID.get(msg_type, 0)
                            )
                            send_sock.sendto(wire, (obu_ip_str, args.obu_port))
                            uper_count += 1
                            log(f"[{ts}] ✓ #{msg_count} {msg_type:>7} "
                                f"UPER({len(uper_bytes)}B) → {args.obu_ip}", GREEN)
                        else:
                            # Fallback: enviar JSON se UPER falhar
                            send_sock.sendto(data, (obu_ip_str, args.obu_port))
                            json_count += 1
                            log(f"[{ts}] ⚠ #{msg_count} {msg_type:>7} "
                                f"UPER falhou, enviando JSON ({len(data)}B)", YELLOW)
                    else:
                        # Modo passthrough JSON
                        send_sock.sendto(data, (obu_ip_str, args.obu_port))
                        json_count += 1
                        log(f"[{ts}] ✓ #{msg_count} {msg_type:>7} "
                            f"JSON({len(data)}B) → {args.obu_ip}", GREEN)

            except UnicodeDecodeError:
                # O Forwarder e o Receiver usam a mesma porta (9090) com SO_REUSEADDR na mesma máquina no test_5g.
                # Portanto o Forwarder capta os pacotes UPER binários que ele mesmo enviou! Ignoramos de forma limpa.
                continue
            except json.JSONDecodeError:
                log(f"[{ts}] ✗ #{msg_count} JSON inválido", RED)
            except Exception as e:
                log(f"[{ts}] ✗ #{msg_count} Erro: {e}", RED)

            # Stats periódico
            if msg_count % 50 == 0:
                parts = [f"{k}:{v}" for k, v in sorted(stats.items())]
                log(f"[STATS] Total: {msg_count} | UPER: {uper_count} | JSON: {json_count} | {' '.join(parts)}", CYAN)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        log(f"\n[INFO] Total: {msg_count} | UPER: {uper_count} | JSON fallback: {json_count}", YELLOW)
        recv_sock.close()
        send_sock.close()


if __name__ == "__main__":
    main()
