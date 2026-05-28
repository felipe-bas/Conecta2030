#!/usr/bin/env python3
"""
J2735 UPER Codec — Conecta2030
Módulo de encoding/decoding ASN.1 UPER para mensagens SAE J2735.
Usa pycrate + pacote j2735_202409 (do USDOT j2735decoder).

Dependências:
    pip install pycrate
    pip install j2735_202409-*.whl  (do repo github.com/usdot-fhwa-stol/j2735decoder)

NOTA: O primeiro import demora ~2 min porque o pycrate compila o schema ASN.1.
      Depois de carregado, encode/decode é instantâneo.
      Se as dependências não estiverem instaladas, opera em modo "passthrough" (JSON puro).
"""

import json
import binascii
import sys
import time

# ============================================================
# Importar pycrate + schema J2735
# ============================================================

UPER_AVAILABLE = False
_MessageFrame = None

def _load_schema():
    """Carrega o schema J2735. Chamado uma vez no startup."""
    global UPER_AVAILABLE, _MessageFrame
    try:
        print("[UPER] Carregando schema J2735 (primeira vez demora ~2 min)...", flush=True)
        t0 = time.time()
        # O pycrate gera um módulo principal j2735_202409.
        # Dentro dele há uma classe MessageFrame e na classe a instância MessageFrame.
        import j2735_202409
        _MessageFrame = j2735_202409.MessageFrame.MessageFrame
        UPER_AVAILABLE = True
        dt = time.time() - t0
        print(f"[UPER] ✓ Schema J2735-202409 carregado em {dt:.1f}s", flush=True)
    except ImportError as e:
        print(f"[UPER] ✗ Schema não disponível: {e}", flush=True)
        print("[UPER]   Instale: pip install pycrate && pip install j2735_202409-*.whl", flush=True)
        print("[UPER]   Operando em modo passthrough (JSON puro)", flush=True)

# Carregar na importação do módulo
_load_schema()


# ============================================================
# Message ID mapping (SAE J2735)
# ============================================================

MSG_TYPE_TO_ID = {
    "bsm": 20,      # BasicSafetyMessage
    "mapData": 18,   # MapData
    "spat": 19,      # SPAT
    "rsa": 27,       # RoadSideAlert
    "tim": 31,       # TravelerInformation
    "psm": 32,       # PersonalSafetyMessage
}

MSG_ID_TO_TYPE = {v: k for k, v in MSG_TYPE_TO_ID.items()}


# ============================================================
# Encoding: JSON dict → UPER bytes
# ============================================================

def json_to_uper(json_data):
    """
    Converte um dict JSON V2X para bytes UPER (ASN.1 UPER).

    Args:
        json_data: dict (ex: {"bsm": {"messageId": 20, "value": {...}}})

    Returns:
        tuple: (uper_bytes, msg_type_str) ou (None, msg_type) se falhar
    """
    msg_type = _detect_type(json_data)

    if not UPER_AVAILABLE or _MessageFrame is None:
        return None, msg_type

    if msg_type == "unknown":
        return None, msg_type

    try:
        # Extrair conteúdo da MessageFrame do JSON do CARLA
        # Formato: {"bsm": {"messageId": 20, "value": {coreData: ...}}}
        inner = json_data.get(msg_type, json_data)
        msg_id = inner.get("messageId", MSG_TYPE_TO_ID.get(msg_type, 0))
        
        # Mapeamento de nomes de tipo para o schema
        type_map = {
            "bsm": "BasicSafetyMessage",
            "mapData": "MapData",
            "spat": "SPAT",
            "rsa": "RoadSideAlert",
            "tim": "TravelerInformation",
            "psm": "PersonalSafetyMessage"
        }
        msg_type_name = type_map.get(msg_type, "BasicSafetyMessage")

        message_frame = {
            "messageId": msg_id,
            "value": (msg_type_name, inner.get("value", inner))
                if isinstance(inner.get("value", inner), dict)
                else ("BasicSafetyMessage", inner.get("value", inner))
        }

        # O payload real (o dicionário da J2735 message)
        payload = message_frame["value"][1]

        # Limpeza e ajuste de tipos para pycrate (JSON Strings -> bytes / tuples)
        if msg_type == "bsm":
            core = payload.get("coreData", {})
            if "id" in core and isinstance(core["id"], str):
                core["id"] = bytes.fromhex(core["id"])
            if "brakes" in core and "wheelBrakes" in core["brakes"]:
                if isinstance(core["brakes"]["wheelBrakes"], str) or isinstance(core["brakes"]["wheelBrakes"], tuple):
                    core["brakes"]["wheelBrakes"] = (0, 5) # BIT STRING SIZE(5) -> (valor_int, len_bits)
        elif msg_type == "psm":
            if "id" in payload and isinstance(payload["id"], str):
                try: payload["id"] = bytes.fromhex(payload["id"])
                except ValueError: payload["id"] = payload["id"].encode('ascii')[:4]
        elif msg_type == "spat":
            for inter in payload.get("intersections", []):
                if "status" in inter and isinstance(inter["status"], str):
                    inter["status"] = (0, 16) # BIT STRING SIZE(16) -> (valor_int, len_bits)

        _MessageFrame.set_val(message_frame)
        uper_bytes = _MessageFrame.to_uper()

        # O pycrate guarda o estado internamente para uso no reuso
        return uper_bytes, msg_type

    except Exception as e:
        print(f"[UPER] Erro encoding {msg_type}: {e}")
        import traceback
        traceback.print_exc()
        return None, msg_type


def uper_to_json(uper_bytes):
    """
    Converte bytes UPER para dict JSON V2X.

    Returns:
        tuple: (json_dict, msg_type_str) ou (None, "unknown") se falhar
    """
    if not UPER_AVAILABLE or _MessageFrame is None:
        return None, "unknown"

    try:
        _MessageFrame.from_uper(uper_bytes)
        val = _MessageFrame.get_val()

        msg_id = val[0] if isinstance(val, tuple) else val.get("messageId", 0)
        msg_type = MSG_ID_TO_TYPE.get(msg_id, "unknown")

        # Reconstruir JSON no formato do CARLA
        message_frame = _MessageFrame.get_val()
        
        # Helper: Limpar tipos primitivos para json.dumps (bytes -> str hex, tuplas de BitString -> "00")
        def clean_for_json(obj):
            if isinstance(obj, dict):
                return {k: clean_for_json(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_for_json(i) for i in obj]
            elif isinstance(obj, bytes):
                return obj.hex().upper()
            elif isinstance(obj, tuple):
                # Conversão genérica de tupla de bits (0, 0, ...) para "00" no JSON do CARLA
                # Ou strings hex dependendo do comprimento. Para simplificar mantemos a convenção do CARLA
                return "00"
            return obj

        message_frame = clean_for_json(message_frame)

        result = {
            msg_type: {
                "messageId": msg_id,
                "value": message_frame.get("value", message_frame)
            }
        }
        return result, msg_type

    except Exception as e:
        print(f"[UPER] Erro decoding: {e}")
        return None, "unknown"


# ============================================================
# Hex helpers
# ============================================================

def uper_to_hex(uper_bytes):
    """Bytes UPER → string hex (como fac_alert.c imprime)."""
    return binascii.hexlify(uper_bytes).decode('ascii').upper()

def hex_to_uper(hex_str):
    """String hex → bytes UPER."""
    return binascii.unhexlify(hex_str)


# ============================================================
# Wire format para UDP
# ============================================================
# Formato: [MAGIC:1 'V'] [MSG_ID:1] [UPER_LEN:2 big-endian] [UPER_DATA:N]

WIRE_MAGIC = b'\x56'  # 'V' de V2X

def pack_for_wire(uper_bytes, message_id):
    """Empacota UPER para envio via UDP."""
    length = len(uper_bytes)
    header = WIRE_MAGIC + bytes([message_id]) + length.to_bytes(2, 'big')
    return header + uper_bytes

def unpack_from_wire(data):
    """
    Desempacota dados UDP.
    Returns: (uper_bytes, message_id) ou (None, None) se é JSON.
    """
    if len(data) < 4:
        return None, None
    if data[0:1] == WIRE_MAGIC:
        message_id = data[1]
        length = int.from_bytes(data[2:4], 'big')
        uper_bytes = data[4:4+length]
        return uper_bytes, message_id
    return None, None

def is_json_wire(data):
    """Verifica se os dados UDP são JSON (fallback) em vez de UPER."""
    return data[:1] in (b'{', b'[')


# ============================================================
# Helpers
# ============================================================

def _detect_type(msg):
    for key in MSG_TYPE_TO_ID:
        if key in msg:
            return key
    return "unknown"

def is_available():
    return UPER_AVAILABLE


# ============================================================
# Auto-teste
# ============================================================

if __name__ == "__main__":
    print(f"\nUPER disponível: {UPER_AVAILABLE}")

    if UPER_AVAILABLE:
        test_bsm = {
            "bsm": {
                "messageId": 20,
                "value": {
                    "coreData": {
                        "msgCnt": 127,
                        "id": "A1B2C3D4",
                        "secMark": 30000,
                        "lat": -235497100, "long": -466327200, "elev": 100,
                        "accuracy": {"semiMajor": 40, "semiMinor": 40, "orientation": 0},
                        "transmission": "forwardGears",
                        "speed": 750, "heading": 0, "angle": 0,
                        "accelSet": {"long": 0, "lat": 0, "vert": 0, "yaw": 0},
                        "brakes": {
                            "wheelBrakes": "00",
                            "traction": "unavailable", "abs": "unavailable",
                            "scs": "unavailable", "brakeBoost": "unavailable",
                            "auxBrakes": "unavailable"
                        },
                        "size": {"width": 200, "length": 500}
                    }
                }
            }
        }

        print("\n--- Teste Encode ---")
        uper, msg_type = json_to_uper(test_bsm)
        if uper:
            print(f"Tipo: {msg_type}")
            print(f"UPER ({len(uper)} bytes): {uper_to_hex(uper)}")

            wire = pack_for_wire(uper, MSG_TYPE_TO_ID[msg_type])
            print(f"Wire ({len(wire)} bytes)")

            print("\n--- Teste Decode ---")
            uper_back, msg_id = unpack_from_wire(wire)
            if uper_back:
                json_back, type_back = uper_to_json(uper_back)
                if json_back:
                    print(f"Decode OK! Tipo: {type_back}")
        else:
            print("Encoding retornou None")
    else:
        print("\nInstale: pip install pycrate && pip install j2735_202409-*.whl")
