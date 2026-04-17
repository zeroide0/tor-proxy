#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tor-proxy.py — Enterprise Transparent Tor Proxy untuk Ubuntu/Debian
Versi     : 4.2.0 (Enterprise 2026 Edition - Nftables Native)
Arsitektur: Native Nftables Support, OOP Modular, Stem Integration, 
            Loopback Bypass, Verbose Logging, Advanced Bootstrapping.
"""

import os
import sys
import time
import signal
import logging
import argparse
import subprocess
import urllib.request
import urllib.error
import json
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

# ==============================================================================
# 1. KONFIGURASI DAN VARIABEL GLOBAL
# ==============================================================================
VERSION = "4.2.0"

# Direktori dan File Sistem
TORRC_PATH = "/etc/tor/torrc"
RESOLV_PATH = "/etc/resolv.conf"
UBUNTU_RESOLV_SYMLINK = "/run/systemd/resolve/stub-resolv.conf"
STATE_DIR = "/var/run/tor-proxy"
LOG_FILE = "/var/log/tor-proxy.log"
LOCK_FILE = f"{STATE_DIR}/proxy.lock"

# Port Konfigurasi Tor
TOR_TRANS_PORT = 9040
TOR_DNS_PORT = 5353
TOR_CTRL_PORT = 9051

# Penanda Konfigurasi Torrc (Fix Terpasang)
MARKER_BEGIN = "# === BEGIN TOR PROXY CONFIGURATION ==="
MARKER_END = "# === END TOR PROXY CONFIGURATION ==="

TORRC_CONFIG_BLOCK = f"""{MARKER_BEGIN}
# Konfigurasi otomatis Tor-Proxy. Jangan diedit manual.
VirtualAddrNetwork 10.192.0.0/10
AutomapHostsOnResolve 1
TransPort {TOR_TRANS_PORT}
DNSPort {TOR_DNS_PORT}
ControlPort {TOR_CTRL_PORT}
CookieAuthentication 1
{MARKER_END}
"""

# API Pemeriksaan IP
API_IP_CHECK = [
    "http://ip-api.com/json/",
    "https://api.myip.com",
    "https://ifconfig.me/all.json"
]

# Modul Stem (Tor Controller)
try:
    from stem.control import Controller
    from stem import Signal
    STEM_AVAILABLE = True
except ImportError:
    STEM_AVAILABLE = False


# ==============================================================================
# 2. SISTEM PEWARNAAN & UI TERMINAL
# ==============================================================================
class Warna:
    HIJAU = '\033[92m'
    MERAH = '\033[31m'
    KUNING = '\033[93m'
    BIRU = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

class UI:
    verbose_mode = False

    @staticmethod
    def info(pesan):
        print(f"  {Warna.BIRU}[*]{Warna.RESET} {pesan}")
        logging.info(pesan)

    @staticmethod
    def sukses(pesan):
        print(f"  {Warna.HIJAU}[✓]{Warna.RESET} {pesan}")
        logging.info(f"[SUKSES] {pesan}")

    @staticmethod
    def error(pesan):
        print(f"  {Warna.MERAH}[✗]{Warna.RESET} {pesan}")
        logging.error(pesan)

    @staticmethod
    def peringatan(pesan):
        print(f"  {Warna.KUNING}[!]{Warna.RESET} {pesan}")
        logging.warning(pesan)

    @staticmethod
    def debug(pesan):
        logging.debug(pesan)
        if UI.verbose_mode:
            print(f"  {Warna.CYAN}[DEBUG] {pesan}{Warna.RESET}")

    @staticmethod
    def header(judul):
        lebar = len(judul) + 6
        garis = "═" * lebar
        print(f"\n{Warna.BOLD}{Warna.CYAN}╔{garis}╗")
        print(f"║   {judul}   ║")
        print(f"╚{garis}╝{Warna.RESET}\n")

    @staticmethod
    def tampilkan_peringatan_awal():
        print(f"{Warna.KUNING}{Warna.BOLD}")
        print("  [!] PERINGATAN KEAMANAN (TRANSPARENT PROXY):")
        print("      - Seluruh lalu lintas OS dialihkan ke jaringan Tor.")
        print("      - Bukan pengganti Tor Browser untuk anonimitas level tertinggi.")
        print(f"{Warna.RESET}")


# ==============================================================================
# 3. KELAS MANAJEMEN SISTEM
# ==============================================================================
class SistemUtils:
    @staticmethod
    def cek_root():
        if os.geteuid() != 0:
            UI.error("Akses root diperlukan. Gunakan 'sudo'.")
            sys.exit(1)

    @staticmethod
    def inisialisasi_direktori():
        if not os.path.exists(STATE_DIR):
            os.makedirs(STATE_DIR, mode=0o755)

    @staticmethod
    def jalankan_perintah(perintah, abaikan_error=False, tampilkan_output=False):
        UI.debug(f"Mengeksekusi: {' '.join(perintah)}")
        try:
            hasil = subprocess.run(perintah, capture_output=not tampilkan_output, text=True, check=not abaikan_error)
            UI.debug(f"Hasil Eksekusi: {hasil.stdout.strip()}")
            return hasil
        except subprocess.CalledProcessError as e:
            UI.debug(f"Eksekusi Gagal ({e.returncode}): {e.stderr.strip()}")
            if abaikan_error: return e
            raise Exception(f"Kegagalan sistem: {' '.join(perintah)}")

    @staticmethod
    def hitung_checksum(path_file):
        if not os.path.exists(path_file): return None
        sha256 = hashlib.sha256()
        try:
            with open(path_file, "rb") as f:
                for blok in iter(lambda: f.read(4096), b""): sha256.update(blok)
            return sha256.hexdigest()
        except Exception: return None

    @staticmethod
    def cek_konflik():
        UI.info("Menganalisis lingkungan sistem...")
        
        # UFW Check
        ufw_status = SistemUtils.jalankan_perintah(["ufw", "status"], abaikan_error=True).stdout
        if "active" in ufw_status.lower():
            UI.peringatan("KONFLIK POTENSIAL: UFW aktif. Ini dapat menimpa aturan iptables Tor.")
            
        # Docker Check
        if "docker0" in SistemUtils.jalankan_perintah(["ip", "link", "show"], abaikan_error=True).stdout:
            UI.peringatan("INFORMASI: Jaringan Docker terdeteksi. Pastikan kontainer menggunakan DNS yang aman.")


# ==============================================================================
# 4. KELAS MANAJEMEN FIREWALL (NATIVE NFTABLES + IPTABLES FALLBACK)
# ==============================================================================
class FirewallManager:
    def __init__(self):
        SistemUtils.inisialisasi_direktori()
        # Deteksi Nftables Asli (Saran Prioritas 1)
        self.gunakan_nftables = shutil.which("nft") is not None
        
        self.waktu_sekarang = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.file_backup_v4 = f"{STATE_DIR}/iptables_v4.bak"
        self.file_backup_v6 = f"{STATE_DIR}/iptables_v6.bak"
        self.file_meta = f"{STATE_DIR}/backup_metadata.json"

    def backup_aturan_asli(self):
        if self.gunakan_nftables:
            UI.info("Backend 'nftables' terdeteksi. Tabel 'tor_proxy' terisolasi akan digunakan.")
            UI.debug("Backup total tidak diperlukan karena nftables memungkinkan isolasi tabel yang bersih.")
            return

        # Fallback ke Iptables Backup
        UI.info("Backend legacy 'iptables' terdeteksi. Melakukan backup konfigurasi asli...")
        try:
            out_v4 = SistemUtils.jalankan_perintah(["iptables-save"]).stdout
            with open(self.file_backup_v4, 'w') as f: f.write(out_v4)
            hash_v4 = SistemUtils.hitung_checksum(self.file_backup_v4)

            out_v6 = SistemUtils.jalankan_perintah(["ip6tables-save"]).stdout
            with open(self.file_backup_v6, 'w') as f: f.write(out_v6)
            hash_v6 = SistemUtils.hitung_checksum(self.file_backup_v6)

            with open(self.file_meta, 'w') as f:
                json.dump({"file_v4": self.file_backup_v4, "hash_v4": hash_v4, "file_v6": self.file_backup_v6, "hash_v6": hash_v6, "timestamp": self.waktu_sekarang}, f)
            UI.sukses("Backup Iptables berhasil diamankan.")
        except Exception as e:
            raise Exception(f"Gagal mem-backup firewall: {e}")

    def restore_aturan_asli(self):
        if self.gunakan_nftables:
            UI.info("Menghapus tabel Nftables Tor-Proxy...")
            SistemUtils.jalankan_perintah(["nft", "delete", "table", "inet", "tor_proxy"], abaikan_error=True)
            UI.sukses("Aturan Nftables dibersihkan. Konfigurasi bawaan Anda tetap utuh.")
            return

        # Fallback Iptables Restore
        UI.info("Memulihkan konfigurasi Iptables dari backup...")
        berhasil = False
        if os.path.exists(self.file_meta):
            try:
                with open(self.file_meta, 'r') as f: metadata = json.load(f)
                file_v4 = metadata.get("file_v4")
                if file_v4 and os.path.exists(file_v4) and SistemUtils.hitung_checksum(file_v4) == metadata.get("hash_v4"):
                    subprocess.run(["iptables-restore"], input=Path(file_v4).read_text(), text=True, check=True)
                    berhasil = True
                    UI.sukses("Iptables IPv4 dipulihkan.")
                file_v6 = metadata.get("file_v6")
                if file_v6 and os.path.exists(file_v6) and SistemUtils.hitung_checksum(file_v6) == metadata.get("hash_v6"):
                    subprocess.run(["ip6tables-restore"], input=Path(file_v6).read_text(), text=True, check=True)
                os.remove(self.file_meta)
            except Exception as e:
                UI.peringatan(f"Gagal memulihkan metadata backup: {e}")

        if not berhasil:
            UI.peringatan("Melakukan FLUSH DARURAT Iptables...")
            for cmd in [["iptables", "-P", "INPUT", "ACCEPT"], ["iptables", "-P", "OUTPUT", "ACCEPT"], ["iptables", "-t", "nat", "-F"], ["iptables", "-F"], ["ip6tables", "-F"]]:
                SistemUtils.jalankan_perintah(cmd, abaikan_error=True)

    def terapkan_aturan_tor(self, tor_uid, port_pengecualian=None, redirect_dns=True):
        if self.gunakan_nftables:
            self._terapkan_nftables(tor_uid, port_pengecualian, redirect_dns)
        else:
            self._terapkan_iptables(tor_uid, port_pengecualian, redirect_dns)

    def _terapkan_nftables(self, tor_uid, port_pengecualian, redirect_dns):
        """Menerapkan aturan Nftables yang elegan, modern, dan tidak merusak konfigurasi Docker (Prioritas 1)."""
        UI.info("Membangun aturan Nftables (Native Mode)...")
        
        # Bersihkan aturan lama jika ada
        SistemUtils.jalankan_perintah(["nft", "delete", "table", "inet", "tor_proxy"], abaikan_error=True)

        aturan_dns = ""
        if redirect_dns:
            aturan_dns = f"""
                udp dport 53 redirect to :{TOR_DNS_PORT}
                tcp dport 53 redirect to :{TOR_DNS_PORT}
            """
            
        aturan_pengecualian = ""
        if port_pengecualian:
            ports = port_pengecualian.replace(",", ", ")
            aturan_pengecualian = f"tcp dport {{ {ports} }} accept"
            UI.info(f"-> Port Dikecualikan: {port_pengecualian}")

        # Definisi Ruleset Nftables
        nft_ruleset = f"""
        table inet tor_proxy {{
            chain nat_out {{
                type nat hook output priority dstnat; policy accept;
                
                # Cegah Tor masuk ke loop
                meta skuid "{tor_uid}" accept
                
                # Wajib: Redirect DNS KELUAR sebelum bypass localhost, agar requests ke 127.0.0.1:53 tertangkap
                {aturan_dns}
                {aturan_pengecualian}
                
                # Bypass Antarmuka Lokal (Loopback) - Mengatasi Saran Prioritas 2 (Loop Bypass)
                oifname "lo" accept
                
                # Bypass Jaringan Lokal (LAN)
                ip daddr {{ 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 }} accept
                
                # Alihkan seluruh TCP ke TransPort Tor
                meta l4proto tcp redirect to :{TOR_TRANS_PORT}
            }}
            
            chain filter_out {{
                type filter hook output priority filter; policy accept;
                
                meta skuid "{tor_uid}" accept
                oifname "lo" accept
                ct state established,related accept
                
                ip daddr {{ 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 }} accept
                {aturan_pengecualian}
                
                # Blokir Eksplisit ICMP Echo (Ping)
                icmp type echo-request reject
                
                # Blokir mutlak IPv6 agar tidak bocor
                meta nfproto ipv6 drop
                
                # Tolak semua paket nyasar (UDP, ICMP non-standar, dll) yang tidak dialihkan
                reject
            }}
        }}
        """
        
        path_nft = f"{STATE_DIR}/tor_rules.nft"
        with open(path_nft, "w") as f:
            f.write(nft_ruleset)
            
        SistemUtils.jalankan_perintah(["nft", "-f", path_nft])
        os.remove(path_nft)
        UI.sukses("Firewall Nftables tingkat maksimum berhasil diterapkan.")

    def _terapkan_iptables(self, tor_uid, port_pengecualian, redirect_dns):
        """Metode cadangan Iptables klasik dengan pengamanan Loopback."""
        UI.info("Membangun aturan Iptables (Legacy Mode)...")

        aturan = [
            ["iptables", "-F"],
            ["iptables", "-t", "nat", "-F"],
            ["iptables", "-t", "nat", "-A", "OUTPUT", "-m", "owner", "--uid-owner", tor_uid, "-j", "RETURN"],
        ]

        if redirect_dns:
            aturan.extend([
                ["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "udp", "--dport", "53", "-j", "REDIRECT", "--to-ports", str(TOR_DNS_PORT)],
                ["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--dport", "53", "-j", "REDIRECT", "--to-ports", str(TOR_DNS_PORT)]
            ])

        if port_pengecualian:
            aturan.append(["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "-m", "multiport", "--dports", port_pengecualian, "-j", "RETURN"])
            UI.info(f"-> Pengecualian Port: {port_pengecualian}")

        # Bypass antarmuka Loopback (Diletakkan SETELAH intercept DNS)
        aturan.append(["iptables", "-t", "nat", "-A", "OUTPUT", "-o", "lo", "-j", "RETURN"])

        jaringan_lokal = ["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12", "127.0.0.0/8"]
        for subnet in jaringan_lokal:
            aturan.append(["iptables", "-t", "nat", "-A", "OUTPUT", "-d", subnet, "-j", "RETURN"])

        aturan.append(["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--syn", "-j", "REDIRECT", "--to-ports", str(TOR_TRANS_PORT)])

        # Tabel Filter
        aturan.extend([
            ["iptables", "-A", "OUTPUT", "-o", "lo", "-j", "ACCEPT"],
            ["iptables", "-A", "OUTPUT", "-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
        ])
        
        for subnet in jaringan_lokal: aturan.append(["iptables", "-A", "OUTPUT", "-d", subnet, "-j", "ACCEPT"])
        if port_pengecualian: aturan.append(["iptables", "-A", "OUTPUT", "-p", "tcp", "-m", "multiport", "--dports", port_pengecualian, "-j", "ACCEPT"])
        
        aturan.extend([
            ["iptables", "-A", "OUTPUT", "-m", "owner", "--uid-owner", tor_uid, "-j", "ACCEPT"],
            ["iptables", "-A", "OUTPUT", "-p", "icmp", "-m", "icmp", "--icmp-type", "echo-request", "-j", "REJECT"],
            ["iptables", "-A", "OUTPUT", "-j", "REJECT"]
        ])

        for baris in aturan: SistemUtils.jalankan_perintah(baris)

        SistemUtils.jalankan_perintah(["ip6tables", "-F"])
        SistemUtils.jalankan_perintah(["ip6tables", "-P", "OUTPUT", "DROP"])
        UI.sukses("Firewall Iptables diterapkan (Loopback Bypassed & ICMP Dropped).")


# ==============================================================================
# 5. KELAS MANAJEMEN DNS
# ==============================================================================
class DNSManager:
    @staticmethod
    def paksa_dns_tor():
        SistemUtils.jalankan_perintah(["rm", "-f", RESOLV_PATH], abaikan_error=True)
        try:
            with open(RESOLV_PATH, 'w') as f:
                f.write("nameserver 127.0.0.1\n")
            UI.sukses("Sistem DNS di-intercept ke jaringan Tor.")
        except Exception as e:
            UI.error(f"Gagal menulis resolv.conf: {e}")

    @staticmethod
    def pulihkan_dns_sistem():
        UI.info("Memulihkan resolusi DNS bawaan sistem...")
        SistemUtils.jalankan_perintah(["rm", "-f", RESOLV_PATH], abaikan_error=True)
        
        if os.path.exists(UBUNTU_RESOLV_SYMLINK):
            SistemUtils.jalankan_perintah(["ln", "-sf", UBUNTU_RESOLV_SYMLINK, RESOLV_PATH], abaikan_error=True)
        else:
            with open(RESOLV_PATH, 'w') as f: f.write("nameserver 8.8.8.8\n")

        SistemUtils.jalankan_perintah(["systemctl", "restart", "systemd-resolved"], abaikan_error=True)
        SistemUtils.jalankan_perintah(["resolvectl", "flush-caches"], abaikan_error=True)
        UI.sukses("DNS berhasil dipulihkan & Flush Cache selesai.")


# ==============================================================================
# 6. KELAS MANAJEMEN LAYANAN TOR
# ==============================================================================
class TorManager:
    @staticmethod
    def dapatkan_tor_uid():
        for user in ["debian-tor", "tor"]:
            hasil = SistemUtils.jalankan_perintah(["id", "-u", user], abaikan_error=True)
            if hasil.returncode == 0: return hasil.stdout.strip()
        raise Exception("Numeric UID Tor tidak ditemukan.")

    @staticmethod
    def konfigurasi_torrc(gunakan_bridges=False, country_code=None):
        konten = Path(TORRC_PATH).read_text() if Path(TORRC_PATH).exists() else ""
        if MARKER_BEGIN in konten: 
            TorManager.bersihkan_konfigurasi_torrc()

        blok_list = [
            MARKER_BEGIN,
            "# Konfigurasi otomatis Tor-Proxy. Jangan diedit manual.",
            "VirtualAddrNetwork 10.192.0.0/10",
            "AutomapHostsOnResolve 1",
            f"TransPort {TOR_TRANS_PORT}",
            f"DNSPort {TOR_DNS_PORT}",
            f"ControlPort {TOR_CTRL_PORT}",
            "CookieAuthentication 1"
        ]

        if country_code:
            code = country_code if country_code.startswith('{') else f"{{{country_code}}}"
            blok_list.append(f"ExitNodes {code}")
            blok_list.append("StrictNodes 1")

        if gunakan_bridges:
            blok_list.append("UseBridges 1\n# Tambahkan list Bridge Anda di bawah ini")

        blok_list.append(MARKER_END)
        blok = "\n".join(blok_list)

        try:
            with open(TORRC_PATH, 'a') as f: f.write("\n" + blok)
            UI.sukses("Konfigurasi Tor-Proxy berhasil ditulis ke torrc.")
        except Exception as e:
            raise Exception(f"Gagal menulis ke torrc: {e}")
        
    @staticmethod
    def bersihkan_konfigurasi_torrc():
        if not Path(TORRC_PATH).exists(): return
        with open(TORRC_PATH, 'r') as f: baris_teks = f.readlines()
        
        baris_bersih, dalam_blok = [], False
        for baris in baris_teks:
            if MARKER_BEGIN in baris: dalam_blok = True; continue
            if MARKER_END in baris: dalam_blok = False; continue
            if not dalam_blok: baris_bersih.append(baris)

        with open(TORRC_PATH, 'w') as f: f.writelines(baris_bersih)

    @staticmethod
    def tunggu_bootstrap(timeout=45):
        """Memanfaatkan pustaka Stem untuk verifikasi bootstrap yang lebih persis (Prioritas 3)."""
        UI.info("Menunggu Tor menyinkronkan Bootstrap...")
        waktu_mulai = time.time()
        
        if STEM_AVAILABLE:
            UI.debug("Menggunakan pustaka Stem untuk mengawasi persentase bootstrap.")
            while time.time() - waktu_mulai < timeout:
                try:
                    with Controller.from_port(port=TOR_CTRL_PORT) as controller:
                        controller.authenticate()
                        fase = controller.get_info("status/bootstrap-phase")
                        UI.debug(f"Status Tor: {fase}")
                        if "PROGRESS=100" in fase:
                            UI.sukses("Tor Bootstrap selesai 100%.")
                            return True
                except Exception as e:
                    UI.debug(f"Stem belum dapat terhubung (menunggu Tor siap): {e}")
                time.sleep(1)
            UI.peringatan("Verifikasi Stem Timeout. Fallback ke utilitas socket...")

        # Fallback SS (Socket Statistics)
        waktu_mulai = time.time()
        while time.time() - waktu_mulai < timeout:
            if SistemUtils.jalankan_perintah(["systemctl", "is-active", "tor"], abaikan_error=True).stdout.strip() == "active":
                cek_port = SistemUtils.jalankan_perintah(["ss", "-tlnp"], abaikan_error=True).stdout
                if str(TOR_TRANS_PORT) in cek_port:
                    UI.sukses("Tor telah membuka port TransPort.")
                    return True
            time.sleep(1.5)
        return False

    @staticmethod
    def ganti_identitas(waktu_tunggu_fallback=5):
        UI.info("Meminta Sirkuit Baru (NEWNYM)...")

        if STEM_AVAILABLE:
            try:
                with Controller.from_port(port=TOR_CTRL_PORT) as controller:
                    controller.authenticate()
                    controller.signal(Signal.NEWNYM)
                    try:
                        waktu_tunggu = max(controller.get_newnym_wait(), 2)
                        UI.info(f"Jaringan Tor meminta jeda {waktu_tunggu} detik untuk sirkuit baru.")
                        time.sleep(waktu_tunggu)
                    except:
                        time.sleep(waktu_tunggu_fallback)
                UI.sukses("Sirkuit baru berhasil dibangun (Via Stem).")
                return True
            except Exception as e:
                UI.peringatan(f"Stem gagal ({e}). Menggunakan Netcat...")

        # Netcat Cookie Auth
        cookie_path = "/run/tor/control.authcookie"
        try:
            cookie_hex = Path(cookie_path).read_bytes().hex()
            cmd = f"echo -e 'AUTHENTICATE {cookie_hex}\\nSIGNAL NEWNYM\\nQUIT' | nc -w 3 127.0.0.1 {TOR_CTRL_PORT}"
            if "250 OK" in SistemUtils.jalankan_perintah(["bash", "-c", cmd], abaikan_error=True).stdout:
                time.sleep(waktu_tunggu_fallback)
                return True
        except Exception:
            # Empty Auth Fallback
            cmd = f"echo -e 'AUTHENTICATE \"\"\\nSIGNAL NEWNYM\\nQUIT' | nc -w 3 127.0.0.1 {TOR_CTRL_PORT}"
            if "250 OK" in SistemUtils.jalankan_perintah(["bash", "-c", cmd], abaikan_error=True).stdout:
                time.sleep(waktu_tunggu_fallback)
                return True

        UI.error("Semua metode ganti identitas gagal.")
        return False


# ==============================================================================
# 7. KELAS PENGECEKAN KESEHATAN DAN KEBOCORAN (LEAK TESTING)
# ==============================================================================
class LeakTester:
    @staticmethod
    def dapatkan_ip_publik():
        for url in API_IP_CHECK:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = response.read().decode('utf-8')
                    try:
                        j = json.loads(data)
                        return j.get("query") or j.get("ip") or j.get("ip_addr")
                    except: return data.strip()
            except: continue
        return "TIDAK_DIKETAHUI"

    @staticmethod
    def uji_kebocoran_dns():
        UI.info("Uji Kebocoran DNS (Menganalisis IP Resolver)...")
        try:
            hasil = SistemUtils.jalankan_perintah(["dig", "+short", "whoami.akamai.net"], abaikan_error=True)
            ip_resolver = hasil.stdout.strip().split('\n')[0]
            if ip_resolver and "." in ip_resolver:
                print(f"  {Warna.KUNING}IP DNS Resolver  : {ip_resolver}{Warna.RESET}")
                UI.sukses("DNS di-resolve oleh server di atas.")
            else:
                UI.peringatan("Gagal mengekstrak IP Resolver (Periksa ketersediaan paket 'dnsutils').")
        except Exception as e:
            UI.peringatan(f"Uji DNS dilewati: {e}")

    @staticmethod
    def uji_kebocoran_rinci():
        UI.header("PENGUJIAN KEBOCORAN (LEAK TEST)")
        LeakTester.uji_kebocoran_dns()
        
        UI.info("Menghubungi server deteksi IP geografis...")
        try:
            req = urllib.request.Request("http://ip-api.com/json/", headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                info = json.loads(response.read().decode('utf-8'))
                
                print(f"  {Warna.KUNING}IP Publik        : {info.get('query', 'Unknown')}{Warna.RESET}")
                print(f"  {Warna.KUNING}Penyedia (ISP)   : {info.get('isp', 'Unknown')}{Warna.RESET}")
                print(f"  {Warna.KUNING}Lokasi Terdeteksi: {info.get('country', 'Unknown')}{Warna.RESET}")
                
                isp = info.get("isp", "")
                if any(x in isp for x in ["Tor", "Quintex", "Censys", "Mullvad", "Data Center", "Hosting"]):
                    UI.sukses("Koneksi TERVERIFIKASI AMAN. (ISP komersial/Tor).")
                else:
                    UI.peringatan("PERINGATAN: Jika nama ISP di atas adalah langganan rumah Anda, ANDA MENGALAMI KEBOCORAN!")
        except Exception as e:
            UI.error(f"Uji koneksi ke API gagal: {e}")


# ==============================================================================
# 8. SISTEM FAILSAFE DAN CONTROLLER UTAMA
# ==============================================================================
def pasang_lock_file():
    SistemUtils.inisialisasi_direktori()
    if os.path.exists(LOCK_FILE):
        UI.error(f"Skrip sedang berjalan! Jika ini adalah error sebelumnya, gunakan --cleanup")
        sys.exit(1)
    with open(LOCK_FILE, 'w') as f: f.write(str(os.getpid()))

def prosedur_rollback_darurat():
    UI.peringatan("Memulai Rollback Sistem Darurat...")
    FirewallManager().restore_aturan_asli()
    DNSManager.pulihkan_dns_sistem()
    if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)
    UI.sukses("Sistem dipulihkan ke kondisi normal.")

def tangani_interupsi(sig, frame):
    print(f"\n{Warna.MERAH}{Warna.BOLD}[!] INTERUPSI PENGGUNA (Ctrl+C).{Warna.RESET}")
    if os.path.exists(LOCK_FILE): prosedur_rollback_darurat()
    sys.exit(1)

def mulai_layanan(args):
    SistemUtils.cek_root()
    SistemUtils.cek_konflik()

    # Menambahkan fungsi pemilihan exit node
    country_code = None
    if args.country:
        country_code = pilih_negara_exit_node()

    UI.tampilkan_peringatan_awal()
    UI.header(f"MEMULAI TOR PROXY v{VERSION}")
    
    pasang_lock_file()
    try:
        # Mengirimkan country_code ke konfigurasi
        TorManager.konfigurasi_torrc(args.use_bridges, country_code) 
        
        UI.info("Merestart layanan background Tor...")
        SistemUtils.jalankan_perintah(["systemctl", "restart", "tor"])
        if not TorManager.tunggu_bootstrap(): raise Exception("Tor Bootstrap Timeout.")

        fm = FirewallManager()
        fm.backup_aturan_asli()
        fm.terapkan_aturan_tor(TorManager.dapatkan_tor_uid(), args.exclude_ports, not args.no_dns_redirect)
        
        if not args.no_dns_redirect: DNSManager.paksa_dns_tor()

        ip_publik = LeakTester.dapatkan_ip_publik()
        print(f"\n  {Warna.KUNING}{Warna.BOLD}IP SAMARAN ANDA : {ip_publik}{Warna.RESET}\n")
    except Exception as e:
        UI.error(f"Kegagalan inisialisasi kritis: {e}")
        prosedur_rollback_darurat()
        sys.exit(1)

def hentikan_layanan():
    SistemUtils.cek_root()
    UI.header("MEMATIKAN TOR PROXY")
    prosedur_rollback_darurat()
    print(f"\n  {Warna.KUNING}{Warna.BOLD}IP ASLI ANDA : {LeakTester.dapatkan_ip_publik()}{Warna.RESET}\n")

def pilih_negara_exit_node():
    daftar_negara = {
        "1": ("Amerika Serikat (US)", "us"),
        "2": ("Jepang (JP)", "jp"),
        "3": ("Jerman (DE)", "de"),
        "4": ("Belanda (NL)", "nl"),
        "5": ("Inggris (GB)", "gb"),
        "6": ("Kanada (CA)", "ca"),
        "7": ("Singapura (SG)", "sg"),
        "8": ("Swiss (CH)", "ch"),
        "9": ("Australia (AU)", "au"),
        "0": ("Acak / Default Tor", None)
    }

    print(f"\n  {Warna.CYAN}{Warna.BOLD}=== PILIH NEGARA EXIT NODE ==={Warna.RESET}")
    for key, (nama, _) in daftar_negara.items():
        print(f"    [{key}] {nama}")

    while True:
        try:
            pilihan = input(f"\n  {Warna.KUNING}Masukkan angka pilihan Anda (0-9): {Warna.RESET}").strip()
            if pilihan in daftar_negara:
                nama, kode = daftar_negara[pilihan]
                if kode:
                    UI.info(f"Anda memilih Exit Node: {nama} {{{kode}}}")
                else:
                    UI.info("Anda memilih Exit Node Acak (Default Tor).")
                return kode
            else:
                print(f"  {Warna.MERAH}[!] Pilihan tidak valid, silakan coba lagi.{Warna.RESET}")
        except KeyboardInterrupt:
            print(f"\n  {Warna.MERAH}[!] Dibatalkan oleh pengguna.{Warna.RESET}")
            sys.exit(1)

# ==============================================================================
# 9. MAIN ARGUMENT PARSER
# ==============================================================================
def main():
    signal.signal(signal.SIGINT, tangani_interupsi)
    signal.signal(signal.SIGTERM, tangani_interupsi)

    parser = argparse.ArgumentParser(description=f"Tor-Proxy Enterprise v{VERSION}")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument('-s', '--start', action='store_true')
    grp.add_argument('-x', '--stop', action='store_true')
    grp.add_argument('-r', '--restart', action='store_true')
    grp.add_argument('-n', '--newnym', action='store_true')
    grp.add_argument('-t', '--test-leak', action='store_true')
    grp.add_argument('--cleanup', action='store_true')
    grp.add_argument('-i', '--ip', action='store_true')

    parser.add_argument('--exclude-ports', type=str, help='Bypass port, misal: 22,3389')
    parser.add_argument('--no-dns-redirect', action='store_true')
    parser.add_argument('--use-bridges', action='store_true')
    parser.add_argument('--wait', type=int, default=5)
    # Di dalam fungsi main(), ubah argumen -c menjadi seperti ini:
    parser.add_argument('-c', '--country', action='store_true', help='Tampilkan menu interaktif untuk memilih negara Exit Node')
    
    # Opsi Verbose (Saran Prioritas 3)
    parser.add_argument('-v', '--verbose', action='store_true', help='Tampilkan log eksekusi teknis tingkat lanjut')

    args = parser.parse_args()

    # Konfigurasi Perekaman Log
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(filename=LOG_FILE, level=log_level, format='[%(asctime)s] %(levelname)s: %(message)s')
    
    if args.verbose:
        UI.verbose_mode = True
        UI.debug("Mode Verbose diaktifkan. Melacak seluruh eksekusi shell...")

    if args.start: mulai_layanan(args)
    elif args.stop: hentikan_layanan()
    elif args.restart: hentikan_layanan(); time.sleep(2); mulai_layanan(args)
    elif args.newnym: 
        SistemUtils.cek_root()
        if TorManager.ganti_identitas(args.wait):
            print(f"\n  {Warna.KUNING}{Warna.BOLD}IP BARU : {LeakTester.dapatkan_ip_publik()}{Warna.RESET}\n")
    elif args.test_leak: LeakTester.uji_kebocoran_rinci()
    elif args.cleanup: 
        SistemUtils.cek_root()
        prosedur_rollback_darurat()
        TorManager.bersihkan_konfigurasi_torrc()
        SistemUtils.jalankan_perintah(["systemctl", "restart", "tor"], abaikan_error=True)
        UI.sukses("Pembersihan total selesai.")
    elif args.ip: print(f"\n  {Warna.KUNING}IP SAAT INI : {LeakTester.dapatkan_ip_publik()}{Warna.RESET}\n")

if __name__ == "__main__":
    main()