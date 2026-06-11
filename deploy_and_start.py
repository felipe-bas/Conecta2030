#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V2X Deploy System - Unificado (IPv4 / IPv6)
Compila código C para arquitetura ARM32 e envia para a OBU e RSU da Commsignia.
Suporta integração local (CARLA) e remota (DDNS para IPv6).
"""

import sys
import os
import time
import subprocess
import socket
import argparse
import threading
import platform
import paramiko
import requests
from dotenv import load_dotenv

# Carregar variáveis do .env
load_dotenv()

# ==========================================
# CONSTANTES VINDAS DO .ENV
# ==========================================
RSU_IPV4 = os.getenv("RSU_IPV4", "192.168.0.50")
RSU_USER = os.getenv("RSU_USER", "root")
RSU_PASS = os.getenv("RSU_PASS", "Conect@2024")

OBU_IPV4 = os.getenv("OBU_IPV4", "192.168.0.53")
OBU_USER = os.getenv("OBU_USER", "root")
OBU_PASS = os.getenv("OBU_PASS", "Conect@24")

CARLA_FIXED_IPV4 = os.getenv("CARLA_FIXED_IP", "192.168.0.56")
CARLA_FIXED_IPV6 = os.getenv("CARLA_FIXED_IPV6", "2804:214:8780:3d5::633")

DDNS_URL = os.getenv("DDNS_URL", "http://[2804:214:8780:3d5::633]:5000")
DDNS_RSU_NAME = os.getenv("DDNS_RSU_NAME", "rsu-v2x")

RSU_PORT = 8080
OBU_PORT = 8080

LOCAL_DIR = os.getcwd()

# Colors for terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"

# ==========================================
# UTILS
# ==========================================

def get_local_ip(target_ip=None):
    """
    Descobre o IP local. Se um IP de destino for fornecido (ex: RSU_IPV4),
    usa ele para descobrir qual placa de rede tem a rota direta.
    Caso contrário, usa o Google (8.8.8.8) como fallback genérico.
    """
    target = target_ip if target_ip else "8.8.8.8"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        # Fallback se a rede estiver fora ou não tiver rota
        return CARLA_FIXED_IPV4

def set_terminal_title(title):
    if platform.system().lower() == "windows":
        os.system(f"title {title}")
    else:
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()

def log(msg, color=RESET):
    try:
        print(f"{color}{msg}{RESET}")
    except UnicodeEncodeError:
        safe_msg = msg.encode('ascii', 'replace').decode('ascii')
        print(f"{color}{safe_msg}{RESET}")

def check_ping(ip):
    """Checks if the device is reachable via Ping."""
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    cmd_name = 'ping'
    if platform.system().lower() != 'windows' and ':' in ip:
        cmd_name = 'ping6'
        
    command = [cmd_name, param, '1', ip]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception:
        return False

# ==========================================
# DDNS (IPv6 Specific)
# ==========================================

def register_rsu_in_ddns(ssh_client):
    """Gets RSU IPv6 from wwan0 and registers it in the DDNS server."""
    try:
        log("  📡 Getting RSU IPv6 address...", CYAN)
        stdin, stdout, stderr = ssh_client.exec_command(
            "ip -6 addr show wwan0 scope global | grep inet6 | awk '{print $2}' | cut -d/ -f1 | head -1"
        )
        rsu_ipv6 = stdout.read().decode().strip()
        
        if not rsu_ipv6:
            log("  ⚠️ RSU has no global IPv6 on wwan0, trying wlan0...", YELLOW)
            stdin, stdout, stderr = ssh_client.exec_command(
                "ip -6 addr show wlan0 scope global | grep inet6 | awk '{print $2}' | cut -d/ -f1 | head -1"
            )
            rsu_ipv6 = stdout.read().decode().strip()
        
        if not rsu_ipv6:
            log("  ⚠️ No global IPv6 found on RSU. DDNS registration skipped.", YELLOW)
            return False
        
        log(f"  📡 RSU IPv6: {rsu_ipv6}", GREEN)
        
        # Register from deploy machine to CARLA DDNS directly
        import urllib.request
        url = f"{DDNS_URL}/update?name={DDNS_RSU_NAME}&ip={rsu_ipv6}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                result = response.read().decode().strip()
            
            if result == "OK":
                log(f"  ✅ RSU registered in DDNS: {DDNS_RSU_NAME} → {rsu_ipv6}", GREEN)
                return True
            else:
                log(f"  ❌ DDNS registration failed. Result: {result}", RED)
                return False
        except Exception as e:
            log(f"  ❌ Could not connect to DDNS ({DDNS_URL}): {e}", RED)
            return False
            
    except Exception as e:
        log(f"  ❌ Exception during DDNS registration: {e}", RED)
        return False

def get_rsu_ip_from_ddns():
    """Queries the DDNS server to get the dynamic IPv6 address of the RSU."""
    import urllib.request
    try:
        url = f"{DDNS_URL}/resolve?name={DDNS_RSU_NAME}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                ip = response.read().decode('utf-8').strip()
                if ip:
                    return ip
    except Exception as e:
        log(f"  ⚠️ Could not resolve RSU IP from DDNS ({DDNS_URL}): {e}", YELLOW)
    return None

# ==========================================
# COMPILAÇÃO E SSH
# ==========================================

def recompile_binaries(rsu_only=False):
    log("\n[1/4] Compiling source code for ARM32...", YELLOW)

    sdk_base = "commsignia-sdk/Unplugged-RT-y20.41.3-b214979-linuxm_obx_sdk-remote_c_sdk/Unplugged-RT-y20.41.3-b214979-linuxm_obx_sdk-remote_c_sdk"
    inc_path = f"{sdk_base}/include"
    lib_path = f"{sdk_base}/lib"
    flags = f"-static -s -I {inc_path} -I {inc_path}/asn1 -L {lib_path} -lits-asnsdk -lits-rem -lpthread -lrt -lstdc++ -lm"

    # 1. Compile RSU application (fac_alert) - always
    log("Compiling RSU App (fac_alert.c)...", CYAN)
    rsu_compile_cmd = (
        f'docker run --rm -v "{LOCAL_DIR}:/src" -w /src arm32-builder bash -c '
        f'"arm-linux-gnueabihf-gcc fac_alert.c -o fac_alert {flags}"'
    )
    res_rsu = os.system(rsu_compile_cmd)
    if res_rsu != 0:
        log("Compilation failed for RSU (fac_alert)!", RED)
        sys.exit(1)

    # 2. Compile OBU application (obu_alert_server) - skip if rsu_only
    if not rsu_only:
        log("Compiling OBU App (obu_alert_server.c)...", CYAN)
        obu_compile_cmd = (
            f'docker run --rm -v "{LOCAL_DIR}:/src" -w /src arm32-builder bash -c '
            f'"arm-linux-gnueabihf-gcc obu_alert_server.c -o obu_alert_server {flags}"'
        )
        res_obu = os.system(obu_compile_cmd)
        if res_obu != 0:
            log("Compilation failed for OBU (obu_alert_server)!", RED)
            sys.exit(1)

    log("Compilation successful!", GREEN)

def get_ssh_client(ip, user, password, retries=3):
    """Creates and returns a connected Paramiko SSH client with retries."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    for attempt in range(1, retries + 1):
        try:
            # Force legacy algorithms for older embedded devices
            client.connect(
                ip, 
                username=user, 
                password=password, 
                timeout=15,  # Increased timeout for flaky IPv6
                look_for_keys=False, 
                allow_agent=False,
                disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
                banner_timeout=60
            )
            return client
        except Exception as e:
            if attempt < retries:
                log(f"  ⚠️ SSH connection failed (Attempt {attempt}/{retries}): {e}. Retrying...", YELLOW)
                import time
                time.sleep(2)
            else:
                log(f"  ❌ SSH connection ultimately failed: {e}", RED)
                
    return None

def transfer_file_robust(client, local_path, remote_path):
    """
    Robust file transfer for unstable IPv6 cellular connections.
    Compresses the file locally using GZIP, transfers via Base64 stream,
    and decompresses remotely. This reduces size by ~4x, avoiding timeouts.
    """
    import gzip
    import base64
    import time
    
    filename = os.path.basename(local_path)
    # Ensure unix paths and add filename if remote_path is a directory
    if not remote_path.endswith('/' + filename):
        full_remote = remote_path + "/" + filename
    else:
        full_remote = remote_path
        
    gz_remote = full_remote + ".gz"
    
    # 0. Kill existing instances
    client.exec_command(f"killall -9 {filename} >/dev/null 2>&1")
    client.exec_command(f"rm -f {full_remote} {gz_remote} >/dev/null 2>&1")
    time.sleep(1.0)
    
    local_size = os.path.getsize(local_path)
    
    # 1. Compress the file in memory
    log(f"  ➡️  Compressing {filename}...", YELLOW)
    with open(local_path, "rb") as f_in:
        raw_data = f_in.read()
    
    gz_data = gzip.compress(raw_data)
    gz_size = len(gz_data)
    
    log(f"  ➡️  Transferring compressed {filename} ({gz_size} bytes, originally {local_size})...", YELLOW)
    
    try:
        # Start base64 decoding to the .gz file on remote side
        cmd = f"base64 -d > {gz_remote}"
        stdin, stdout, stderr = client.exec_command(cmd)
        
        # Send in very small chunks to respect MTU
        chunk_size = 1024
        for i in range(0, len(gz_data), chunk_size):
            chunk = gz_data[i:i+chunk_size]
            encoded = base64.b64encode(chunk)
            try:
                stdin.write(encoded)
                stdin.flush()
                time.sleep(0.01) # Critical delay
            except Exception as e:
                log(f"  ❌ Base64 Pipe Exception: {e}", RED)
                return False
                    
        stdin.channel.shutdown_write()
        time.sleep(1.0)
        
        # 2. Decompress remotely
        log(f"  ➡️  Decompressing on target...", YELLOW)
        client.exec_command(f"gzip -d {gz_remote}")
        time.sleep(0.5)
        
        # Verify Size
        stdin, stdout, stderr = client.exec_command(f"wc -c < {full_remote}")
        remote_size_str = stdout.read().decode().strip()
        
        if not remote_size_str.isdigit():
            log(f"  ❌ Decompression failed! Output: {remote_size_str}", RED)
            return False
            
        remote_size = int(remote_size_str)
        
        if local_size == remote_size:
            log(f"  ✅ Transfer Verified via Compressed Base64 ({remote_size} bytes)", GREEN)
            client.exec_command(f"chmod +x {full_remote}")
            return True
        else:
            log(f"  ⚠️ Size mismatch! Local: {local_size}, Remote: {remote_size}", YELLOW)
            return False
    except Exception as e:
        log(f"  ❌ Exception during transfer: {e}", RED)
        return False

# ==========================================
# ==========================================
# MAIN DEPLOY FLOW
# ==========================================

def main_deploy(mode_ipv6=False, enable_carla=False, test_data=False, rsu_only=False):
    log(f"V2X Deploy System (IPv6={mode_ipv6}, CARLA={enable_carla}, TEST_DATA={test_data})", CYAN)

    recompile_binaries(rsu_only=rsu_only)

    rsu_ip = None

    if mode_ipv6:
        # IPv6 MODO
        log("\n[2/4] Resolving RSU IP via DDNS (IPv6)...", YELLOW)
        rsu_ip = get_rsu_ip_from_ddns()
        if not rsu_ip:
            log("RSU IP not found via DDNS. Ensure the RSU has registered itself.", RED)
            sys.exit(1)
        log(f"Resolved RSU IP: {rsu_ip}", GREEN)
    else:
        # IPv4 MODO
        rsu_ip = RSU_IPV4
        log(f"\n[2/4] Ping RSU ({rsu_ip}) e OBU ({OBU_IPV4})...", YELLOW)
        if not check_ping(rsu_ip):
            log(f"RSU {rsu_ip} is unreachable! Check cables/network.", RED)
            sys.exit(1)
        if not rsu_only and not check_ping(OBU_IPV4):
            log(f"OBU {OBU_IPV4} is unreachable! Continuing anyway (might be on 5G only).", YELLOW)

    # 1. TRANSFER RSU FILE
    log(f"\n[3/4] Transferring files to RSU [{rsu_ip}] via SCP...", YELLOW)
    try:
        rsu_client = get_ssh_client(rsu_ip, RSU_USER, RSU_PASS)
        log("Sending fac_alert to RSU...", CYAN)
        transfer_file_robust(rsu_client, "fac_alert", "/tmp/fac_alert")

        # Em IPv6, pode ser necessário registrar no DDNS ou isso já foi feito externamente?
        if mode_ipv6:
            register_rsu_in_ddns(rsu_client)
            
        rsu_client.close()
        log("Upload to RSU complete.", GREEN)
    except Exception as e:
        log(f"Failed to connect or upload to RSU: {e}", RED)
        sys.exit(1)

    # 2. TRANSFER OBU FILE
    if not rsu_only:
        obu_ip = OBU_IPV4 # Usualmente OBU_IPV4 é fixo por cabo
        log(f"\n[4/4] Transferring files to OBU [{obu_ip}] via SCP...", YELLOW)
        try:
            obu_client = get_ssh_client(obu_ip, OBU_USER, OBU_PASS)
            log("Killing old obu_alert_server processes...", CYAN)
            obu_client.exec_command("killall -9 obu_alert_server")

            log("Sending obu_alert_server to OBU...", CYAN)
            transfer_file_robust(obu_client, "obu_alert_server", "/tmp/obu_alert_server")
            
            obu_client.close()
            log("Upload to OBU complete.", GREEN)
        except Exception as e:
            log(f"Failed to connect or upload to OBU: {e}", RED)
            sys.exit(1)

    # Lógica do Simulador Local / Destino do CARLA
    if enable_carla:
        # Pega IP Dinâmico da máquina local em direção ao IP alvo.
        # Se for IPv6, RSU tá na nuvem e o target é a nuvem. Se IPv4, target é a RSU local.
        local_pc_ip = get_local_ip(target_ip=rsu_ip) 
        log(f"\n[!] MODO CARLA LOCAL: IP descoberto = {local_pc_ip}", YELLOW)
        
        carla_target = local_pc_ip
        
        # Lança o simulador local na porta 8080 (usando subprocess para não travar esta tela)
        log("\nLaunch Simulador CARLA...", YELLOW)
        if test_data:
            open_child_window("CARLA_TestData", mode="simulate_test_data")
        else:
            open_child_window("CARLA_Interactive", mode="simulate_interactive")
            
        log("  ⏳ Esperando 3s para o servidor CARLA iniciar...", YELLOW)
        time.sleep(3)
    else:
        # Se não usamos o PC local para carla, usamos o IP Fixo do CARLA Real (.env)
        # Modo IPv6 -> passamos CARLA_FIXED_IPV6
        # Modo IPv4 -> passamos CARLA_FIXED_IPV4
        carla_target = CARLA_FIXED_IPV6 if mode_ipv6 else CARLA_FIXED_IPV4
        log(f"\n[!] MODO CARLA FIXO: RSU se conectará ao CARLA em {carla_target}", YELLOW)

    # Executa OBU em Janela Secundária
    if not rsu_only:
        log("\nLaunching OBU Server...", YELLOW)
        open_child_window("OBU_Console", ip=OBU_IPV4, user=OBU_USER, password=OBU_PASS, command="/tmp/obu_alert_server", mode="listen")

    # Executa RSU em Janela Secundária apontando para o IP do CARLA correspondente
    # Na OBU/RSU o primeiro IP é o fallback/principal. Vamos focar num IP primário pra não sujar.
    log(f"\nLaunching RSU Client (target: {carla_target})...", YELLOW)
    open_child_window("RSU_Console", ip=rsu_ip, user=RSU_USER, password=RSU_PASS, command=f"/tmp/fac_alert {carla_target}", mode="listen")

    log("\nDeploy Concluido! Pressione Enter para fechar as janelas do terminal (se foram atachadas a este processo).", GREEN)
    try:
        input()
    except KeyboardInterrupt:
        pass


import json
# ==========================================
# SIMULATION LOGIC (CARLA INTERACTIVE)
# ==========================================

# --------------------------
# Message Generation Helpers
# Structs reference: modular_us/*.h
# --------------------------

def create_bsm(msg_count):
    """Generates a Basic Safety Message (BSM) JSON wrapped in MessageFrame.
    MessageFrame { messageId: 20, value: BasicSafetyMessage }
    Struct ref: bsm_types.h -> US_BSMcoreData, US_BasicSafetyMessage
    """
    sec_mark = int((time.time() * 1000) % 60000)
    # FORCING BSM LOCATION TO MATCH PSM LOCATION FOR IMMEDIATE COLLISION
    lat_asn = -235497100
    lon_asn = -466327200
    speed_asn = 750  # 15 m/s

    json_data = {
        "bsm": {
            "messageId": 20,
            "value": {
                "coreData": {
                    "msgCnt": msg_count % 128,
                    "id": "A1B2C3D4",
                    "secMark": sec_mark,
                    "lat": lat_asn,
                    "long": lon_asn,
                    "elev": 100,
                    "accuracy": {
                        "semiMajor": 40,
                        "semiMinor": 40,
                        "orientation": 0
                    },
                    "transmission": "forwardGears",
                    "speed": speed_asn,
                    "heading": 0,
                    "angle": 0,
                    "accelSet": {
                        "long": 0,
                        "lat": 0,
                        "vert": 0,
                        "yaw": 0
                    },
                    "brakes": {
                        "wheelBrakes": "00",
                        "traction": "unavailable",
                        "abs": "unavailable",
                        "scs": "unavailable",
                        "brakeBoost": "unavailable",
                        "auxBrakes": "unavailable"
                    },
                    "size": {
                        "width": 200,
                        "length": 500
                    }
                }
            }
        }
    }
    return json.dumps(json_data)

def create_map(msg_count):
    """Generates a Map Data (MAP) JSON.
    Struct ref: map_and_signal_types.h -> US_MapData, US_IntersectionGeometry,
    US_GenericLane, US_LaneAttributes, US_LaneTypeAttributes
    US_NodeOffsetPointXY CHOICE: node-XY1 = Node_XY_20b (x, y as Offset_B10)
    """
    json_data = {
        "mapData": {
            "messageId": 18,
            "value": {
                "msgIssueRevision": msg_count % 128,
                "intersections": [
                    {
                        "id": {
                            "region": 0,
                            "id": 1
                        },
                        "revision": 1,
                        "refPoint": {
                            "lat": -235500000,
                            "long": -466330000
                        },
                        "laneSet": [
                            {
                                "laneID": 1,
                                "laneAttributes": {
                                    "directionalUse": {
                                        "value": "80",
                                        "length": 2
                                    },
                                    "sharedWith": {
                                        "value": "0000",
                                        "length": 10
                                    },
                                    "laneType": {
                                        "vehicle": {
                                            "value": "00",
                                            "length": 8
                                        }
                                    }
                                },
                                "nodeList": {
                                    "nodes": [
                                        {"delta": {"node-XY1": {"x": 0, "y": 0}}},
                                        {"delta": {"node-XY1": {"x": 100, "y": 0}}}
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        }
    }
    return json.dumps(json_data)

def create_spat(msg_count):
    """Generates a Signal Phase and Timing (SPAT) JSON.
    Struct ref: message_frame_and_spat_types.h -> US_SPAT, US_IntersectionState,
    US_MovementState, US_MovementEvent, US_TimeChangeDetails
    """
    now = time.time()
    local_time = time.localtime(now)
    current_dsec = (local_time.tm_min * 60 + local_time.tm_sec) * 10
    event_state = "protected-Movement-Allowed" if (msg_count % 20 < 10) else "stop-And-Remain"
    min_end = (current_dsec + 100) % 36000

    json_data = {
        "spat": {
            "messageId": 19,
            "value": {
                "intersections": [
                    {
                        "id": {
                            "region": 0,
                            "id": 1
                        },
                        "revision": 1,
                        "status": "0000",
                        "states": [
                            {
                                "signalGroup": 1,
                                "state-time-speed": [
                                    {
                                        "eventState": event_state,
                                        "timing": {
                                            "minEndTime": min_end,
                                            "maxEndTime": min_end + 50
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        }
    }
    return json.dumps(json_data)

def create_rsa(msg_count):
    """Generates a Road Side Alert (RSA) JSON.
    Struct ref: rsa_types.h -> US_RoadSideAlert
    US_FullPositionVector field order: Long, lat, elevation
    US_Priority is ASN1String (1 byte OCTET STRING)
    US_HeadingSlice is ASN1BitString (16 bits)
    US_FurtherInfoID is ASN1String (2 byte OCTET STRING)
    US_Extent enum: useInstantlyOnly (not useInstantly)
    """
    json_data = {
        "rsa": {
            "messageId": 27,
            "value": {
                "msgCnt": msg_count % 128,
                "typeEvent": 1231,
                "description": [533],
                "priority": "00",
                "heading": {
                    "value": "0001",
                    "length": 16
                },
                "extent": "useInstantlyOnly",
                "position": {
                    "long": -466335000,
                    "lat": -235505000,
                    "elevation": 100
                },
                "furtherInfoID": "0000"
            }
        }
    }
    return json.dumps(json_data)

def create_tim(msg_count):
    """Generates a Traveler Information Message (TIM) wrapped in MessageFrame.
    MessageFrame { messageId: 31, value: TravelerInformation }
    Struct ref: traveler_and_probe_types.h -> US_TravelerInformation
    """
    json_data = {
        "tim": {
            "messageId": 31,
            "value": {
                "msgCnt": msg_count % 127,
                "timeStamp": int(time.time() % 525600),
                "packetID": "000000000000000000",
                "dataFrames": [
                    {
                        "notUsed": 0,
                        "frameType": "advisory",
                        "msgId": {
                            "roadSignID": {
                                "position": {
                                    "lat": -235502000,
                                    "long": -466332000,
                                    "elevation": 100
                                },
                                "viewAngle": "0000",
                                "mutcdCode": "warning",
                                "crc": "0000"
                            }
                        },
                        "startTime": 0,
                        "durationTime": 1,
                        "priority": 1,
                        "notUsed1": 0,
                        "regions": [
                            {
                                "name": "zona_escolar",
                                "anchor": {
                                    "lat": -235497100,
                                    "long": -466327200,
                                    "elevation": 100
                                },
                                "directionality": "both",
                                "closedPath": False
                            }
                        ],
                        "notUsed2": 0,
                        "notUsed3": 0,
                        "content": {
                            "workZone": [
                                {"item": {"itis": 4867}}
                            ]
                        }
                    }
                ]
            }
        }
    }
    return json.dumps(json_data)

def create_psm(msg_count):
    """Creates a PSM (Personal Safety Message) wrapped in MessageFrame.
    MessageFrame { messageId: 32, value: PersonalSafetyMessage }
    Struct ref: psm_types.h -> US_PersonalSafetyMessage
    """
    sec_mark = int((time.time() * 1000) % 60000)
    # FORCING PSM LOCATION TO MATCH BSM LOCATION FOR IMMEDIATE COLLISION
    lat_asn = -235497100
    lon_asn = -466327200

    json_data = {
        "psm": {
            "messageId": 32,
            "value": {
                "basicType": "aPEDESTRIAN",
                "secMark": sec_mark,
                "msgCnt": msg_count % 128,
                "id": "50534D31",
                "position": {
                    "lat": lat_asn,
                    "long": lon_asn,
                    "elevation": 100
                },
                "accuracy": {
                    "semiMajor": 40,
                    "semiMinor": 40,
                    "orientation": 0
                },
                "speed": 100,
                "heading": 0,
                "pathHistory": {
                    "crumbData": [
                        {
                            "latOffset": 0,
                            "lonOffset": 0,
                            "elevationOffset": 0,
                            "timeOffset": 1
                        }
                    ]
                },
                "pathPrediction": {
                    "radiusOfCurve": 0,
                    "confidence": 200
                }
            }
        }
    }
    return json.dumps(json_data)

# --------------------------
# Message Dispatcher
# --------------------------

MESSAGE_GENERATORS = {
    "bsm": create_bsm,
    "map": create_map,
    "spat": create_spat,
    "rsa": create_rsa,
    "tim": create_tim,
    "psm": create_psm,
}

# --------------------------
# Multi-Client TCP Server (Simulation)
# --------------------------

class SocketSender:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.listen_sock = None
        self.clients = []  # List to store active client socket objects
        self.running = True

    def start_server(self):
        """Initializes the server and starts a background thread to accept clients."""
        self.listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listen_sock.bind((self.host, self.port))
        self.listen_sock.listen(5)  # Allow a backlog of connections
        log(f"[INFO] Server listening on {self.host}:{self.port}...", CYAN)

        # Start the background thread for accepting connections
        self.accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
        self.accept_thread.start()

    def _accept_clients(self):
        """Background loop to accept new clients without blocking the main loop."""
        while self.running:
            try:
                client_sock, addr = self.listen_sock.accept()
                
                # Desativa o Nagle's Algorithm para envio imediato (Reduz Latência TCP)
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                
                log(f"[INFO] New client connected from: {addr}", GREEN)
                self.clients.append(client_sock)
            except Exception as e:
                if self.running:
                    log(f"[ERROR] Accept failed: {e}", RED)
                break

    def send_event(self, event_data):
        """Sends data to ALL connected clients and removes dead ones."""
        if not self.clients:
            return

        message = json.dumps(event_data).encode('utf-8') + b'\n'
        disconnected_clients = []

        for client in self.clients:
            try:
                client.sendall(message)
            except (socket.error, BrokenPipeError):
                disconnected_clients.append(client)

        # Clean up clients that closed the connection
        for client in disconnected_clients:
            log("[INFO] Removing disconnected client.", YELLOW)
            client.close()
            self.clients.remove(client)

    def close(self):
        self.running = False
        if self.listen_sock:
            self.listen_sock.close()
        for client in self.clients:
            client.close()
        log("[INFO] Server shut down.", CYAN)


def run_interactive_simulation(test_data=False):
    """Starts the Interactive CARLA Simulator as a TCP Server.
    
    Architecture: This PC acts as TCP SERVER on port 8080.
    RSU (fac_alert) connects here as a CLIENT, receives JSON messages,
    encodes them to UPER and broadcasts via DSRC radio to the OBU.
    """
    os.system("title CARLA_Simulator_Controller")
    log("CARLA INTERACTIVE SIMULATOR (TCP Server Mode)", CYAN)
    log(f"This PC IP (RSU must reach this): {get_local_ip()}", GREEN)
    log(f"Listening on 0.0.0.0:{RSU_PORT} — RSU (fac_alert) will auto-connect...", CYAN)
    log("Commands: list, send [TYPE], auto [TYPE] [INTERVAL], status, close, quit", YELLOW)
    log("Types: bsm, map, spat, rsa, tim, psm, all", YELLOW)
    log("====================================" , CYAN)
    log(">>> Waiting for RSU to connect. Once connected, type 'send' to trigger an OBU alert (sends BSM+PSM+TIM).", GREEN)

    sender = SocketSender("0.0.0.0", RSU_PORT)
    sender.start_server()
    msg_count = 0

    if test_data:
        log("\n[TESTE DE DADOS] Modo automatizado ativado! Enviando BSM+PSM+TIM a 10Hz...", YELLOW)
        interval = 0.1
        ALERT_TYPES = ["bsm", "psm", "tim"]
        gen_list = [(t, MESSAGE_GENERATORS[t]) for t in ALERT_TYPES if t in MESSAGE_GENERATORS]
        
        # Cria arquivo de log
        log_file = open("log_envio_interno.csv", "w")
        log_file.write("Seq_ID,Timestamp_Send,size_bytes\n")
        
        try:
            while True:
                msg_count += 1
                for name, gen_func in gen_list:
                    msg = json.loads(gen_func(msg_count))
                    sender.send_event(msg)
                    # O CARLA manda 3 mensagens por ciclo (BSM, PSM, TIM).
                    # A RSU geralmente gera alertas a partir dessa combinação.
                    # Vamos registrar o Timestamp para bater com o Seq_ID do log da OBU.
                
                # Registra apenas o envio do pacote consolidado ou do BSM principal
                timestamp = int(time.time() * 1000)
                # OBU recebe o count com módulo 128, então precisamos gravar assim também!
                # E estimamos ~151 bytes por ciclo (BSM+PSM+TIM)
                log_file.write(f"{msg_count % 128},{timestamp},151\n")
                log_file.flush()
                
                if not sender.clients:
                    print(f"  [>] Auto-Sent #{msg_count} (Sem clientes conectados)")
                else:
                    print(f"  [>] Auto-Sent #{msg_count} para {len(sender.clients)} client(s)")
                
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[*] Auto-Mode Stopped.")
        finally:
            log_file.close()
            sender.close()
            return

    while True:
        try:
            n_clients = len(sender.clients)
            cmd_raw = input(f"CARLA ({n_clients} connected)> ").strip().lower()
            parts = cmd_raw.split()
            if not parts:
                continue

            cmd = parts[0]

            if cmd in ("quit", "exit"):
                break

            elif cmd == "list":
                print("\nAvailable Message Types:")
                print("  bsm  - Basic Safety Message (Vehicle pos/state)")
                print("  map  - Map Data (Intersection Geometry)")
                print("  spat - Signal Phase and Timing (Traffic Lights)")
                print("  rsa  - Road Side Alert (Hazards)")
                print("  tim  - Traveler Information (Work Zones)")
                print("  psm  - Personal Safety Message (Pedestrians)")
                print("  all  - Send ALL types (bsm+map+spat+rsa+tim+psm)")
                print("")
                print("  NOTE: The OBU only forwards to the tablet when it receives")
                print("        BSM + PSM + TIM together. 'send' without args sends all 3.")
                print("")

            elif cmd == "status":
                print(f"\nConnected clients: {n_clients}")
                for i, client in enumerate(sender.clients):
                    try:
                        addr = client.getpeername()
                        print(f"  [{i}] {addr[0]}:{addr[1]}")
                    except Exception:
                        print(f"  [{i}] (unknown)")
                print("")

            elif cmd == "close":
                for client in sender.clients:
                    try: client.close()
                    except: pass
                sender.clients.clear()
                print("[-] Disconnected all clients.")

            elif cmd == "send":
                if not sender.clients:
                    print("[!] No clients connected. Wait for RSU/OBU to connect.")
                    continue

                msg_type = parts[1] if len(parts) > 1 else "alert"
                msg_count += 1

                # "alert" (default) = the 3 types the OBU needs to forward to the tablet
                ALERT_TYPES = ["bsm", "psm", "tim"]

                if msg_type == "all":
                    for gen_name, gen_func in MESSAGE_GENERATORS.items():
                        msg = json.loads(gen_func(msg_count))
                        sender.send_event(msg)
                    print(f"  [>] Sent ALL types (Msg #{msg_count}) to {len(sender.clients)} client(s)")
                elif msg_type == "alert":
                    sent = []
                    for t in ALERT_TYPES:
                        gen = MESSAGE_GENERATORS.get(t)
                        if gen:
                            msg = json.loads(gen(msg_count))
                            sender.send_event(msg)
                            sent.append(t)
                    print(f"  [>] Sent alert bundle [{'+'.join(sent)}] (Msg #{msg_count}) -> OBU will now forward to tablet")
                else:
                    gen = MESSAGE_GENERATORS.get(msg_type)
                    if not gen:
                        print(f"[!] Unknown message type: {msg_type}. Type 'list' for options.")
                        continue
                    msg = json.loads(gen(msg_count))
                    sender.send_event(msg)
                    print(f"  [>] Sent '{msg_type}' (Msg #{msg_count}) to {len(sender.clients)} client(s)")
                    if msg_type in ("bsm", "psm", "tim"):
                        print(f"  [!] NOTE: OBU needs BSM+PSM+TIM to forward. Missing: { {t for t in ALERT_TYPES if t != msg_type} }")

            elif cmd == "auto":
                if not sender.clients:
                    print("[!] No clients connected. Wait for RSU/OBU to connect.")
                    continue

                msg_type = parts[1] if len(parts) > 1 else "alert"
                interval = 1.0  # Default 1Hz
                if len(parts) > 2:
                    try: interval = float(parts[2])
                    except: pass

                ALERT_TYPES = ["bsm", "psm", "tim"]

                if msg_type == "all":
                    gen_list = list(MESSAGE_GENERATORS.items())
                elif msg_type == "alert":
                    gen_list = [(t, MESSAGE_GENERATORS[t]) for t in ALERT_TYPES if t in MESSAGE_GENERATORS]
                else:
                    gen = MESSAGE_GENERATORS.get(msg_type)
                    if not gen:
                        print(f"[!] Unknown message type: {msg_type}")
                        continue
                    gen_list = [(msg_type, gen)]

                type_label = '+'.join([t for t, _ in gen_list])
                print(f"[*] Auto-sending '{type_label}' every {interval}s (Ctrl+C to stop)...")
                if msg_type == "alert":
                    print(f"    (BSM+PSM+TIM bundle — OBU will forward to tablet on each cycle)")
                try:
                    while True:
                        msg_count += 1
                        for name, gen_func in gen_list:
                            msg = json.loads(gen_func(msg_count))
                            sender.send_event(msg)
                        if not sender.clients:
                            print("[!] All clients disconnected, stopping auto-mode.")
                            break
                        print(f"  [>] Auto-Sent #{msg_count} [{type_label}] to {len(sender.clients)} client(s)")
                        time.sleep(interval)
                except KeyboardInterrupt:
                    print("\n[*] Auto-Mode Stopped.")

            else:
                print("Unknown command. Type 'list' for options.")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ERROR: {e}")

    sender.close()
    log("Simulator Closed.", CYAN)


# ==========================================
# WINDOW MANAGEMENT
# ==========================================

def interactive_shell(ip, user, password, command, title):
    """Refined Interactive Shell for the child windows."""
    os.system(f"title {title}")
    log(f"🔌 Connecting to {title} ({ip})...", CYAN)
    
    client = get_ssh_client(ip, user, password)
    if not client:
        log("\n❌ Failed to connect. Press key to exit.", RED)
        input()
        return

    try:
        log(f"🚀 Starting Remote Command: {command}", GREEN)
        log("==========================================", CYAN)
        
        chan = client.invoke_shell()
        time.sleep(1)
        chan.send(command + "\n")
        
        import msvcrt
        
        def write_to_stdout():
            while True:
                if chan.recv_ready():
                    try:
                        data = chan.recv(1024)
                        if not data: break
                        sys.stdout.buffer.write(data)
                        sys.stdout.flush()
                    except: break
                time.sleep(0.01)
                
        t = threading.Thread(target=write_to_stdout, daemon=True)
        t.start()
        
        while True:
            if msvcrt.kbhit():
                char = msvcrt.getch()
                chan.send(char)
            if not t.is_alive() or not chan.active:
                break
            time.sleep(0.05)
            
    except Exception as e:
        log(f"\n❌ Connection Error: {e}", RED)
    finally:
        if client: client.close()
        log("\nDisconnected.", RESET)
        input("\nPress Enter to close window...")

def open_child_window(title, ip=None, user=None, password=None, command=None, mode="listen"):
    """
    Spawns a new CMD window running THIS script in a specific mode.
    Modes: 
      - 'listen': Connects SSH and runs command (RSU/OBU Consoles)
      - 'simulate': Runs the CARLA simulation loop (Local)
    """
    script_path = os.path.abspath(__file__)
    python_exe = sys.executable
    
    if mode == "listen":
        # Argument Quoting
        safe_pass = password.replace('"', '\\"')
        # Escapamos caracteres especiais do Windows (^|, ^&, ^>) para que não sejam interpretados localmente
        safe_cmd = command.replace('"', '\\"').replace('|', '^|').replace('&', '^&').replace('>', '^>')
        args = f'"{python_exe}" "{script_path}" --listen --ip {ip} --user {user} --pass "{safe_pass}" --cmd "{safe_cmd}" --title "{title}"'
        
    elif mode == "simulate":
        args = f'"{python_exe}" "{script_path}" --simulate'
    elif mode == "simulate_interactive":
        args = f'"{python_exe}" "{script_path}" --simulate'
    elif mode == "simulate_test_data":
        args = f'"{python_exe}" "{script_path}" --simulate_test_data'
        
    full_cmd = f'start "{title}" cmd /k "{args}"'
    
    log(f"  🖥️  Launching {title}...", CYAN)
    subprocess.Popen(full_cmd, shell=True)

# ==========================================
# MAIN DEPLOY FLOW
# ==========================================


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="V2X Deploy System - Unificado")
    
    # Internal Modes for child windows
    parser.add_argument("--listen", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--simulate", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--simulate_test_data", action="store_true", help=argparse.SUPPRESS)
    
    # Listen arguments
    parser.add_argument("--ip", help=argparse.SUPPRESS)
    parser.add_argument("--user", help=argparse.SUPPRESS)
    parser.add_argument("--pass", dest="password", help=argparse.SUPPRESS)
    parser.add_argument("--cmd", help=argparse.SUPPRESS)
    parser.add_argument("--title", help=argparse.SUPPRESS)
    
    # Mutually exclusive group for mode
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ipv4", action="store_true", help="Usa a rede local IPv4 (Padrão)")
    group.add_argument("--ipv6", action="store_true", help="Usa rede IPv6/DDNS")
    
    parser.add_argument("--carla", action="store_true", help="Usa o simulador CARLA rodando na máquina local (abre janela e descobre o IP)")
    parser.add_argument("--teste_dados", action="store_true", help="Deve ser usado junto com --carla. Inicia o simulador interno em modo de disparo automatico e gera log_envio_interno.csv.")
    parser.add_argument("--rsu-only", action="store_true", help="Apenas compila e envia para a RSU (Ignora a OBU)")
    parser.add_argument("--sync", action="store_true", help="Sincroniza os relógios da RSU, OBU e PC via GPS PPS antes de iniciar")

    args, _ = parser.parse_known_args()

    if args.listen:
        try:
            interactive_shell(args.ip, args.user, args.password, args.cmd, args.title)
        except Exception as e:
            print(f"Error in listen mode: {e}")
        sys.exit(0)
        
    if args.simulate:
        run_interactive_simulation(test_data=False)
        sys.exit(0)
        
    if args.simulate_test_data:
        run_interactive_simulation(test_data=True)
        sys.exit(0)

    # Se não especificou nenhum, assume ipv4
    mode_ipv6 = args.ipv6
    
    # Se passou teste_dados mas não passou carla, alerta
    if args.teste_dados and not args.carla:
        print("AVISO: --teste_dados não faz nada sem a flag --carla. Ativando --carla automaticamente.")
        args.carla = True

    # Sincronização GPS PPS (opcional, mas recomendado para métricas precisas)
    if args.sync:
        try:
            from sync_gps_time import full_sync
            log("\n[0/4] Sincronizando relógios via GPS PPS...", YELLOW)
            full_sync()
        except ImportError:
            log("[AVISO] sync_gps_time.py não encontrado. Pulando sincronização.", YELLOW)
        except Exception as e:
            log(f"[AVISO] Falha na sincronização GPS: {e}. Continuando mesmo assim.", YELLOW)

    main_deploy(
        mode_ipv6=mode_ipv6,
        enable_carla=args.carla,
        test_data=args.teste_dados,
        rsu_only=args.rsu_only
    )
