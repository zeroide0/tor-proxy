#!/bin/bash
# ==============================================================================
#  INSTALLER & UNINSTALLER ULTIMATE TOR-PROXY
#  Versi: 4.2.0 (Enterprise Architecture - Nftables Native)
# ==============================================================================

MERAH='\033[0;31m'
HIJAU='\033[0;32m'
KUNING='\033[0;33m'
BIRU='\033[0;34m'
CYAN='\033[0;96m'
RESET='\033[0m'
BOLD='\033[1m'

INSTALL_PATH="/usr/local/bin/tor-proxy"
LOG_FILE="/var/log/tor-proxy.log"
SCRIPT_SRC="tor_proxy.py"

set -e
set -u
set -o pipefail

trap 'echo -e "\n${MERAH}[!] Instalasi Dihentikan oleh Pengguna.${RESET}"; exit 130' SIGINT
trap 'echo -e "\n${MERAH}[!] ERROR FATAL pada baris ke-${LINENO}. Instalasi Dibatalkan.${RESET}"; exit 1' ERR

info()   { echo -e "  ${BIRU}[*]${RESET} $1"; }
sukses() { echo -e "  ${HIJAU}[✓]${RESET} $1"; }
error()  { echo -e "  ${MERAH}[✗]${RESET} $1"; }
warn()   { echo -e "  ${KUNING}[!]$RESET $1"; }

header() {
  local msg="$1"
  local lebar=$(( ${#msg} + 6 ))
  local garis=$(printf '═%.0s' $(seq 1 $lebar))
  echo -e "\n${BOLD}${CYAN}╔${garis}╗"
  echo -e "║   ${msg}   ║"
  echo -e "╚${garis}╝${RESET}\n"
}

if [ "$EUID" -ne 0 ]; then
  error "Skrip ini mengatur hak cipta kernel firewall. Gunakan: sudo ./install.sh"
  exit 1
fi

# ==============================================================================
# UNINSTALLER
# ==============================================================================
if [ "${1:-}" == "--uninstall" ]; then
    header "UNINSTALLER TOR-PROXY"
    if command -v tor-proxy >/dev/null 2>&1; then
        info "Mengeksekusi pembersihan mendalam (Cleanup)..."
        set +e; tor-proxy --cleanup >/dev/null 2>&1; set -e
    fi
    info "Menghapus file eksekusi, folder state, dan log..."
    rm -f "${INSTALL_PATH}" "${LOG_FILE}"
    rm -rf "/var/run/tor-proxy"
    sukses "Uninstalasi Selesai! Semua kembali ke standar pabrikan."
    exit 0
fi

# ==============================================================================
# INSTALLER
# ==============================================================================
header "INSTALLER TOR-PROXY v4.2.0"

if [ ! -f "$SCRIPT_SRC" ]; then
  error "File sumber '${SCRIPT_SRC}' tidak ditemukan."
  exit 1
fi

info "Memverifikasi dependensi infrastruktur tingkat lanjut..."
set +e
BUTUH_APT=0
# Integrasi komprehensif nftables, iptables, stem, dan dnsutils
for pkg in tor curl python3 netcat-openbsd iptables python3-stem nftables dnsutils; do
    if ! dpkg -l | grep -qw "$pkg"; then
        BUTUH_APT=1
        warn "Paket $pkg belum terinstal."
    fi
done
set -e

if [ $BUTUH_APT -eq 1 ]; then
    info "Memasang pustaka dan program OS dari repository Ubuntu..."
    apt-get update -qq
    apt-get install -y tor curl python3 netcat-openbsd iptables python3-stem nftables dnsutils
    sukses "Seluruh dependensi eksekusi terpenuhi."
else
    sukses "Infrastruktur Nftables, Stem & DNSUtils telah sedia."
fi

# Deteksi Systemd-Resolved
if systemctl is-active --quiet systemd-resolved; then
    sukses "Layanan systemd-resolved aktif (Diperlukan untuk mitigasi DNS Leak)."
else
    warn "Layanan systemd-resolved tidak aktif. Manajemen Cache DNS akan ditangani secara asinkron."
fi

info "Mendaftarkan daemon Tor (Autostart)..."
systemctl enable tor >/dev/null 2>&1 || true
systemctl start tor >/dev/null 2>&1 || true

info "Merekam skrip ke PATH Global (${INSTALL_PATH})..."
cp "$SCRIPT_SRC" "$INSTALL_PATH"
chmod +x "$INSTALL_PATH"

touch "$LOG_FILE" && chmod 644 "$LOG_FILE"
mkdir -p /var/run/tor-proxy

if command -v tor-proxy >/dev/null 2>&1; then
    sukses "Instalasi Tor-Proxy berhasil di-compile dan diverifikasi."
else
    error "Gagal meregistrasi sistem."
    exit 1
fi

echo -e "\n${BOLD}${HIJAU}  Tor-Proxy 4.2.0 Enterprise Siap Digunakan!${RESET}"
echo -e "  ${CYAN}─────────────────────────────────────────────────────────${RESET}"
echo -e "  ${BOLD}PERINTAH UTAMA:${RESET}"
echo -e "    sudo tor-proxy -s           : Mengaktifkan mode penyamaran"
echo -e "    sudo tor-proxy -x           : Mematikan mode penyamaran"
echo -e "    sudo tor-proxy -r           : Mulai ulang sistem (Restart)"
echo -e "    sudo tor-proxy -n           : Eksekusi rotasi alamat IP"
echo -e ""
echo -e "  ${BOLD}PENGUJIAN & DIAGNOSTIK:${RESET}"
echo -e "    sudo tor-proxy -t           : Uji kebocoran IP dan DNS"
echo -e "    sudo tor-proxy -s -v        : Hidupkan dengan Output Verbose (Debug)"
echo -e "    sudo tor-proxy --cleanup    : Lenyapkan konfigurasi saat error"
echo -e "  ${CYAN}─────────────────────────────────────────────────────────${RESET}"
echo ""