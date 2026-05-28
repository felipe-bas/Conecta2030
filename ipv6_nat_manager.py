#!/usr/bin/env python3
"""
IPv6 NAT Manager — Conecta2030
Gerencia NAT66 (masquerade) e ip6tables para o tráfego V2X
na rede 5G com overlay IPv6 ULA (fd00:5678::/64).

Funções:
  - Configurar ip6tables MASQUERADE na interface ogstun3
  - Descobrir endereço IPv6 alocado na uesimtun1
  - Verificar conectividade IPv6 end-to-end
  - Injetar rotas IPv6 no host/container
  - Monitorar mudanças de IPv6 e publicar via mDNS (Avahi)
  - Resolver hostnames V2X via mDNS (.local)

Uso:
    python3 ipv6_nat_manager.py --action setup-nat    [--upf-iface ogstun3]
    python3 ipv6_nat_manager.py --action discover-ue  [--container ueransim]
    python3 ipv6_nat_manager.py --action inject-route [--container ueransim]
    python3 ipv6_nat_manager.py --action verify       [--target fd00:5678::2]
    python3 ipv6_nat_manager.py --action full-setup   [--container ueransim]
    python3 ipv6_nat_manager.py --action watch        [--ue-container ueransim --hostname obu-v2x]
    python3 ipv6_nat_manager.py --action resolve      [--hostname obu-v2x]
"""

import subprocess
import sys
import re
import argparse
import time
import socket
import os

CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
MAGENTA = "\033[95m"
RESET   = "\033[0m"

# Prefixo IPv6 ULA para V2X
V2X_PREFIX = "fd00:5678::/64"
V2X_PREFIX_SHORT = "fd00:5678::"
UPF_V2X_GW = "fd00:5678::1"
UE_V2X_ADDR = "fd00:5678::2"
UPF_IFACE = "ogstun3"
UE_IFACE = "uesimtun1"

# Servidor de Registro Central (DDNS)
V2X_REGISTRY_URL = "http://10.147.17.110:5000"


def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}", flush=True)


def run(cmd, check=True, capture=True):
    """Executa um comando shell e retorna stdout."""
    log(f"  $ {cmd}", CYAN)
    result = subprocess.run(
        cmd, shell=True, capture_output=capture,
        text=True, timeout=30
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        log(f"  ✗ Falhou (rc={result.returncode}): {stderr}", RED)
        return None
    return result.stdout.strip() if capture else ""


def run_in_container(container_name, cmd):
    """Executa comando dentro de um container Docker."""
    return run(f"docker exec {container_name} {cmd}")


# ====================================================================
# ACTION: setup-nat — Configura ip6tables MASQUERADE no UPF
# ====================================================================
def setup_nat(upf_container="open5gs_upf", upf_iface=UPF_IFACE):
    """
    Configura NAT66 (MASQUERADE) no container UPF para que o tráfego
    IPv6 V2X vindo do uesimtun1 seja roteado via ogstun3.
    """
    log(f"\n[NAT66] Configurando MASQUERADE no UPF ({upf_container})...", MAGENTA)

    # 1. Habilitar forwarding IPv6
    run_in_container(upf_container,
        "sysctl -w net.ipv6.conf.all.forwarding=1")

    # 2. Verificar se ip6tables existe
    check = run_in_container(upf_container, "which ip6tables")
    if check is None:
        log("[NAT66] ✗ ip6tables não encontrado no container UPF!", RED)
        log("[NAT66]   Instale com: apt-get install -y iptables", YELLOW)
        return False

    # 3. Flush regras anteriores (evitar duplicatas)
    run_in_container(upf_container,
        f"ip6tables -t nat -D POSTROUTING -s {V2X_PREFIX} -o eth0 -j MASQUERADE 2>/dev/null")

    # 4. Adicionar MASQUERADE para tráfego V2X saindo pela eth0
    result = run_in_container(upf_container,
        f"ip6tables -t nat -A POSTROUTING -s {V2X_PREFIX} -o eth0 -j MASQUERADE")

    if result is not None:
        log(f"[NAT66] ✓ MASQUERADE configurado: {V2X_PREFIX} → eth0", GREEN)
    else:
        log("[NAT66] ✗ Falha ao configurar MASQUERADE", RED)
        return False

    # 5. Permitir FORWARD do tráfego V2X
    run_in_container(upf_container,
        f"ip6tables -A FORWARD -s {V2X_PREFIX} -j ACCEPT")
    run_in_container(upf_container,
        f"ip6tables -A FORWARD -d {V2X_PREFIX} -j ACCEPT")

    # 6. Verificar regras
    log("\n[NAT66] Regras ip6tables ativas:", CYAN)
    run_in_container(upf_container, "ip6tables -t nat -L -n -v")

    log(f"[NAT66] ✓ NAT66 setup completo", GREEN)
    return True


# ====================================================================
# ACTION: discover-ue — Descobre endereço IPv6 do UE no uesimtun
# ====================================================================
def discover_ue_ipv6(ue_container="ueransim"):
    """
    Descobre o endereço IPv6 atribuído ao uesimtun1 no UE container.
    Retorna o endereço IPv6 se encontrado, None caso contrário.
    """
    log(f"\n[DISCOVER] Buscando IPv6 em {UE_IFACE} no container {ue_container}...", MAGENTA)

    output = run_in_container(ue_container,
        f"ip -6 addr show dev {UE_IFACE} scope global")

    if output is None:
        log(f"[DISCOVER] ✗ Interface {UE_IFACE} não encontrada", RED)
        return None

    # Procurar por endereço fd00:5678::X
    match = re.search(r'inet6\s+(fd00:5678::[^\s/]+)', output)
    if match:
        addr = match.group(1)
        log(f"[DISCOVER] ✓ UE IPv6: {addr}", GREEN)
        return addr

    # Procurar qualquer IPv6 global
    match = re.search(r'inet6\s+([^\s/]+)/\d+\s+scope\s+global', output)
    if match:
        addr = match.group(1)
        log(f"[DISCOVER] ✓ UE IPv6 (não-ULA): {addr}", YELLOW)
        return addr

    log(f"[DISCOVER] ✗ Nenhum IPv6 global encontrado em {UE_IFACE}", RED)
    log(f"[DISCOVER]   Output: {output}", YELLOW)
    return None


# ====================================================================
# ACTION: inject-route — Injeta rota IPv6 no host para alcançar o UE
# ====================================================================
def inject_route(ue_container="ueransim"):
    """
    Injeta rota no host Linux para que pacotes destinados a
    fd00:5678::/64 sejam encaminhados via o container UPF.
    """
    log(f"\n[ROUTE] Injetando rota IPv6 para {V2X_PREFIX}...", MAGENTA)

    # Descobrir PID do container UPF para nsenter
    pid_out = run(f"docker inspect -f '{{{{.State.Pid}}}}' open5gs_upf")
    if not pid_out:
        log("[ROUTE] ✗ Container UPF não encontrado", RED)
        return False

    upf_pid = pid_out.strip().strip("'")

    # Descobrir IPv4 do UPF na rede Docker (para roteamento gateway)
    upf_ipv4 = run(
        "docker inspect -f '{{.NetworkSettings.Networks.docker_open5gs_default.IPAddress}}' open5gs_upf")
    if not upf_ipv4:
        log("[ROUTE] ✗ IPv4 do UPF não encontrado", RED)
        return False

    upf_ipv4 = upf_ipv4.strip().strip("'")

    # Remover rota antiga se existir
    run(f"sudo ip -6 route del {V2X_PREFIX} 2>/dev/null", check=False)

    # Adicionar rota via namespace do UPF
    # O tráfego IPv6 para fd00:5678::/64 vai para o UPF que faz o forward
    result = run(
        f"sudo nsenter -t {upf_pid} -n ip -6 route add {V2X_PREFIX} dev {UPF_IFACE} 2>/dev/null",
        check=False)

    log(f"[ROUTE] ✓ Rota {V2X_PREFIX} → UPF (PID {upf_pid})", GREEN)
    return True


# ====================================================================
# ACTION: verify — Verificar conectividade IPv6 end-to-end
# ====================================================================
def verify_connectivity(target=UE_V2X_ADDR, upf_container="open5gs_upf"):
    """
    Verifica conectividade IPv6 entre o UPF e o UE via ping6.
    """
    log(f"\n[VERIFY] Testando conectividade IPv6 → {target}...", MAGENTA)

    # Ping do UPF para o UE
    result = run_in_container(upf_container,
        f"ping6 -c 3 -W 2 {target}")

    if result and "bytes from" in result:
        log(f"[VERIFY] ✓ Conectividade IPv6 OK: UPF → {target}", GREEN)
        return True
    else:
        log(f"[VERIFY] ✗ Sem resposta de {target}", RED)
        log("[VERIFY]   Verifique:", YELLOW)
        log(f"  1. IPv6 overlay ativo no UE ({UE_IFACE})?", YELLOW)
        log(f"  2. ip6tables FORWARD habilitado?", YELLOW)
        log(f"  3. sysctl net.ipv6.conf.all.forwarding=1 no UPF?", YELLOW)
        return False


# ====================================================================
# ACTION: full-setup — Executa tudo em sequência
# ====================================================================
def full_setup(ue_container="ueransim", upf_container="open5gs_upf"):
    """Executa setup completo de NAT66 + rota + verificação."""
    log("=" * 60, MAGENTA)
    log("  IPv6 NAT Manager — Conecta2030", MAGENTA)
    log("  Full Setup: NAT66 + Route Injection + Verify", MAGENTA)
    log("=" * 60, MAGENTA)

    # 1. Setup NAT66
    if not setup_nat(upf_container):
        return False

    # 2. Descobrir UE IPv6
    ue_ipv6 = discover_ue_ipv6(ue_container)
    if not ue_ipv6:
        log("[FULL] ⚠ UE IPv6 não detectado, continuando com default...", YELLOW)
        ue_ipv6 = UE_V2X_ADDR

    # 3. Injetar rota
    inject_route(ue_container)

    # 4. Aguardar convergência
    log("\n[FULL] Aguardando 3s para convergência de rotas...", CYAN)
    time.sleep(3)

    # 5. Verificar conectividade
    ok = verify_connectivity(ue_ipv6, upf_container)

    log("\n" + "=" * 60, MAGENTA)
    if ok:
        log("  ✓ IPv6 V2X SETUP COMPLETO — Conectividade OK", GREEN)
    else:
        log("  ⚠ Setup parcial — verificar conectividade manualmente", YELLOW)
    log(f"  UE IPv6:  {ue_ipv6}", CYAN)
    log(f"  UPF GW:   {UPF_V2X_GW}", CYAN)
    log(f"  Prefix:   {V2X_PREFIX}", CYAN)
    log("=" * 60, MAGENTA)

    return ok


# ====================================================================
# ACTION: watch — Monitora IPv6 do UE e publica via mDNS
# ====================================================================
def watch_ue_ipv6(ue_container="ueransim", hostname="obu-v2x", poll_interval=5):
    """
    Loop contínuo que monitora o IPv6 do UE e inicia o mDNS publisher
    dentro do container para publicar <hostname>.local.
    """
    log(f"\n[WATCH] Iniciando monitoramento IPv6 do UE ({ue_container})...", MAGENTA)
    log(f"[WATCH] Hostname: {hostname}.local", CYAN)
    log(f"[WATCH] Polling: a cada {poll_interval}s", CYAN)

    last_ipv6 = None
    publisher_pid = None

    # Instalar avahi dentro do container se necessário
    log(f"[WATCH] Verificando avahi no container {ue_container}...", CYAN)
    avahi_check = run_in_container(ue_container, "which avahi-publish-address")
    if avahi_check is None:
        log("[WATCH] Instalando avahi-utils no container...", YELLOW)
        run_in_container(ue_container,
            "bash -c 'apt-get update -qq && apt-get install -y -qq avahi-daemon avahi-utils libnss-mdns 2>/dev/null'")
        run_in_container(ue_container, "avahi-daemon -D 2>/dev/null")

    try:
        while True:
            # Descobrir IPv6 atual
            current_ipv6 = discover_ue_ipv6(ue_container)

            if current_ipv6 and current_ipv6 != last_ipv6:
                log(f"[WATCH] Mudança detectada: {last_ipv6} → {current_ipv6}", GREEN)

                # Parar publisher antigo
                if publisher_pid:
                    run_in_container(ue_container, f"kill {publisher_pid} 2>/dev/null")

                # 2. Publicar via Registry Central (DDNS)
                try:
                    import urllib.request
                    url = f"{V2X_REGISTRY_URL}/update?name={hostname}&ip={current_ipv6}"
                    with urllib.request.urlopen(url, timeout=5) as resp:
                        if resp.status == 200:
                            log(f"[WATCH] ✓ Registry atualizado: {hostname} -> {current_ipv6}", GREEN)
                except Exception as e:
                    log(f"[WATCH] ⚠ Falha ao atualizar Registry: {e}", YELLOW)

                last_ipv6 = current_ipv6

            elif not current_ipv6:
                log(f"[WATCH] ⚠ Nenhum IPv6 no UE, usando fallback {UE_V2X_ADDR}", YELLOW)

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        log("\n[WATCH] Monitoramento encerrado pelo usuário", YELLOW)
        if publisher_pid:
            run_in_container(ue_container, f"kill {publisher_pid} 2>/dev/null")


# ====================================================================
# ACTION: resolve — Resolve hostname V2X via mDNS
# ====================================================================
def resolve_hostname(hostname="obu-v2x"):
    """
    Resolve um hostname V2X via mDNS (.local) usando getaddrinfo.
    Requer avahi-daemon e libnss-mdns no host.
    """
    # 1. Tentar via Registry Central (DDNS)
    try:
        import urllib.request
        url = f"{V2X_REGISTRY_URL}/resolve?name={hostname}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status == 200:
                addr = resp.read().decode().strip()
                if addr:
                    log(f"[RESOLVE] ✓ {hostname} → {addr} (via Registry)", GREEN)
                    return addr
    except Exception as e:
        log(f"[RESOLVE] ⚠ Falha no Registry ({hostname}): {e}", YELLOW)

    # 2. Tentar via mDNS local (.local) usando getaddrinfo
    fqdn = hostname if hostname.endswith(".local") else f"{hostname}.local"
    log(f"[RESOLVE] Tentando mDNS para {fqdn}...", CYAN)
    try:
        results = socket.getaddrinfo(fqdn, None, socket.AF_INET6, socket.SOCK_STREAM)
        if results:
            addr = results[0][4][0]
            log(f"[RESOLVE] ✓ {fqdn} → {addr} (via getaddrinfo)", GREEN)
            return addr
    except socket.gaierror:
        pass

    # Fallback: tentar via avahi-resolve
    try:
        result = subprocess.run(
            ["avahi-resolve", "-6", "-n", fqdn],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                addr = parts[1]
                log(f"[RESOLVE] ✓ {fqdn} → {addr} (via avahi-resolve)", GREEN)
                return addr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    log(f"[RESOLVE] ✗ Não foi possível resolver {fqdn}", RED)
    log(f"[RESOLVE]   Fallback: usando endereço estático {UE_V2X_ADDR}", YELLOW)
    return UE_V2X_ADDR


def main():
    parser = argparse.ArgumentParser(
        description="IPv6 NAT Manager — Conecta2030 V2X")
    parser.add_argument("--action", required=True,
        choices=["setup-nat", "discover-ue", "inject-route", "verify",
                 "full-setup", "watch", "resolve"],
        help="Ação a executar")
    parser.add_argument("--upf-container", default="open5gs_upf",
        help="Nome do container UPF (default: open5gs_upf)")
    parser.add_argument("--ue-container", default="ueransim",
        help="Nome do container UE (default: ueransim)")
    parser.add_argument("--upf-iface", default=UPF_IFACE,
        help=f"Interface TUN do UPF (default: {UPF_IFACE})")
    parser.add_argument("--target", default=UE_V2X_ADDR,
        help=f"IPv6 do UE para verificação (default: {UE_V2X_ADDR})")
    parser.add_argument("--hostname", default="obu-v2x",
        help="Hostname mDNS para watch/resolve (default: obu-v2x)")
    parser.add_argument("--poll-interval", type=int, default=5,
        help="Intervalo de polling em segundos para watch (default: 5)")
    args = parser.parse_args()

    actions = {
        "setup-nat":    lambda: setup_nat(args.upf_container, args.upf_iface),
        "discover-ue":  lambda: discover_ue_ipv6(args.ue_container),
        "inject-route": lambda: inject_route(args.ue_container),
        "verify":       lambda: verify_connectivity(args.target, args.upf_container),
        "full-setup":   lambda: full_setup(args.ue_container, args.upf_container),
        "watch":        lambda: watch_ue_ipv6(args.ue_container, args.hostname, args.poll_interval),
        "resolve":      lambda: resolve_hostname(args.hostname),
    }

    result = actions[args.action]()

    if result is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
