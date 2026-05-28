#!/usr/bin/env python3
"""
CARLA Full Topology Extractor - Conecta 2030

Connects to a running CARLA simulator and continuously extracts the complete
road topology (all junctions, all lanes, all road segments) into the
map_cruzamento.json file used by the manual_control game loop.

The script runs alongside the simulation—while CARLA is open, it keeps
the JSON updated so the MAP broadcast always reflects the full map.

Usage:
  python extract_map_facens.py              # Continuous (default 10s interval)
  python extract_map_facens.py --interval 5 # Custom interval
  python extract_map_facens.py --host 192.168.0.10  # Remote CARLA
"""

import carla
import json
import math
import os
import sys
import time
import argparse

# ==============================================
# COORDINATE REFERENCE (Facens Campus / Sorocaba)
# ==============================================
REF_LAT = -23.4703361
REF_LON = -47.4308804

# Zone center for the intersection reference point
MAP_ZONE_LAT = -23.4720
MAP_ZONE_LON = -47.4280

# ==============================================
# COORDINATE CONVERSION
# ==============================================

def carla_to_wgs84(location):
    """Convert CARLA world coordinates to WGS84 lat/lon."""
    lat = REF_LAT + (location.y / 111139.0)
    lon = REF_LON + (location.x / (111139.0 * math.cos(math.radians(lat))))
    return lat, lon

def wgs84_to_carla(lat, lon):
    """Convert WGS84 lat/lon to CARLA world coordinates."""
    y = (lat - REF_LAT) * 111139.0
    x = (lon - REF_LON) * (111139.0 * math.cos(math.radians(lat)))
    return x, y

# ==============================================
# TOPOLOGY EXTRACTION
# ==============================================

def extract_all_junctions(carla_map):
    """Discover ALL junctions in the map via the topology graph."""
    junctions = {}
    for w1, w2 in carla_map.get_topology():
        if w1.is_junction:
            junctions[w1.junction_id] = w1.get_junction()
        if w2.is_junction:
            junctions[w2.junction_id] = w2.get_junction()
    return junctions

def waypoints_to_nodes(waypoints, ref_lat, ref_lon, max_nodes=63):
    """
    Convert CARLA waypoints into J2735 node offset list.
    First node is relative to refPoint, subsequent nodes relative to previous.
    """
    if len(waypoints) > max_nodes:
        step = max(1, len(waypoints) // max_nodes)
        waypoints = waypoints[::step][:max_nodes]

    nodes = []
    current_lat = ref_lat
    current_lon = ref_lon

    for w in waypoints:
        node_lat, node_lon = carla_to_wgs84(w.transform.location)

        dy_meters = (node_lat - current_lat) * 111139.0
        dx_meters = (node_lon - current_lon) * (111139.0 * math.cos(math.radians(current_lat)))

        dx_cm = int(dx_meters * 100)
        dy_cm = int(dy_meters * 100)

        # Skip zero-offset duplicates
        if dx_cm == 0 and dy_cm == 0 and len(nodes) > 0:
            current_lat = node_lat
            current_lon = node_lon
            continue

        # Clamp to node-XY6 range (16-bit signed = -32768 to 32767)
        # 32767 cm = 327.67 meters maximum distance per node
        dx_cm = max(-32767, min(32767, dx_cm))
        dy_cm = max(-32767, min(32767, dy_cm))

        nodes.append({
            "delta": {
                "node-XY6": {
                    "x": dx_cm,
                    "y": dy_cm
                }
            }
        })

        current_lat = node_lat
        current_lon = node_lon

    return nodes

def build_lane_entry(lane_id, carla_lane_id, waypoints, ref_lat, ref_lon):
    """Build a single J2735 lane entry from a set of waypoints."""
    nodes = waypoints_to_nodes(waypoints, ref_lat, ref_lon)

    if len(nodes) < 2:
        return None

    # Negative CARLA lane IDs = ingress (forward travel), positive = egress
    if carla_lane_id < 0:
        dir_use = "000000000000000010"  # ingressPath
    else:
        dir_use = "000000000000000100"  # egressPath

    return {
        "laneID": lane_id,
        "laneAttributes": {
            "directionalUse": dir_use,
            "sharedWith": "000000000000000000",
            "laneType": {
                "vehicle": "000000000000000000"
            }
        },
        "nodeList": {
            "nodes": nodes
        }
    }

# ==============================================
# FULL TOPOLOGY BUILDER
# ==============================================

def build_full_topology(carla_map):
    """
    Build a complete J2735 MAP payload from the entire CARLA map.
    Extracts all junctions as intersections with all their lanes
    plus approach/departure road segments.
    """
    print("=" * 60)
    print("  CARLA Full Topology Extractor")
    print("=" * 60)

    # 1. Discover ALL junctions
    junctions = extract_all_junctions(carla_map)
    print(f"\n  Found {len(junctions)} junctions in map '{carla_map.name}'")

    # 2. Generate all waypoints across the entire map (every 2m)
    all_wps = carla_map.generate_waypoints(2.0)
    print(f"  Generated {len(all_wps)} total waypoints")

    # 3. Separate into junction vs road segment waypoints
    road_segments = {}  # (road_id, lane_id) -> [waypoints]
    for w in all_wps:
        if w.is_junction:
            continue
        key = (w.road_id, w.lane_id)
        if key not in road_segments:
            road_segments[key] = []
        road_segments[key].append(w)

    # Sort each segment by s-parameter
    for key in road_segments:
        road_segments[key].sort(key=lambda w: w.s)

    print(f"  Found {len(road_segments)} road segment lanes")

    # 4. Build intersections
    intersections = []

    for j_id, junction in junctions.items():
        bb = junction.bounding_box
        ref_lat, ref_lon = carla_to_wgs84(bb.location)

        lane_set = []
        lane_id_counter = 1

        # 4a. Get internal junction lanes
        try:
            junction_wps = junction.get_waypoints(carla.LaneType.Driving)
            junction_lanes = {}
            for wp_pair in junction_wps:
                for w in wp_pair:
                    key = (w.road_id, w.lane_id)
                    if key not in junction_lanes:
                        junction_lanes[key] = []
                    junction_lanes[key].append(w)

            for key in junction_lanes:
                junction_lanes[key].sort(key=lambda w: w.s)

            for (r_id, l_id), wps in junction_lanes.items():
                if len(wps) < 2:
                    continue
                entry = build_lane_entry(lane_id_counter, l_id, wps, ref_lat, ref_lon)
                if entry:
                    lane_set.append(entry)
                    lane_id_counter += 1
        except Exception as e:
            print(f"  ⚠️  Junction {j_id} internal lanes error: {e}")

        # 4b. Get approach/departure road segments near this junction
        approach_range = max(bb.extent.x, bb.extent.y) + 40.0

        for (r_id, l_id), wps in road_segments.items():
            if len(wps) < 3:
                continue

            # Check if any endpoint is close to the junction center
            d_first = wps[0].transform.location.distance(bb.location)
            d_last = wps[-1].transform.location.distance(bb.location)

            if min(d_first, d_last) < approach_range:
                entry = build_lane_entry(lane_id_counter, l_id, wps, ref_lat, ref_lon)
                if entry:
                    lane_set.append(entry)
                    lane_id_counter += 1

        # 4c. Build connectsTo for ingress->egress lane pairs
        ingress_lanes = [l for l in lane_set if l["laneAttributes"]["directionalUse"] == "000000000000000010"]
        egress_lanes = [l for l in lane_set if l["laneAttributes"]["directionalUse"] == "000000000000000100"]

        for ing in ingress_lanes:
            if egress_lanes:
                # Connect to first available egress lane (simplified)
                ing["connectsTo"] = [{
                    "connectingLane": {
                        "lane": egress_lanes[0]["laneID"],
                        "maneuver": "000000000000001000"  # straightAhead
                    }
                }]

        if not lane_set:
            continue

        intersection = {
            "id": {"region": 0, "id": j_id % 65535},
            "revision": 1,
            "refPoint": {
                "lat": int(ref_lat * 10000000),
                "long": int(ref_lon * 10000000),
                "elevation": int(bb.location.z * 10)
            },
            "laneWidth": 300,
            "speedLimits": [{"type": "vehicleMaxSpeed", "speed": 894}],
            "laneSet": lane_set
        }

        intersections.append(intersection)
        print(f"  ✓ Junction {j_id}: {len(lane_set)} lanes (ref: {ref_lat:.6f}, {ref_lon:.6f})")

    # 5. Assemble final J2735 MAP payload
    map_payload = {
        "mapData": {
            "messageId": 18,
            "value": {
                "msgIssueRevision": 1,
                "layerType": "intersectionData",
                "layerID": 0,
                "intersections": intersections
            }
        }
    }

    print(f"\n  ✅ Total: {len(intersections)} intersections extracted")
    return map_payload

# ==============================================
# MAIN
# ==============================================

def main():
    parser = argparse.ArgumentParser(description="CARLA Full Topology Extractor - Conecta 2030")
    parser.add_argument("--host", default="127.0.0.1", help="CARLA server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=2000, help="CARLA server port (default: 2000)")
    parser.add_argument("--interval", type=float, default=10.0, help="Seconds between extractions (default: 10)")
    parser.add_argument("--output", default=None, help="Custom output path (default: auto-detect)")
    args = parser.parse_args()

    # Determine output path: same folder as script -> map_cruzamento.json
    if args.output:
        output_path = args.output
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, "map_cruzamento.json")

    print(f"🔌 Connecting to CARLA at {args.host}:{args.port}...")

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(10.0)
        world = client.get_world()
        carla_map = world.get_map()
        print(f"✅ Connected! Map: {carla_map.name}")
    except Exception as e:
        print(f"❌ Failed to connect to CARLA: {e}")
        print("Make sure the CARLA simulator is running.")
        return

    print(f"\n🔄 Running continuously. Extracting every {args.interval}s.")
    print(f"📁 Output: {output_path}")
    print(f"   Press Ctrl+C to stop.\n")

    revision = 1
    try:
        while True:
            try:
                # Re-fetch world in case the map changed
                world = client.get_world()
                carla_map = world.get_map()
            except Exception:
                print("⚠️  Lost connection to CARLA, retrying in 3s...")
                time.sleep(3)
                continue

            map_payload = build_full_topology(carla_map)
            map_payload["mapData"]["value"]["msgIssueRevision"] = revision % 128

            with open(output_path, 'w') as f:
                json.dump(map_payload, f, indent=4)

            size_kb = os.path.getsize(output_path) / 1024
            n_intersections = len(map_payload["mapData"]["value"]["intersections"])
            total_lanes = sum(len(i["laneSet"]) for i in map_payload["mapData"]["value"]["intersections"])

            print(f"\n💾 Saved revision #{revision} to {os.path.basename(output_path)}")
            print(f"   {n_intersections} intersections, {total_lanes} total lanes, {size_kb:.1f} KB")
            print(f"   Next extraction in {args.interval}s...\n")

            revision += 1
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print(f"\n\n🛑 Stopped. Last output: {output_path}")
        print(f"   {revision - 1} revisions captured.")

if __name__ == '__main__':
    main()
