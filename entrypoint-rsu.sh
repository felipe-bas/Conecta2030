#!/bin/bash
set -e

# Configurar rota para o IP PDU do UE (ex. 10.45.0.3) via UPF (ex. 172.22.0.8)
if [ -n "$UPF_IP" ] && [ -n "$OBU_SUBNET" ]; then
    echo "[Entrypoint] Adding route to $OBU_SUBNET via UPF $UPF_IP..."
    ip route add "$OBU_SUBNET" via "$UPF_IP" || true
fi

# Executar o processo principal RSU Forwarder
echo "[Entrypoint] Starting RSU Forwarder..."
exec python3 /app/rsu_5g_forwarder.py "$@"
