#!/usr/bin/env python3
"""
V2X 5G Slicing Test System (Auto-Deploy & Simulate) — IPv6 Dual-Stack
Conecta 2030

Automação completa para testar o Path 2 (5G) localmente.
Faz toda a checagem de infraestrutura (requisitos 3.1 a 3.4 do guia):
- Checa instalação PyCrate / j2735decoder
- Checa a PDU Session (IPv4 192.168.200.X + IPv6 fd00:5678::X)
- Configura o overlay IPv6 no uesimtun1
- Configura NAT66 via ipv6_nat_manager.py
- Configura a rota sudo no host (IPv4 + IPv6)
E no final, simula em 3 janelas interativas.
"""

import os
import sys
import time
import json
import socket
import argparse
import platform
import subprocess
import threading
import re

# Configurações padrão
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
FORWARDER_PORT = 9090
TABLET_PORT = 8081
SUDO_PASS = "ghf05042004"  # Memorizada

# ANSI Colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}")

def set_terminal_title(title):
    if platform.system().lower() == "windows":
        os.system(f"title {title}")
    else:
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()

# ==========================================
# SETUP AUTOMATION
# ==========================================

def run_sudo_cmd(cmd):
    """Roda comando com sudo silenciosamente injetando a senha."""
    # Wraps in bash -c to keep && inside a single sudo process
    safe_cmd = cmd.replace("'", "'\\''")
    full = f"echo '{SUDO_PASS}' | sudo -S bash -c '{safe_cmd}'"
    return subprocess.run(full, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

def setup_infrastructure():
    log("============================================", GREEN)
    log("  5G V2X Test System (Setup Automation)", GREEN)
    log("============================================", GREEN)

    # 1. Checar Pycrate/J2735
    log("\n[1/4] Verificando dependências Python (UPER)...", YELLOW)
    try:
        import pycrate_core
        import j2735_202409
        log("  ✓ pycrate e j2735_202409 instalados.", GREEN)
    except ImportError:
        log("  ✗ Dependências ausentes! Executando instalação automática...", RED)
        os.system("pip3 install pycrate --break-system-packages")
        if not os.path.exists("/tmp/j2735decoder"):
            os.system("git clone --depth 1 https://github.com/usdot-fhwa-stol/j2735decoder.git /tmp/j2735decoder")
        os.system("pip3 install /tmp/j2735decoder/wheels/j2735_202409-0.1.0-py3-none-any.whl --break-system-packages")
        log("  ✓ Instalação concluída.", GREEN)

    # 2. Inicializar Cluster Docker
    log("\n[2/5] Orquestrando Cluster 5G Open5GS Isolado...", YELLOW)
    core_restarted = False
    core_running = run_sudo_cmd("docker inspect -f '{{.State.Running}}' open5gs-upf")
    if core_running.returncode != 0 or 'true' not in core_running.stdout:
        log("  [+] Subindo Open5GS Core (sa-deploy.yaml)...", CYAN)
        run_sudo_cmd("cd /home/gusfravolini/Open5gs && docker compose -f sa-deploy.yaml up -d")
        core_restarted = True
        time.sleep(5)
        
    gnb_running = run_sudo_cmd("docker inspect -f '{{.State.Running}}' nr_gnb")
    if gnb_running.returncode != 0 or 'true' not in gnb_running.stdout:
        log("  [+] Subindo gNodeB (nr-gnb.yaml)...", CYAN)
        run_sudo_cmd("cd /home/gusfravolini/Open5gs && docker compose -f nr-gnb.yaml up -d")
        time.sleep(3)
    elif core_restarted:
        log("  [+] Reiniciando gNodeB (reconectar NGAP ao AMF)...", CYAN)
        run_sudo_cmd("docker restart nr_gnb")
        time.sleep(3)

    log("  [+] Derrubando UEs antigos para alijamento de rede...", CYAN)
    run_sudo_cmd("docker rm -f nr_ue")
    log("  [+] Subindo UE Slicing Isolado (nr-ue-slicing.yaml)...", CYAN)
    run_sudo_cmd("cd /home/gusfravolini/Open5gs && docker compose -f nr-ue-slicing.yaml up -d")
    log("  [Zzz] Aguardando UERANSIM estabilizar sessão PDU (15s)...", YELLOW)
    time.sleep(15)

    # 3. Descobrir IP do UE na PDU Session V2X (uesimtun1 = SST=2)
    log("\n[3/6] Buscando PDU Session V2X no container 'nr_ue'...", YELLOW)

    # --- IPv4 Discovery ---
    res = run_sudo_cmd("docker exec nr_ue ip -4 addr show")
    if res.returncode != 0:
        log("  ✗ Erro ao acessar container nr_ue.", RED)
        log("    O UE pode não ter estabelecido a PDU Session.", RED)
        sys.exit(1)

    ip_match = re.search(r'inet\s+(192\.168\.200\.\d+)', res.stdout)
    if not ip_match:
        res2 = run_sudo_cmd("docker exec nr_ue ip -4 addr show uesimtun1")
        ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', res2.stdout) if res2.returncode == 0 else None
    if not ip_match:
        log(f"  ✗ Nenhuma interface V2X IPv4 (192.168.200.x) encontrada.", RED)
        sys.exit(1)

    obu_ip_v4 = ip_match.group(1)
    log(f"  ✓ IPv4 V2X do UE: {obu_ip_v4}", GREEN)

    # --- IPv6 Discovery ---
    log("\n[3b/6] Buscando IPv6 overlay no UE (fd00:5678::/64)...", YELLOW)
    res6 = run_sudo_cmd("docker exec nr_ue ip -6 addr show dev uesimtun1 scope global")
    obu_ip_v6 = None
    if res6.returncode == 0 and res6.stdout:
        ipv6_match = re.search(r'inet6\s+(fd00:5678::[^\s/]+)', res6.stdout)
        if ipv6_match:
            obu_ip_v6 = ipv6_match.group(1)
            log(f"  ✓ IPv6 V2X do UE: {obu_ip_v6}", GREEN)
        else:
            log("  ⚠ IPv6 overlay não encontrado em uesimtun1 (script init pode estar rodando)", YELLOW)
    else:
        log("  ⚠ uesimtun1 sem IPv6 (overlay será configurado pelo init script)", YELLOW)

    if not obu_ip_v6:
        # Try mDNS resolution first (if Avahi is available)
        try:
            import ipv6_nat_manager as nat_mgr
            resolved = nat_mgr.resolve_hostname("obu-v2x")
            if resolved and resolved != "fd00:5678::2":
                obu_ip_v6 = resolved
                log(f"  ✓ IPv6 via mDNS: {obu_ip_v6}", GREEN)
        except Exception:
            pass

    if not obu_ip_v6:
        obu_ip_v6 = "fd00:5678::2"  # default do overlay
        log(f"  Usando IPv6 default: {obu_ip_v6}", CYAN)

    # 4. Rota IPv4
    upf_ip = run_sudo_cmd("docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' open5gs-upf").stdout.strip()
    if not upf_ip: upf_ip = "172.22.0.8"

    subnet = obu_ip_v4.rsplit('.', 1)[0] + ".0/24"
    log(f"\n[4/6] Configurando roteamento IPv4 ({subnet}) via UPF ({upf_ip})...", YELLOW)
    route_check = run_sudo_cmd(f"ip route show {subnet}")
    if f"{subnet} via {upf_ip}" in route_check.stdout:
        log("  ✓ Rota IPv4 já configurada.", GREEN)
    else:
        run_sudo_cmd(f"ip route add {subnet} via {upf_ip}")
        log("  ✓ Rota IPv4 adicionada.", GREEN)

    # 5. Setup NAT66 + Rota IPv6
    log(f"\n[5/6] Configurando NAT66 e rota IPv6 (fd00:5678::/64)...", YELLOW)
    try:
        import ipv6_nat_manager
        ipv6_nat_manager.setup_nat()
        ipv6_nat_manager.inject_route()
        log("  ✓ NAT66 e rota IPv6 configurados.", GREEN)

        # Start mDNS watcher in background thread
        log("  [+] Iniciando mDNS publisher (obu-v2x.local)...", CYAN)
        mdns_thread = threading.Thread(
            target=ipv6_nat_manager.watch_ue_ipv6,
            kwargs={"ue_container": "nr_ue", "hostname": "obu-v2x", "poll_interval": 10},
            daemon=True
        )
        mdns_thread.start()
        log("  ✓ mDNS watcher ativo em background.", GREEN)
    except Exception as e:
        log(f"  ⚠ NAT66 setup parcial: {e}", YELLOW)
        log("    Execute manualmente: python3 ipv6_nat_manager.py --action full-setup", YELLOW)

    # Obter o Namespace PID do UE
    ue_pid = run_sudo_cmd("docker inspect -f '{{.State.Pid}}' nr_ue").stdout.strip()

    log(f"\n[6/6] Setup Completo!", YELLOW)
    log(f"  OBU IPv4: {obu_ip_v4}", CYAN)
    log(f"  OBU IPv6: {obu_ip_v6}", CYAN)
    return obu_ip_v4, obu_ip_v6, ue_pid

# ==========================================
# MESSAGE GENERATORS
# ==========================================

def create_bsm(msg_count):
    sec_mark = int((time.time() * 1000) % 60000)
    json_data = {
        "bsm": {"messageId": 20, "value": {
            "coreData": {
                "msgCnt": msg_count % 128, "id": "A1B2C3D4", "secMark": sec_mark,
                "lat": -235497100, "long": -466327200, "elev": 100,
                "accuracy": {"semiMajor": 40, "semiMinor": 40, "orientation": 0},
                "transmission": "forwardGears", "speed": 750, "heading": 0, "angle": 0,
                "accelSet": {"long": 0, "lat": 0, "vert": 0, "yaw": 0},
                "brakes": {"wheelBrakes": "00", "traction": "unavailable", "abs": "unavailable",
                           "scs": "unavailable", "brakeBoost": "unavailable", "auxBrakes": "unavailable"},
                "size": {"width": 200, "length": 500}
            }
        }}
    }
    return json.dumps(json_data)

def create_spat(msg_count):
    json_data = {
        "spat": {"messageId": 19, "value": {
            "msgCnt": msg_count % 128,
            "intersections": [{
                "id": {"region": 0, "id": 1001},
                "revision": 1, "status": "00",
                "states": [{
                    "signalGroup": 1,
                    "state-time-speed": [{"eventState": "stop-And-Remain", "timing": {"minEndTime": 1000}}]
                }]
            }]
        }}
    }
    return json.dumps(json_data)

def create_psm(msg_count):
    sec_mark = int((time.time() * 1000) % 60000)
    json_data = {
        "psm": {"messageId": 32, "value": {
            "basicType": "aPEDESTRIAN", "secMark": sec_mark, "msgCnt": msg_count % 128,
            "id": "50534D31", "position": {"lat": -235497100, "long": -466327200, "elevation": 100},
            "accuracy": {"semiMajor": 40, "semiMinor": 40, "orientation": 0},
            "speed": 100, "heading": 0
        }}
    }
    return json.dumps(json_data)

MESSAGE_GENERATORS = {
    "bsm": create_bsm, "spat": create_spat, "psm": create_psm,
}

# ==========================================
# SIMULATOR LOGIC
# ==========================================

class UDPSender:
    """UDP Sender dual-stack (AF_INET6 com IPV6_V6ONLY=0)."""
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        log(f"[INFO] UDP Sender (dual-stack) → [{self.host}]:{self.port}", CYAN)

    def send_event(self, event_data):
        try:
            message = json.dumps(event_data).encode('utf-8') + b'\n'
            self.sock.sendto(message, (self.host, self.port))
        except Exception as e:
             log(f"[ERROR] Fail: {e}", RED)

    def close(self):
        self.sock.close()

def run_interactive_simulation(fwd_target="127.0.0.1"):
    set_terminal_title("CARLA_5G_Simulator")
    log("============================================", MAGENTA)
    log("  CARLA 5G V2X INTERACTIVE SIMULATOR", MAGENTA)
    log("============================================", MAGENTA)
    log(f"Enviando UDP para target RSU Forwarder em {fwd_target}:{FORWARDER_PORT}", CYAN)
    log("Comandos: send [TYPE], list, close, quit", YELLOW)
    log("Tipos: bsm, spat, psm, all", YELLOW)
    log("====================================", MAGENTA)

    sender = UDPSender(fwd_target, FORWARDER_PORT)
    msg_count = 0



    while True:
        try:
            cmd_raw = input("CARLA-5G> ").strip().lower()
            parts = cmd_raw.split()
            if not parts: continue
            cmd = parts[0]

            if cmd in ("quit", "exit", "close"):
                break
            elif cmd == "list":
                print("\n bsm, spat, psm, all\n")
            elif cmd == "send":
                msg_type = parts[1] if len(parts) > 1 else "bsm"
                msg_count += 1
                if msg_type == "all":
                    for name, gen_func in MESSAGE_GENERATORS.items():
                        sender.send_event(json.loads(gen_func(msg_count)))
                    print(f"  [>] Enviado ALL (Msg #{msg_count})")
                else:
                    if msg_type not in MESSAGE_GENERATORS:
                        print(f"[!] Desconhecido: {msg_type}")
                        continue
                    sender.send_event(json.loads(MESSAGE_GENERATORS[msg_type](msg_count)))
                    print(f"  [>] Enviado '{msg_type}' (Msg #{msg_count})")
            else:
                print("Comando inválido. Tipos permitidos: send, list, close.")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ERROR: {e}")

    sender.close()
    log("Simulator Fechado.", CYAN)

# ==========================================
# WINDOW MANAGEMENT
# ==========================================

def open_child_window(title, mode, script_args=""):
    """Spawns a new terminal running this script or an external script."""
    script_path = os.path.abspath(__file__)
    python_exe = sys.executable
    
    if mode == "simulate":
        args = f'"{python_exe}" "{script_path}" --simulate --target-fwd 127.0.0.1'
    elif mode == "forwarder":
        fwd_path = os.path.join(LOCAL_DIR, "rsu_5g_forwarder.py")
        args = f'"{python_exe}" "{fwd_path}" {script_args}'
    elif mode == "nsenter_receiver":
        ue_pid, recv_args = script_args.split("|", 1)
        recv_path = os.path.join(LOCAL_DIR, "obu_5g_receiver.py")
        # Preserva PYTHONPATH do user para que sudo/nsenter encontre j2735_202409 em ~/.local
        user_site = os.path.expanduser('~/.local/lib/python3.12/site-packages')
        args = f"echo '{SUDO_PASS}' | sudo -S PYTHONPATH={user_site}:$PYTHONPATH nsenter -t {ue_pid} -n '{python_exe}' '{recv_path}' {recv_args}"
    elif mode == "docker_forwarder":
        args = script_args
        
    terminals = [
        ("gnome-terminal", f"gnome-terminal --title='{title}' -- bash -c '{args}; exec bash'"),
        ("konsole", f"konsole --title '{title}' -e bash -c '{args}; exec bash'"),
        ("xfce4-terminal", f"xfce4-terminal --title='{title}' -e 'bash -c \"{args}; exec bash\"'"),
        ("xterm", f"xterm -T '{title}' -e bash -c '{args}; exec bash'")
    ]
    full_cmd = ""
    for term, cmd in terminals:
        if subprocess.run(["which", term], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            full_cmd = cmd
            break
            
    if not full_cmd: full_cmd = f"xterm -T '{title}' -e bash -c '{args}; exec bash'"
    log(f"  🖥️  Lançando {title}...", CYAN)
    subprocess.Popen(full_cmd, shell=True)

# ==========================================
# MAIN AUTO DEPLOY
# ==========================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true", help="Internal: CARLA Simulation Mode")
    parser.add_argument("--target-fwd", default="::1")
    args = parser.parse_args()
    
    if args.simulate:
        try: run_interactive_simulation(args.target_fwd)
        except KeyboardInterrupt: pass
    else:
        try:
            # Roda as checagens e pega IPv4, IPv6, e PID do UE V2X
            obu_ip_v4, obu_ip_v6, ue_pid = setup_infrastructure()

            print("\nEsta ferramenta fará o deploy e abrirá 3 janelas:")
            print(f" 1. OBU 5G Receiver (Isolado no NetNS do Container PID {ue_pid})")
            print(" 2. RSU 5G Forwarder (Containerizado na rede do Core 5G)")
            print(" 3. CARLA Simulator (Gera V2X JSON no PATH 2)")
            print(f"\n  OBU IPv4: {obu_ip_v4}")
            print(f"  OBU IPv6: {obu_ip_v6}")
            input("\nPressione Enter para lançar Tudo...")

            log("\n[1/3] Iniciando OBU 5G Receiver (Isolado em NS, Dual-Stack)...", YELLOW)
            # OBU escuta em :: (dual-stack), recebe IPv4 e IPv6
            obu_args = f"{ue_pid}|--v2x-port 9090 --tablet-port {TABLET_PORT} --v2x-ip ::"
            open_child_window("OBU_5G_Receiver_nsenter", "nsenter_receiver", obu_args)
            time.sleep(2)

            log("\n[2/3] Iniciando RSU 5G Forwarder (Containerizado, IPv6)...", YELLOW)
            try:
                res_upf = run_sudo_cmd("docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' open5gs-upf")
                upf_ip = res_upf.stdout.strip() if res_upf.returncode == 0 and res_upf.stdout.strip() else ""
                res_net = run_sudo_cmd("docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}' open5gs-upf")
                docker_net = res_net.stdout.strip() if res_net.returncode == 0 and res_net.stdout.strip() else "host"
            except Exception:
                upf_ip = ""
                docker_net = "host"

            log("  🖥️  Construindo imagem conecta2030_rsu (caso necessário)...", CYAN)
            run_sudo_cmd("docker build -t conecta2030_rsu -f Dockerfile.rsu .")
            run_sudo_cmd("docker rm -f rsu_5g_forwarder")
            
            # Usar IPv6 como destino principal do Forwarder
            port_bind = "-p [::]:9090:9090/udp" if docker_net != "host" else ""
            upf_env = f"-e UPF_IP={upf_ip}" if upf_ip else ""
            
            # O forwarder envia para o OBU IPv6 (fd00:5678::2) via dual-stack
            fwd_cmd = f"echo '{SUDO_PASS}' | sudo -S docker run --rm --name rsu_5g_forwarder --network {docker_net} --cap-add=NET_ADMIN {upf_env} -e OBU_SUBNET=fd00:5678::/64 {port_bind} conecta2030_rsu --obu-ip {obu_ip_v6} --listen-ip :: --listen-port 9090"
            open_child_window("RSU_5G_Forwarder_Docker", "docker_forwarder", fwd_cmd)
            time.sleep(2)

            log("\n[3/3] Iniciando CARLA Simulator Interativo...", YELLOW)
            open_child_window("CARLA_5G_Simulator", "simulate")
            
            log("\n✅ Concluído! Vá para o terminal [CARLA_5G_Simulator] para enviar mensagens.", GREEN)
            log(f"   Forwarder envia para OBU via IPv6: [{obu_ip_v6}]:9090", CYAN)
        except KeyboardInterrupt:
            pass
