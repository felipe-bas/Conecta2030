@echo off
echo ========================================================
echo       RESTAURAR IP DO PC PARA 192.168.0.51
echo ========================================================
echo.
echo Verificando permissoes...
net session >nul 2>&1
if errorlevel 1 goto NOTADMIN
goto ISADMIN

:NOTADMIN
echo [ERRO] Este script precisa ser executado como Administrador!
echo Feche, clique com o botao direito em "restaurar_ip_pc.bat"
echo e selecione "Executar como administrador".
pause
exit /b

:ISADMIN
echo [OK] Executando como Administrador.
echo.
echo Restaurando IP Fixo 192.168.0.51 no adaptador Ethernet...
netsh interface ipv4 set address name="Ethernet" static 192.168.0.51 255.255.255.0 >nul 2>&1

echo.
echo ========================================================
echo PRONTO! O seu PC voltou a ter o IP 192.168.0.51.
echo Tente acessar agora: http://192.168.0.50/ ou http://192.168.0.49/
echo ========================================================
pause
