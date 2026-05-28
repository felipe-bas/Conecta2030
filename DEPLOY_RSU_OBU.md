# V2X Alert System - Guia de Deploy para RSU e OBU

Este documento detalha o passo a passo completo para transferir e executar os servidores de alerta V2X na RSU e OBU.

---

## 📋 Informações de Acesso

| Dispositivo | IP | Usuário | Senha |
|-------------|-----|---------|-------|
| **RSU** | 192.168.0.56 | root | Conect@2024 |
| **OBU** | 192.168.0.53 | root | Conect@24 |

---

## Parte 1: Preparação (No seu computador Windows)

### 1.1 Verificar se os executáveis existem

Abra o PowerShell e execute:

```powershell
cd c:\Users\ferob\Downloads\conecta2030
dir fac_alert_server, obu_alert_server
```

Se os arquivos **não existirem**, extraia-os do Docker:

```powershell
$containerId = docker create arm32-builder
docker cp ${containerId}:/workspace/build/fac_alert_server ./
docker cp ${containerId}:/workspace/build/obu_alert_server ./
docker rm $containerId
```

### 1.2 Verificar conectividade com RSU e OBU

```powershell
ping 192.168.0.56
ping 192.168.0.53
```

> ⚠️ Se não responder, verifique se você está na mesma rede dos dispositivos.

---

## Parte 2: Deploy na RSU

### 2.1 Transferir o executável para a RSU

```powershell
cd c:\Users\ferob\Downloads\conecta2030
scp -O .\fac_alert_server root@192.168.0.56:/tmp/
```

Quando pedir a senha, digite: `Conect@2024`

**Saída esperada:**
```
fac_alert_server    100%   31KB 177.2KB/s   00:00
```

### 2.2 Conectar na RSU via SSH

```powershell
ssh root@192.168.0.56
```

Senha: `Conect@2024`

### 2.3 Preparar e executar o servidor na RSU

Dentro da RSU (após conectar via SSH):

```bash
# Ir para o diretório onde o arquivo foi copiado
cd /tmp

# Verificar se o arquivo está lá
ls -la fac_alert_server

# Dar permissão de execução
chmod +x fac_alert_server

# Executar o servidor
./fac_alert_server
```

**Saída esperada:**
```
Waiting for clients to connect...
```

### 2.4 (Opcional) Executar em background

Para manter o servidor rodando mesmo após desconectar:

```bash
nohup ./fac_alert_server > /tmp/fac_alert.log 2>&1 &
```

Para verificar se está rodando:
```bash
ps | grep fac_alert
```

Para ver os logs:
```bash
tail -f /tmp/fac_alert.log
```

### 2.5 Sair da RSU

```bash
exit
```

---

## Parte 3: Deploy na OBU

### 3.1 Transferir o executável para a OBU

No PowerShell (Windows):

```powershell
cd c:\Users\ferob\Downloads\conecta2030
scp -O .\obu_alert_server root@192.168.0.53:/tmp/
```

Quando pedir a senha, digite: `Conect@24`

**Saída esperada:**
```
obu_alert_server    100%   29KB 152.5KB/s   00:00
```

### 3.2 Conectar na OBU via SSH

```powershell
ssh root@192.168.0.53
```

Senha: `Conect@24`

### 3.3 Preparar e executar o servidor na OBU

Dentro da OBU (após conectar via SSH):

```bash
# Ir para o diretório onde o arquivo foi copiado
cd /tmp

# Verificar se o arquivo está lá
ls -la obu_alert_server

# Dar permissão de execução
chmod +x obu_alert_server

# Executar o servidor
./obu_alert_server
```

**Saída esperada:**
```
Waiting for clients to connect...
```

### 3.4 (Opcional) Executar em background

```bash
nohup ./obu_alert_server > /tmp/obu_alert.log 2>&1 &
```

### 3.5 Sair da OBU

```bash
exit
```

---

## Parte 4: Verificação do Sistema

### 4.1 Verificar status dos servidores

**Na RSU:**
```powershell
ssh root@192.168.0.56 "ps | grep fac_alert"
```

**Na OBU:**
```powershell
ssh root@192.168.0.53 "ps | grep obu_alert"
```

### 4.2 Arquitetura do Sistema

```
┌─────────────┐     TCP:8080     ┌─────────────┐     DSRC/WSMP     ┌─────────────┐
│   CARLA     │ ───────────────► │     RSU     │ ────────────────► │     OBU     │
│  Simulator  │                  │ 192.168.0.56│                   │ 192.168.0.53│
└─────────────┘                  └─────────────┘                   └─────────────┘
                                       │                                  │
                                       │ TCP                              │ TCP
                                       ▼                                  ▼
                                 ┌───────────┐                     ┌───────────┐
                                 │ Smartphone│                     │  Tablet   │
                                 │ (Pedestre)│                     │(Motorista)│
                                 └───────────┘                     └───────────┘
```

---

## Parte 5: Troubleshooting

### Erro: "Connection refused" no SCP/SSH
- Verifique se você está na mesma rede (192.168.0.x)
- Verifique se o dispositivo está ligado

### Erro: "sftp-server: not found"
- Use a flag `-O` no SCP: `scp -O arquivo root@IP:/destino/`

### Erro: "/home/: No such file or directory"
- Use `/tmp/` como destino em vez de `/home/`

### Erro: "Permission denied"
- Execute `chmod +x nome_do_arquivo` antes de rodar

### Servidor para de funcionar após desconectar SSH
- Use `nohup ./servidor &` para rodar em background

---

## Comandos Rápidos de Referência

```powershell
# ===== WINDOWS (PowerShell) =====

# Transferir para RSU
scp -O .\fac_alert_server root@192.168.0.56:/tmp/
# Senha: Conect@2024

# Transferir para OBU
scp -O .\obu_alert_server root@192.168.0.53:/tmp/
# Senha: Conect@24

# Conectar na RSU
ssh root@192.168.0.56
# Senha: Conect@2024

# Conectar na OBU
ssh root@192.168.0.53
# Senha: Conect@24
```

```bash
# ===== DENTRO DA RSU/OBU (Linux) =====

# Executar servidor
cd /tmp && chmod +x *_server && ./fac_alert_server

# Executar em background
nohup ./fac_alert_server > /tmp/log.txt 2>&1 &

# Ver processos rodando
ps | grep alert

# Matar processo
killall fac_alert_server
```

---

*Documento atualizado em 30/01/2026*
