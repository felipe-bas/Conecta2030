@echo off
echo ========================================================
echo       SUPER SCANNER DE BBU (Requer Administrador!)
echo ========================================================
echo.
net session >nul 2>&1
if errorlevel 1 goto NOTADMIN
goto ISADMIN

:NOTADMIN
echo [ERRO] Este script precisa ser executado como Administrador!
echo Feche, clique com o botao direito e selecione "Executar como administrador".
pause
exit /b

:ISADMIN
echo [OK] Executando como Administrador.

REM Primeiro, garantimos que o IP base está lá
netsh interface ipv4 set address name="Ethernet" static 192.168.0.51 255.255.255.0 >nul 2>&1

echo Criando o script Python do Scanner...
echo import subprocess > super_scanner_temp.py
echo import concurrent.futures >> super_scanner_temp.py
echo import re >> super_scanner_temp.py
echo subnets = ['192.168.1', '192.168.2', '192.168.100', '192.168.88', '10.0.0', '10.1.1', '172.16.0'] >> super_scanner_temp.py
echo print("Adicionando IPs temporarios (Redes 192.168.1.x, 10.0.0.x, etc)...") >> super_scanner_temp.py
echo for sub in subnets: >> super_scanner_temp.py
echo     subprocess.run(f'netsh interface ipv4 add address "Ethernet" {sub}.51 255.255.255.0', shell=True, stdout=subprocess.DEVNULL) >> super_scanner_temp.py
echo ips_to_ping = [] >> super_scanner_temp.py
echo for sub in subnets + ['192.168.0']: >> super_scanner_temp.py
echo     for suffix in [1, 49, 50, 52, 100, 200, 254]: >> super_scanner_temp.py
echo         ips_to_ping.append(f"{sub}.{suffix}") >> super_scanner_temp.py
echo def ping_ip(ip): >> super_scanner_temp.py
echo     try: >> super_scanner_temp.py
echo         res = subprocess.run(f"ping -n 1 -w 500 {ip}", shell=True, capture_output=True, text=True) >> super_scanner_temp.py
echo         if "TTL=" in res.stdout: return ip >> super_scanner_temp.py
echo     except: pass >> super_scanner_temp.py
echo     return None >> super_scanner_temp.py
echo print(f"Varrendo {len(ips_to_ping)} IPs padroes da industria (Commsignia, Yunex, etc)...") >> super_scanner_temp.py
echo found = [] >> super_scanner_temp.py
echo with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor: >> super_scanner_temp.py
echo     for res in executor.map(ping_ip, ips_to_ping): >> super_scanner_temp.py
echo         if res: >> super_scanner_temp.py
echo             found.append(res) >> super_scanner_temp.py
echo             print(f"\n[!!!] DISPOSITIVO ENCONTRADO NO IP: {res}\n") >> super_scanner_temp.py
echo print("Limpando IPs temporarios...") >> super_scanner_temp.py
echo for sub in subnets: >> super_scanner_temp.py
echo     subprocess.run(f'netsh interface ipv4 delete address "Ethernet" {sub}.51', shell=True, stdout=subprocess.DEVNULL) >> super_scanner_temp.py
echo if not found: print("Nenhum IP encontrado.") >> super_scanner_temp.py

echo.
echo Iniciando Super Scanner Python...
python super_scanner_temp.py
del super_scanner_temp.py

echo.
echo ========================================================
echo Scanner finalizado!
echo ========================================================
pause
