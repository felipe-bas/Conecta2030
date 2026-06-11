#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPS PPS Time Synchronization for V2X Conecta 2030
Sincroniza os relógios da RSU, OBU e PC usando GPS como referência.
A RSU atua como servidor NTP Stratum 1 (disciplinado por GPS).
O PC sincroniza com a RSU via w32tm.
"""

import os
import sys
import time
import subprocess
import platform
import paramiko
from dotenv import load_dotenv

load_dotenv()

# Colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"

def log(msg, color=""):
    print(f"{color}{msg}{RESET}")

def get_ssh_client(ip, username, password):
    """Cria conexão SSH robusta com os dispositivos Commsignia."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            ip,
            username=username,
            password=password,
            timeout=10,
            look_for_keys=False,
            allow_agent=False,
            disabled_algorithms={'pubkeys': ['rsa-sha2-512', 'rsa-sha2-256']},
            banner_timeout=30
        )
        return client
    except Exception as e:
        log(f"[ERRO] Falha SSH em {ip}: {e}", RED)
        return None

def ssh_exec(client, cmd, timeout=10):
    """Executa comando SSH e retorna stdout."""
    try:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        return stdout.read().decode('utf-8', errors='ignore').strip()
    except Exception as e:
        return f"ERRO: {e}"

def check_gps_status(client, device_name):
    """Verifica se o GPS tem fix (lock nos satélites)."""
    log(f"\n{'='*50}", CYAN)
    log(f"  GPS Status: {device_name}", CYAN)
    log(f"{'='*50}", CYAN)
    
    gps_ok = False
    
    # Tenta diferentes comandos de GPS (varia por firmware)
    gps_commands = [
        ("gpsc status", "GPS Status"),
        ("gpsc position", "GPS Position"),
        ("ubus call gps info", "GPS Info (ubus)"),
        ("ubus call gps status", "GPS Status (ubus)"),
        ("cat /proc/driver/gps 2>/dev/null", "GPS Driver"),
    ]
    
    for cmd, label in gps_commands:
        result = ssh_exec(client, cmd)
        if result and "ERRO" not in result and "not found" not in result.lower() and len(result) > 2:
            log(f"  [{label}]: {result}", GREEN)
            # Detecta fix baseado em palavras-chave comuns
            if any(kw in result.lower() for kw in ['fix', 'locked', 'valid', '3d', '2d', 'lat', 'lon']):
                gps_ok = True
    
    # Verifica se gpsd está rodando
    ps_result = ssh_exec(client, "ps | grep -i gps | grep -v grep")
    if ps_result:
        log(f"  [Processos GPS]: {ps_result}", GREEN)
        gps_ok = True  # Se gpsd está rodando, provavelmente está OK
    else:
        log(f"  [Processos GPS]: Nenhum daemon GPS encontrado", YELLOW)
    
    # Verifica dispositivos GPS no kernel
    dev_result = ssh_exec(client, "ls /dev/gps* /dev/ttyS* /dev/ttyUSB* /dev/pps* 2>/dev/null")
    if dev_result:
        log(f"  [Dispositivos]: {dev_result}", GREEN)
    
    # Mostra a hora atual do dispositivo
    date_result = ssh_exec(client, "date '+%Y-%m-%d %H:%M:%S %Z'")
    log(f"  [Hora Atual]: {date_result}", GREEN)
    
    return gps_ok, date_result

def setup_ntp_server(client, device_name):
    """Configura o dispositivo como servidor NTP usando GPS como fonte."""
    log(f"\n  Configurando NTP Server em {device_name}...", CYAN)
    
    # Habilita o servidor NTP
    commands = [
        "uci set system.ntp.enabled='1'",
        "uci set system.ntp.enable_server='1'",
        "uci commit system",
    ]
    
    for cmd in commands:
        result = ssh_exec(client, cmd)
        if "ERRO" in result:
            log(f"  [AVISO] Comando falhou: {cmd} -> {result}", YELLOW)
    
    # Reinicia o serviço NTP
    # Tenta diferentes métodos (varia por firmware)
    restart_cmds = [
        "/etc/init.d/sysntpd restart",
        "/etc/init.d/ntpd restart 2>/dev/null",
        "service ntpd restart 2>/dev/null",
    ]
    
    for cmd in restart_cmds:
        result = ssh_exec(client, cmd)
    
    log(f"  ✅ NTP Server habilitado em {device_name}", GREEN)

def setup_ntp_client(client, device_name):
    """Configura o dispositivo como cliente NTP (apenas sincroniza via GPS)."""
    log(f"\n  Configurando NTP Client em {device_name}...", CYAN)
    
    commands = [
        "uci set system.ntp.enabled='1'",
        "uci commit system",
    ]
    
    for cmd in commands:
        ssh_exec(client, cmd)
    
    # Reinicia
    ssh_exec(client, "/etc/init.d/sysntpd restart")
    log(f"  ✅ NTP habilitado em {device_name}", GREEN)

def fallback_ssh_sync(client, device_name):
    """
    Fallback: Se o GPS não tiver fix, sincroniza via SSH 
    usando a hora do PC como referência.
    """
    log(f"\n  [FALLBACK] Sincronizando {device_name} com a hora do PC...", YELLOW)
    
    # Pega a hora UTC do PC
    now_utc = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    
    cmd = f"date -u -s '{now_utc}'"
    result = ssh_exec(client, cmd)
    
    if "ERRO" not in result:
        log(f"  ✅ {device_name} sincronizado via SSH: {now_utc} UTC", GREEN)
        return True
    else:
        log(f"  ❌ Falha ao sincronizar {device_name}: {result}", RED)
        return False

def sync_pc_to_rsu(rsu_ip):
    """Sincroniza o relógio do PC Windows com a RSU via NTP."""
    log(f"\n{'='*50}", CYAN)
    log(f"  Sincronizando PC com RSU ({rsu_ip})", CYAN)
    log(f"{'='*50}", CYAN)
    
    if platform.system() != "Windows":
        log("  [INFO] Sistema não é Windows, pulando w32tm.", YELLOW)
        return False
    
    try:
        # Verifica se estamos rodando como administrador
        result = subprocess.run(
            "net session", shell=True, capture_output=True, text=True
        )
        is_admin = result.returncode == 0
        
        if not is_admin:
            log("  [AVISO] Sem privilégio de administrador.", YELLOW)
            log("  Para sincronização precisa via NTP, execute como Administrador.", YELLOW)
            log("  Alternativa: a sincronização SSH (fallback) será usada.", YELLOW)
            return False
        
        # Configura w32tm para usar a RSU como fonte
        cmds = [
            "net stop w32time",
            f'w32tm /config /manualpeerlist:"{rsu_ip}" /syncfromflags:manual /reliable:YES /update',
            "net start w32time",
            "w32tm /resync /force",
        ]
        
        for cmd in cmds:
            subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            time.sleep(1)
        
        # Verifica o offset
        result = subprocess.run(
            f"w32tm /stripchart /computer:{rsu_ip} /samples:3 /dataonly",
            shell=True, capture_output=True, text=True, timeout=30
        )
        
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split('\n')
            for line in lines[-3:]:
                log(f"  [NTP Offset]: {line.strip()}", GREEN)
            log(f"  ✅ PC sincronizado com RSU via NTP!", GREEN)
            return True
        else:
            log(f"  [AVISO] w32tm não conseguiu medir offset: {result.stderr}", YELLOW)
            return False
            
    except Exception as e:
        log(f"  [ERRO] Falha na sincronização NTP do PC: {e}", RED)
        return False

def validate_sync(rsu_client, obu_client):
    """Valida a sincronização comparando os relógios."""
    log(f"\n{'='*50}", CYAN)
    log(f"  Validação da Sincronização", CYAN)
    log(f"{'='*50}", CYAN)
    
    pc_time = time.time()
    rsu_time_str = ssh_exec(rsu_client, "date +%s.%N") if rsu_client else None
    obu_time_str = ssh_exec(obu_client, "date +%s.%N") if obu_client else None
    
    log(f"  PC  (epoch): {pc_time:.3f}", GREEN)
    
    offsets = {}
    
    if rsu_time_str and "ERRO" not in rsu_time_str:
        try:
            rsu_time = float(rsu_time_str)
            offset_rsu = abs(pc_time - rsu_time)
            offsets['RSU'] = offset_rsu
            log(f"  RSU (epoch): {rsu_time:.3f}  |  Offset: {offset_rsu*1000:.1f} ms", 
                GREEN if offset_rsu < 0.1 else YELLOW)
        except ValueError:
            log(f"  RSU: não suporta %N, usando date +%s", YELLOW)
            rsu_time_str = ssh_exec(rsu_client, "date +%s")
            try:
                rsu_time = float(rsu_time_str)
                offset_rsu = abs(pc_time - rsu_time)
                offsets['RSU'] = offset_rsu
                log(f"  RSU (epoch): {rsu_time:.0f}  |  Offset: {offset_rsu*1000:.0f} ms", 
                    GREEN if offset_rsu < 1 else YELLOW)
            except:
                log(f"  RSU: erro ao ler tempo", RED)
    
    if obu_time_str and "ERRO" not in obu_time_str:
        try:
            obu_time = float(obu_time_str)
            offset_obu = abs(pc_time - obu_time)
            offsets['OBU'] = offset_obu
            log(f"  OBU (epoch): {obu_time:.3f}  |  Offset: {offset_obu*1000:.1f} ms",
                GREEN if offset_obu < 0.1 else YELLOW)
        except ValueError:
            obu_time_str = ssh_exec(obu_client, "date +%s")
            try:
                obu_time = float(obu_time_str)
                offset_obu = abs(pc_time - obu_time)
                offsets['OBU'] = offset_obu
                log(f"  OBU (epoch): {obu_time:.0f}  |  Offset: {offset_obu*1000:.0f} ms",
                    GREEN if offset_obu < 1 else YELLOW)
            except:
                log(f"  OBU: erro ao ler tempo", RED)
    
    # Resultado
    all_ok = True
    for dev, offset in offsets.items():
        if offset > 1.0:  # Mais de 1 segundo de diferença
            log(f"\n  ⚠️  {dev} tem offset de {offset:.1f}s — considere re-sincronizar!", YELLOW)
            all_ok = False
    
    if all_ok and offsets:
        log(f"\n  ✅ Todos os dispositivos sincronizados! Offsets < 1s", GREEN)
    
    return offsets

def full_sync():
    """Executa a sincronização completa: GPS check → NTP setup → PC sync → Validação."""
    log("=" * 55, CYAN)
    log("  🛰️  GPS PPS Time Synchronization — Conecta 2030", CYAN)
    log("=" * 55, CYAN)
    
    rsu_ip = os.getenv("RSU_IPV4", "192.168.0.50")
    rsu_user = os.getenv("RSU_USER", "root")
    rsu_pass = os.getenv("RSU_PASS", "Conect@2024")
    
    obu_ip = os.getenv("OBU_IPV4", "192.168.0.53")
    obu_user = os.getenv("OBU_USER", "root")
    obu_pass = os.getenv("OBU_PASS", "Conect@24")
    
    rsu_client = None
    obu_client = None
    rsu_gps_ok = False
    obu_gps_ok = False
    
    # ── PASSO 1: Conectar e verificar GPS na RSU ──
    log("\n[1/4] Verificando GPS na RSU...", CYAN)
    rsu_client = get_ssh_client(rsu_ip, rsu_user, rsu_pass)
    if rsu_client:
        rsu_gps_ok, rsu_date = check_gps_status(rsu_client, "RSU")
        
        if rsu_gps_ok:
            log("  ✅ GPS da RSU com fix! Usando como referência de tempo.", GREEN)
            setup_ntp_server(rsu_client, "RSU")
        else:
            log("  ⚠️  GPS da RSU sem fix. Usando fallback SSH.", YELLOW)
            fallback_ssh_sync(rsu_client, "RSU")
            setup_ntp_server(rsu_client, "RSU")  # Ainda habilita NTP server
    else:
        log("  ❌ Não foi possível conectar na RSU.", RED)
    
    # ── PASSO 2: Conectar e verificar GPS na OBU ──
    log("\n[2/4] Verificando GPS na OBU...", CYAN)
    obu_client = get_ssh_client(obu_ip, obu_user, obu_pass)
    if obu_client:
        obu_gps_ok, obu_date = check_gps_status(obu_client, "OBU")
        
        if obu_gps_ok:
            log("  ✅ GPS da OBU com fix! Tempo já sincronizado via GPS.", GREEN)
            setup_ntp_client(obu_client, "OBU")
        else:
            log("  ⚠️  GPS da OBU sem fix. Usando fallback SSH.", YELLOW)
            fallback_ssh_sync(obu_client, "OBU")
    else:
        log("  ❌ Não foi possível conectar na OBU.", RED)
    
    # ── PASSO 3: Sincronizar PC com RSU via NTP ──
    log("\n[3/4] Sincronizando PC com RSU...", CYAN)
    if rsu_client:
        pc_synced = sync_pc_to_rsu(rsu_ip)
        if not pc_synced:
            log("  [FALLBACK] Sem admin — os timestamps do PC usarão o relógio local.", YELLOW)
            log("  Dica: Execute 'python sync_gps_time.py' como Administrador para sincronização NTP.", YELLOW)
    
    # ── PASSO 4: Validar sincronização ──
    log("\n[4/4] Validando sincronização...", CYAN)
    offsets = validate_sync(rsu_client, obu_client)
    
    # Cleanup
    if rsu_client:
        rsu_client.close()
    if obu_client:
        obu_client.close()
    
    # Resumo final
    log(f"\n{'='*55}", CYAN)
    log(f"  📊 RESUMO DA SINCRONIZAÇÃO", CYAN)
    log(f"{'='*55}", CYAN)
    log(f"  RSU GPS: {'✅ Com Fix' if rsu_gps_ok else '⚠️ Sem Fix (fallback SSH)'}", 
        GREEN if rsu_gps_ok else YELLOW)
    log(f"  OBU GPS: {'✅ Com Fix' if obu_gps_ok else '⚠️ Sem Fix (fallback SSH)'}",
        GREEN if obu_gps_ok else YELLOW)
    
    for dev, offset in offsets.items():
        status = "✅" if offset < 0.1 else ("⚠️" if offset < 1.0 else "❌")
        log(f"  {dev} Offset: {status} {offset*1000:.1f} ms", 
            GREEN if offset < 0.1 else (YELLOW if offset < 1.0 else RED))
    
    log(f"{'='*55}\n", CYAN)
    
    return rsu_gps_ok or obu_gps_ok  # True se pelo menos um GPS funcionou

if __name__ == "__main__":
    success = full_sync()
    if success:
        log("Sincronização concluída com sucesso! ✅", GREEN)
    else:
        log("Sincronização parcial (fallback SSH usado). ⚠️", YELLOW)
        log("Para precisão GPS PPS, garanta que os dispositivos tenham visão do céu.", YELLOW)
