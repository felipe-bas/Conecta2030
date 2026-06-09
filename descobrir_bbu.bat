@echo off
echo ========================================================
echo       BUSCADOR DE IP DA BBU (Requer Administrador!)
echo ========================================================
echo.
echo Verificando permissoes...
net session >nul 2>&1
if errorlevel 1 goto NOTADMIN
goto ISADMIN

:NOTADMIN
echo [ERRO] Este script precisa ser executado como Administrador!
echo Feche, clique com o botao direito em "descobrir_bbu.bat"
echo e selecione "Executar como administrador".
pause
exit /b

:ISADMIN
echo [OK] Executando como Administrador.
echo.
echo 1. Limpando filtros antigos do PktMon...
pktmon filter remove >nul 2>&1
echo 2. Adicionando filtro para pacotes IPv4, IPv6 e ARP...
pktmon filter add -t IPv4 >nul 2>&1
pktmon filter add -t ARP >nul 2>&1
pktmon filter add -t IPv6 >nul 2>&1
echo 3. Iniciando captura de pacotes em todas as placas de rede...
pktmon start --etw >nul 2>&1

echo.
echo [!] REINICIE A BBU AGORA OU DESCONECTE E RECONECTE O CABO DELA!
echo Capturando trafego por 20 segundos... aguarde...
timeout /t 20 /nobreak

echo.
echo 4. Parando captura...
pktmon stop >nul 2>&1
echo 5. Formatando log para texto...
pktmon format PktMon.etl -o captura_bbu.txt >nul 2>&1

echo.
echo ========================================================
echo CAPTURA FINALIZADA! 
echo O arquivo "captura_bbu.txt" foi gerado na mesma pasta.
echo O Antigravity vai ler esse arquivo e encontrar o IP.
echo ========================================================
pause
