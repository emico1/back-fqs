#!/usr/bin/env bash
# Crea la máquina virtual de Azure donde corre el sistema completo con Docker Compose.
# Ver docs/seguridad/despliegue-azure.md
#
#   az login
#   bash despliegue/azure/crear-vm.sh
#
# Solo abre SSH (22) y solo para la IP de quien corre el script. La app llega a la API por el
# túnel de Cloudflare, que sale desde la máquina, así que 80 y 443 no se abren en Azure.
# Con ABRIR_WEB=1 también se abren 80 y 443 para usar Caddy con un dominio propio.
set -euo pipefail

GRUPO="${GRUPO:-rg-familiasquesuman}"
UBICACION="${UBICACION:-mexicocentral}"
VM="${VM:-vm-familias}"
TAMANO="${TAMANO:-Standard_B2s}"
IMAGEN="${IMAGEN:-Canonical:ubuntu-24_04-lts:server:latest}"
USUARIO="${USUARIO:-fqsadmin}"
LLAVE="${LLAVE:-$HOME/.ssh/id_ed25519.pub}"
DISCO_GB="${DISCO_GB:-64}"
ABRIR_WEB="${ABRIR_WEB:-0}"
CARPETA="$(cd "$(dirname "$0")" && pwd)"

command -v az >/dev/null || { echo "Falta Azure CLI (az). Instálala y corre az login"; exit 1; }
az account show >/dev/null 2>&1 || { echo "Primero inicia sesión con az login"; exit 1; }

if [ ! -f "$LLAVE" ]; then
  echo "No existe $LLAVE. Crea una llave Ed25519 con"
  echo "  ssh-keygen -t ed25519 -a 100 -f ~/.ssh/id_ed25519 -C fqs-azure"
  exit 1
fi
case "$(cut -d' ' -f1 "$LLAVE")" in
  ssh-ed25519) ;;
  *) echo "La llave debe ser Ed25519 (ssh-ed25519)"; exit 1 ;;
esac

# IP pública de quien administra, la única que podrá entrar por SSH
MI_IP="${MI_IP:-$(curl -fsS https://api.ipify.org)}"
[[ "$MI_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "No se pudo obtener tu IP pública, ponla en MI_IP"; exit 1; }

# El tamaño debe existir en la región y no tener restricciones para la suscripción
if ! az vm list-skus -l "$UBICACION" --size "$TAMANO" --resource-type virtualMachines \
      --query "[?name=='$TAMANO' && length(restrictions)==\`0\`].name" -o tsv | grep -qx "$TAMANO"; then
  echo "$TAMANO no está disponible en $UBICACION para esta suscripción. Prueba otro con TAMANO=Standard_B2ms"
  exit 1
fi

echo "Grupo de recursos $GRUPO en $UBICACION"
az group create -n "$GRUPO" -l "$UBICACION" --tags proyecto=familiasquesuman -o none

echo "Grupo de seguridad de red, todo cerrado salvo SSH desde $MI_IP"
az network nsg create -g "$GRUPO" -n "nsg-$VM" -l "$UBICACION" -o none
az network nsg rule create -g "$GRUPO" --nsg-name "nsg-$VM" -n ssh-administracion --priority 100 \
  --direction Inbound --access Allow --protocol Tcp --source-address-prefixes "$MI_IP/32" \
  --destination-port-ranges 22 -o none
if [ "$ABRIR_WEB" = "1" ]; then
  az network nsg rule create -g "$GRUPO" --nsg-name "nsg-$VM" -n web --priority 110 \
    --direction Inbound --access Allow --protocol Tcp --source-address-prefixes Internet \
    --destination-port-ranges 80 443 -o none
fi

# Los tamaños de las generaciones v6 y v7 solo tienen discos NVMe. Ubuntu 24.04 lo soporta
CONTROLADOR=()
if [[ "$TAMANO" =~ _v[67]$ ]]; then CONTROLADOR=(--disk-controller-type NVMe); fi

echo "Máquina virtual $VM ($TAMANO, Ubuntu 24.04, arranque seguro y vTPM)"
az vm create -g "$GRUPO" -n "$VM" -l "$UBICACION" \
  --image "$IMAGEN" --size "$TAMANO" \
  --admin-username "$USUARIO" --authentication-type ssh --ssh-key-values "$LLAVE" \
  --nsg "nsg-$VM" --public-ip-sku Standard \
  --os-disk-size-gb "$DISCO_GB" --storage-sku StandardSSD_LRS \
  --security-type TrustedLaunch --enable-secure-boot true --enable-vtpm true \
  --custom-data "$CARPETA/cloud-init.yaml" \
  "${CONTROLADOR[@]}" -o none

IP=$(az vm show -d -g "$GRUPO" -n "$VM" --query publicIps -o tsv)
echo
echo "Lista. La configuración inicial (actualizaciones, Docker, firewall) tarda unos minutos."
echo "Revisa que terminó con"
echo "  ssh $USUARIO@$IP cloud-init status --wait"
echo "Después sigue docs/seguridad/despliegue-azure.md"
