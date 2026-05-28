#!/usr/bin/env python3
"""
Tablet App Simulator for V2X Alert System
Conecta 2030

This script mimics the behavior of the Android Tablet App.
It connects to the OBU, receives V2X messages (PSM/BSM),
associates data, calculates risk (TTC), and displays alerts.

Logic:
1. Connect to OBU Server (TCP 8080)
2. Receive JSON stream: { "psm": {...}, "bsm": {...}, "tim": {...} }
3. Calculate Distance, Bearing, and TTC (Time To Collision)
4. Display "Visual" Alerts in Console
"""

import socket
import json
import math
import time
import sys

# Configuration
OBU_IP = "192.168.0.53"  # IP of the OBU
OBU_PORT = 8080
BUFFER_SIZE = 4096

# --- Math & Physics Logic (Replicated from Kotlin App) ---

def to_radians(deg):
    return deg * (math.pi / 180.0)

def to_degrees(rad):
    return rad * (180.0 / math.pi)

def normalize_angle(angle):
    """Normalize angle to -180...180 range."""
    a = angle % 360
    if a > 180: a -= 360
    if a <= -180: a += 360
    return a

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Calculates bearing from point 1 to point 2."""
    lat1_rad = to_radians(lat1)
    lat2_rad = to_radians(lat2)
    delta_lon_rad = to_radians(lon2 - lon1)

    y = math.sin(delta_lon_rad) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon_rad)
    
    bearing_rad = math.atan2(y, x)
    return (to_degrees(bearing_rad) + 360) % 360

def distance_meters(lat1, lon1, lat2, lon2):
    """Haversine formula for distance in meters."""
    R = 6371000.0 # Earth radius in meters
    dlat = to_radians(lat2 - lat1)
    dlon = to_radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(to_radians(lat1)) * math.cos(to_radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def calculate_risk_level(ttc):
    if ttc is None: return "low"
    if ttc < 4.0: return "high"
    if ttc <= 8.0: return "medium"
    return "low"

def get_direction_string(relative_angle):
    if -45 <= relative_angle < 45: return "FRONT"
    if 45 <= relative_angle < 135: return "RIGHT"
    if relative_angle >= 135 or relative_angle < -135: return "REAR"
    return "LEFT"

def process_message(data):
    """Processes the incoming JSON from the OBU."""
    
    # 1. Check if it's our new Unified Message format (BSM + PSM + TIM)
    if "bsm" in data and "psm" in data and "tim" in data:
        print("\n" + "="*60)
        print("!!! UNIFIED V2X ALERT RECEIVED (BSM + PSM + TIM) !!!")
        print("="*60)
        
        try:
            # Extract basic info
            psm = data["psm"]["value"] if "value" in data["psm"] else data["psm"]
            bsm = data["bsm"]["value"]["coreData"] if "value" in data["bsm"] else data["bsm"]["coreData"]
            tim = data["tim"]["value"] if "value" in data["tim"] else data["tim"]
            
            # Parse User (Car) Data
            user_lat = bsm["lat"] / 10000000.0
            user_lon = bsm["long"] / 10000000.0
            user_speed = float(bsm["speed"]) * 0.02
            user_heading = bsm["heading"] * 0.0125
            
            # Parse Object Data
            obj_lat = psm["position"]["lat"] / 10000000.0
            obj_lon = psm["position"]["long"] / 10000000.0
            obj_speed = psm["speed"] * 0.02
            obj_type = psm.get("basicType", "aPEDESTRIAN")
            
            # Translate Type (No Emojis for Windows CMD)
            if "PEDESTRIAN" in obj_type.upper():
                obj_type = "PEDESTRIAN"
            elif "CYCLIST" in obj_type.upper():
                obj_type = "CYCLIST"
            
            # Parse Zone Data
            region_name = "Unknown Zone"
            try:
                tim_df = tim["dataFrames"][0]
                region_name = tim_df["regions"][0]["name"]
            except (KeyError, IndexError):
                pass
            
            # Calculations
            distance = distance_meters(user_lat, user_lon, obj_lat, obj_lon)
            bearing = calculate_bearing(user_lat, user_lon, obj_lat, obj_lon)
            relative_angle = normalize_angle(bearing - user_heading)
            direction = get_direction_string(relative_angle)
            
            # TTC
            v_rel = user_speed + obj_speed if direction.lower() in ["front", "left", "right"] else (obj_speed - user_speed if obj_speed > user_speed else -1.0)
            ttc = (distance / v_rel) if v_rel > 0 else None
            risk_level = calculate_risk_level(ttc)
            
            # Print Alert Data
            print(json.dumps({
                "alertType": "Collision & Zone Warning",
                "riskLevel": risk_level.upper(),
                "timeToCollisionSecs": round(ttc, 2) if ttc else None,
                "distanceMeters": round(distance, 2),
                "objectType": obj_type,
                "direction": direction,
                "activeZone": region_name
            }, indent=2))
            
        except KeyError as e:
            print(f"- Error extracting data from Unified Message: Missing key {e}")

    # 2. Check for individual raw messages (MAP, SPAT, RSA, etc)
    else:
        msg_type = list(data.keys())[0] if isinstance(data, dict) and len(data.keys()) > 0 else "UNKNOWN"
        print("\n" + "-"*50)
        print(f">>> RAW V2X MESSAGE RECEIVED: {msg_type.upper()} <<<")
        print("-"*50)
        
        # Only print the first few lines to avoid flooding terminal with huge MAP payloads
        formatted_json = json.dumps(data, indent=2)
        lines = formatted_json.split("\n")
        if len(lines) > 25:
            print("\n".join(lines[:25]))
            print(f"  ... [TRUNCATED {len(lines) - 25} MORE LINES] ...")
            print("}")
        else:
            print(formatted_json)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Tablet App Simulator for V2X")
    parser.add_argument("--ip", default=OBU_IP, help=f"OBU IP address (default: {OBU_IP})")
    parser.add_argument("--port", type=int, default=OBU_PORT, help=f"OBU port (default: {OBU_PORT})")
    args = parser.parse_args()

    obu_ip = args.ip
    obu_port = args.port
    reconnect_delay = 5  # seconds, matching the app's reconnect behavior

    print("=" * 50)
    print("  V2X Tablet App Simulator - Conecta 2030")
    print("=" * 50)
    print(f"  Target: {obu_ip}:{obu_port}")
    print(f"  Reconnect delay: {reconnect_delay}s")
    print("  Press Ctrl+C to stop")
    print("=" * 50)

    while True:
        client = None
        try:
            print(f"\n[CONN] Connecting to OBU at {obu_ip}:{obu_port}...")
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(10)
            client.connect((obu_ip, obu_port))
            client.settimeout(None)

            print("[CONN] Connected! Waiting for V2X messages...")

            # Brace-counting JSON parser (same approach as the Android app)
            buffer = ""
            brace_depth = 0
            json_start = -1

            while True:
                chunk = client.recv(BUFFER_SIZE).decode('utf-8', errors='ignore')
                if not chunk:
                    print("[CONN] Server closed connection.")
                    break

                buffer += chunk

                # Parse complete JSON objects using brace counting
                i = 0
                while i < len(buffer):
                    c = buffer[i]
                    if c == '{':
                        if brace_depth == 0:
                            json_start = i
                        brace_depth += 1
                    elif c == '}':
                        brace_depth -= 1
                        if brace_depth == 0 and json_start >= 0:
                            json_str = buffer[json_start:i+1]
                            try:
                                data = json.loads(json_str)
                                process_message(data)
                            except json.JSONDecodeError:
                                print(f"[WARN] Invalid JSON ({len(json_str)} bytes)")
                            json_start = -1
                    i += 1

                # Keep only unprocessed data in buffer
                if json_start >= 0:
                    buffer = buffer[json_start:]
                    json_start = 0
                else:
                    buffer = ""
                    brace_depth = 0

        except socket.timeout:
            print(f"[CONN] Connection timed out.")
        except ConnectionRefusedError:
            print(f"[CONN] Connection refused (OBU server not running?).")
        except OSError as e:
            print(f"[CONN] Connection error: {e}")
        except KeyboardInterrupt:
            print("\n[EXIT] Simulator stopped.")
            break
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

        # Auto-reconnect (same as Android app)
        try:
            print(f"[CONN] Reconnecting in {reconnect_delay}s...")
            time.sleep(reconnect_delay)
        except KeyboardInterrupt:
            print("\n[EXIT] Simulator stopped.")
            break

if __name__ == "__main__":
    main()
