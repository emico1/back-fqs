# Crea la máquina virtual de Azure desde Windows (PowerShell). Hace lo mismo que crear-vm.sh.
# Ver docs/seguridad/despliegue-azure.md
#
#   az login
#   powershell -ExecutionPolicy Bypass -File despliegue\azure\crear-vm.ps1
#
# Solo abre SSH (22) y solo para la IP de quien corre el script. La app llega a la API por el
# túnel de Cloudflare, que sale desde la máquina, así que 80 y 443 no se abren en Azure.
# Con -AbrirWeb también se abren 80 y 443 para usar Caddy con un dominio propio.
param(
    [string]$Grupo = "rg-familiasquesuman",
    [string]$Ubicacion = "mexicocentral",
    [string]$Vm = "vm-familias",
    [string]$Tamano = "Standard_B2s",
    [string]$Imagen = "Canonical:ubuntu-24_04-lts:server:latest",
    [string]$Usuario = "fqsadmin",
    [string]$Llave = "$HOME\.ssh\id_ed25519.pub",
    [int]$DiscoGb = 64,
    [string]$MiIp = "",
    [switch]$AbrirWeb
)
$ErrorActionPreference = "Stop"
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path

function Revisar([string]$paso) {
    if ($LASTEXITCODE -ne 0) { throw "Falló $paso (código $LASTEXITCODE)" }
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw "Falta Azure CLI (az). Instálala con  winget install -e --id Microsoft.AzureCLI" }
$cuenta = az account show --query name -o tsv
if ($LASTEXITCODE -ne 0 -or -not $cuenta) { throw "Primero inicia sesión con  az login" }
Write-Host "Suscripción $cuenta"

if (-not (Test-Path $Llave)) {
    throw "No existe $Llave. Crea una llave Ed25519 con  ssh-keygen -t ed25519 -a 100 -f `"$HOME\.ssh\id_ed25519`" -C fqs-azure"
}
if (-not ((Get-Content $Llave -Raw).StartsWith("ssh-ed25519 "))) { throw "La llave debe ser Ed25519 (ssh-ed25519)" }

# IP pública de quien administra, la única que podrá entrar por SSH
if (-not $MiIp) { $MiIp = (Invoke-RestMethod -Uri "https://api.ipify.org").Trim() }
if ($MiIp -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw "No se pudo obtener tu IP pública, pásala con -MiIp" }

# El tamaño debe existir en la región y no tener restricciones para la suscripción
# Se filtra en PowerShell y no con --query, porque az en Windows es un .cmd y los caracteres
# & y | de una consulta se los come la consola
# Los paréntesis importan. En Windows PowerShell 5.1, ConvertFrom-Json entrega el arreglo como
# un solo objeto y Where-Object lo vería completo en lugar de tamaño por tamaño
$skus = @(az vm list-skus -l $Ubicacion --size $Tamano --resource-type virtualMachines -o json | ConvertFrom-Json)
$disponible = @($skus | ForEach-Object { $_ } | Where-Object { $_.name -eq $Tamano -and @($_.restrictions).Count -eq 0 })
if ($disponible.Count -eq 0) {
    throw "$Tamano no está disponible en $Ubicacion para esta suscripción. Prueba otro con -Tamano Standard_B2ms"
}

# Algunas suscripciones (por ejemplo las de laboratorio de una universidad) no dejan crear
# grupos de recursos, pero dan uno ya creado. Si el grupo existe se usa tal cual
# az group exists responde true o false sin escribir errores. En Windows PowerShell 5.1 un error
# de az redirigido con 2>$null detiene el script por $ErrorActionPreference = "Stop"
$existe = (az group exists -n $Grupo).Trim()
if ($existe -eq "true") {
    Write-Host "Se usa el grupo de recursos existente $Grupo"
} else {
    Write-Host "Grupo de recursos $Grupo en $Ubicacion"
    az group create -n $Grupo -l $Ubicacion --tags proyecto=familiasquesuman -o none; Revisar "crear el grupo"
}

Write-Host "Grupo de seguridad de red, todo cerrado salvo SSH desde $MiIp"
az network nsg create -g $Grupo -n "nsg-$Vm" -l $Ubicacion -o none; Revisar "crear el grupo de seguridad"
az network nsg rule create -g $Grupo --nsg-name "nsg-$Vm" -n ssh-administracion --priority 100 `
    --direction Inbound --access Allow --protocol Tcp --source-address-prefixes "$MiIp/32" `
    --destination-port-ranges 22 -o none; Revisar "abrir SSH"
if ($AbrirWeb) {
    az network nsg rule create -g $Grupo --nsg-name "nsg-$Vm" -n web --priority 110 `
        --direction Inbound --access Allow --protocol Tcp --source-address-prefixes Internet `
        --destination-port-ranges 80 443 -o none; Revisar "abrir 80 y 443"
}

# Los tamaños de las generaciones v6 y v7 solo tienen discos NVMe. Ubuntu 24.04 lo soporta
$controlador = @()
if ($Tamano -match '_v[67]$') { $controlador = @("--disk-controller-type", "NVMe") }

Write-Host "Máquina virtual $Vm ($Tamano, Ubuntu 24.04, arranque seguro y vTPM)"
az vm create -g $Grupo -n $Vm -l $Ubicacion `
    --image $Imagen --size $Tamano `
    --admin-username $Usuario --authentication-type ssh --ssh-key-values $Llave `
    --nsg "nsg-$Vm" --public-ip-sku Standard `
    --os-disk-size-gb $DiscoGb --storage-sku StandardSSD_LRS `
    --security-type TrustedLaunch --enable-secure-boot true --enable-vtpm true `
    --custom-data (Join-Path $carpeta "cloud-init.yaml") `
    @controlador -o none; Revisar "crear la máquina"

$ip = az vm show -d -g $Grupo -n $Vm --query publicIps -o tsv
Write-Host ""
Write-Host "Lista. IP pública $ip"
Write-Host "La configuración inicial (actualizaciones, Docker, firewall) tarda unos minutos. Revisa que terminó con"
Write-Host "  ssh $Usuario@$ip cloud-init status --wait"
Write-Host "Después sigue docs/seguridad/despliegue-azure.md"
