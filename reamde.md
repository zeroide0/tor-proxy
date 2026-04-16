# 🧅 Tor-Proxy Enterprise
### Transparent Tor Proxy untuk Ubuntu / Debian
**Versi:** `4.2.0` — *Enterprise 2026 Edition · Nftables Native*

> Alihkan **seluruh lalu lintas jaringan sistem operasi** secara transparan melalui jaringan Tor — tanpa konfigurasi manual di tiap aplikasi.

---

## 📑 Daftar Isi

- [Tentang Proyek](#tentang-proyek)
- [Fitur Utama](#fitur-utama)
- [Cara Kerja](#cara-kerja)
- [Persyaratan Sistem](#persyaratan-sistem)
- [Instalasi](#instalasi)
- [Uninstalasi](#uninstalasi)
- [Penggunaan](#penggunaan)
- [Opsi Lanjutan](#opsi-lanjutan)
- [Arsitektur Teknis](#arsitektur-teknis)
- [Pengujian & Diagnostik](#pengujian--diagnostik)
- [Penanganan Error & Failsafe](#penanganan-error--failsafe)
- [Catatan Keamanan](#catatan-keamanan)
- [Pertanyaan Umum (FAQ)](#pertanyaan-umum-faq)

---

## Tentang Proyek

**Tor-Proxy Enterprise** adalah skrip Python berbasis sistem yang mengotomasi proses pengalihan seluruh koneksi jaringan pada level OS ke jaringan Tor melalui mekanisme *transparent proxy*. Tidak seperti Tor Browser yang hanya melindungi satu aplikasi, tool ini mengamankan **semua koneksi outbound** di sistem Anda — termasuk aplikasi yang tidak mendukung konfigurasi proxy secara native.

Skrip ini menggunakan arsitektur OOP modular dengan dukungan **Native Nftables** (firewall modern Linux) dan fallback otomatis ke **Iptables** (firewall legacy), serta integrasi pustaka **Stem** untuk kontrol Tor tingkat lanjut.

---

## Fitur Utama

| Fitur | Keterangan |
|---|---|
| 🔥 **Native Nftables** | Menggunakan tabel terisolasi `inet tor_proxy` — tidak mengganggu aturan firewall yang sudah ada (termasuk Docker) |
| 🔄 **Fallback Iptables** | Otomatis beralih ke iptables klasik jika nft tidak tersedia |
| 🧠 **Stem Integration** | Pemantauan bootstrap Tor dengan persentase akurat & rotasi IP via `NEWNYM` |
| 🛡️ **DNS Leak Prevention** | Mengalihkan query DNS (port 53) ke `DNSPort` Tor — mencegah kebocoran DNS |
| 🔁 **Rotasi IP Otomatis** | Ganti sirkuit Tor dan dapatkan IP baru kapan pun |
| 💾 **Backup & Restore Firewall** | Backup aturan iptables asli beserta checksum SHA-256 sebelum modifikasi |
| 🌉 **Dukungan Bridge** | Opsi `--use-bridges` untuk melewati sensor ISP/negara |
| 🚨 **Failsafe & Rollback** | Rollback darurat otomatis jika terjadi error atau interupsi (Ctrl+C) |
| 🔍 **Leak Tester** | Uji kebocoran IP dan DNS secara real-time dari terminal |
| 📋 **Verbose Logging** | Mode debug untuk melacak setiap eksekusi perintah ke log dan terminal |
| 🔒 **IPv6 Blocking** | Memblokir seluruh lalu lintas IPv6 agar tidak bocor keluar Tor |
| 🚪 **Port Exclusion** | Bypass port tertentu (misalnya SSH) agar tetap terhubung langsung |

---

## Cara Kerja

```
  Aplikasi di OS Anda
        │
        ▼ (semua koneksi TCP/UDP)
  ┌─────────────────────┐
  │  Firewall (Kernel)  │  ← Nftables / Iptables Rule
  │  tabel: tor_proxy   │
  └─────────────────────┘
        │
        ▼ REDIRECT ke port lokal
  ┌─────────────────────┐
  │   Tor Daemon        │
  │  TransPort :9040    │  ← Transparent TCP Proxy
  │  DNSPort   :5353    │  ← DNS melalui Tor
  │  ControlPort:9051   │  ← Kontrol via Stem/Netcat
  └─────────────────────┘
        │
        ▼
  Jaringan Tor (Onion Network)
        │
        ▼
  Internet (dengan IP Anonim)
```

**Alur Pengalihan:**
1. `tor-proxy -s` dijalankan → daemon Tor di-restart & dikonfigurasi
2. Aturan firewall diterapkan: semua TCP dialihkan ke `TransPort 9040`, DNS ke `DNSPort 5353`
3. Loopback (`127.x.x.x`) dan jaringan LAN dikecualikan agar tidak ter-loop
4. Proses milik user `debian-tor` dikecualikan (Tor itu sendiri tidak ikut dialihkan)
5. DNS sistem (`/etc/resolv.conf`) ditulis ulang ke `127.0.0.1`

---

## Persyaratan Sistem

- **OS:** Ubuntu 20.04+ / Debian 11+
- **Akses:** `root` / `sudo`
- **Koneksi:** Aktif (untuk mengunduh dependensi saat instalasi pertama)

### Dependensi (Diinstal Otomatis)

| Paket | Fungsi |
|---|---|
| `tor` | Daemon utama jaringan Tor |
| `python3` | Runtime skrip |
| `python3-stem` | Library kontrol Tor (bootstrap monitor & NEWNYM) |
| `nftables` | Firewall modern (mode utama) |
| `iptables` | Firewall legacy (mode fallback) |
| `netcat-openbsd` | Fallback kontrol Tor via socket |
| `dnsutils` | Uji kebocoran DNS (`dig`) |
| `curl` | Utilitas jaringan tambahan |

---

## Instalasi

### Langkah 1 — Unduh / Siapkan File

Pastikan kedua file berikut berada di **direktori yang sama**:
```
tor-proxy.py
install.sh
```

### Langkah 2 — Beri Izin Eksekusi

```bash
chmod +x install.sh
```

### Langkah 3 — Jalankan Installer

```bash
sudo ./install.sh
```

Installer akan secara otomatis:
- Mengecek dan menginstal semua dependensi yang belum ada
- Mendaftarkan daemon `tor` ke autostart sistem (`systemctl enable tor`)
- Menyalin skrip ke `/usr/local/bin/tor-proxy` (tersedia global di PATH)
- Membuat file log di `/var/log/tor-proxy.log`
- Membuat direktori state di `/var/run/tor-proxy/`

### Verifikasi Instalasi

```bash
tor-proxy --help
```

---

## Uninstalasi

```bash
sudo ./install.sh --uninstall
```

Proses uninstalasi akan:
1. Menjalankan `--cleanup` untuk mengembalikan semua aturan firewall
2. Menghapus file eksekusi dari `/usr/local/bin/tor-proxy`
3. Menghapus log dan direktori state
4. Mengembalikan sistem ke kondisi semula

---

## Penggunaan

> ⚠️ Semua perintah membutuhkan akses **root** (`sudo`).

### Perintah Utama

```bash
# Mengaktifkan mode penyamaran (transparan proxy via Tor)
sudo tor-proxy -s

# Mematikan mode penyamaran & kembali ke IP asli
sudo tor-proxy -x

# Restart (matikan lalu hidupkan kembali)
sudo tor-proxy -r

# Rotasi IP: minta sirkuit Tor baru
sudo tor-proxy -n

# Cek IP publik saat ini
sudo tor-proxy -i
```

### Pengujian & Diagnostik

```bash
# Uji kebocoran IP dan DNS (tampilkan info lengkap)
sudo tor-proxy -t

# Jalankan dengan output debug penuh (verbose)
sudo tor-proxy -s -v

# Bersihkan konfigurasi jika ada error sebelumnya
sudo tor-proxy --cleanup
```

### Contoh Output saat Aktif

```
╔══════════════════════════════════╗
║   MEMULAI TOR PROXY v4.2.0      ║
╚══════════════════════════════════╝

  [*] Menganalisis lingkungan sistem...
  [✓] Konfigurasi Tor-Proxy berhasil ditulis ke torrc.
  [*] Merestart layanan background Tor...
  [*] Menunggu Tor menyinkronkan Bootstrap...
  [✓] Tor Bootstrap selesai 100%.
  [*] Membangun aturan Nftables (Native Mode)...
  [✓] Firewall Nftables tingkat maksimum berhasil diterapkan.
  [✓] Sistem DNS di-intercept ke jaringan Tor.

  IP SAMARAN ANDA : 185.220.xxx.xxx
```

---

## Opsi Lanjutan

```
Penggunaan: tor-proxy [OPSI UTAMA] [OPSI TAMBAHAN]

OPSI UTAMA (wajib pilih salah satu):
  -s, --start           Aktifkan transparent proxy
  -x, --stop            Matikan proxy & pulihkan sistem
  -r, --restart         Restart layanan proxy
  -n, --newnym          Rotasi sirkuit Tor (IP baru)
  -t, --test-leak       Uji kebocoran IP dan DNS
  -i, --ip              Tampilkan IP publik saat ini
      --cleanup         Rollback darurat & bersihkan konfigurasi

OPSI TAMBAHAN:
  --exclude-ports PORT  Bypass port tertentu dari tunneling Tor.
                        Berguna untuk SSH atau RDP.
                        Contoh: --exclude-ports 22,3389

  --no-dns-redirect     Jangan alihkan DNS ke Tor.
                        (Tidak disarankan, berisiko DNS leak)

  --use-bridges         Aktifkan dukungan Bridge Tor.
                        Gunakan jika Tor diblokir oleh ISP/negara Anda.
                        Edit /etc/tor/torrc setelah ini untuk menambah
                        daftar bridge.

  --wait DETIK          Waktu tunggu rotasi sirkuit (default: 5 detik)

  -v, --verbose         Tampilkan log eksekusi teknis secara real-time
```

### Contoh Penggunaan Lanjutan

```bash
# Aktifkan Tor, tapi bypass port SSH (22) & RDP (3389)
sudo tor-proxy -s --exclude-ports 22,3389

# Aktifkan dengan bridge (untuk melewati sensor)
sudo tor-proxy -s --use-bridges

# Aktifkan dengan mode debug penuh
sudo tor-proxy -s -v

# Rotasi IP dengan waktu tunggu 10 detik
sudo tor-proxy -n --wait 10
```

---

## Arsitektur Teknis

### Modul Utama (Kelas Python)

| Kelas | Fungsi |
|---|---|
| `SistemUtils` | Eksekusi perintah shell, cek root, inisialisasi direktori, deteksi konflik (UFW, Docker), checksum SHA-256 |
| `FirewallManager` | Backup & restore aturan firewall, penerapan aturan Nftables (prioritas) dan Iptables (fallback) |
| `DNSManager` | Intercept DNS ke Tor (`/etc/resolv.conf`), pemulihan DNS sistem via `systemd-resolved` |
| `TorManager` | Konfigurasi `torrc`, monitoring bootstrap via Stem, rotasi sirkuit (NEWNYM) |
| `LeakTester` | Uji kebocoran DNS (`dig whoami.akamai.net`) dan IP publik via multi-API |
| `UI` / `Warna` | Output terminal berwarna, logging ke file, mode verbose |

### Port Konfigurasi Tor

| Port | Fungsi |
|---|---|
| `9040` | `TransPort` — Penerima TCP yang dialihkan firewall |
| `5353` | `DNSPort` — Resolver DNS melalui Tor |
| `9051` | `ControlPort` — Kontrol daemon Tor (Stem / Netcat) |

### Konfigurasi Torrc (Ditambahkan Otomatis)

```
# === BEGIN TOR PROXY CONFIGURATION ===
VirtualAddrNetwork 10.192.0.0/10
AutomapHostsOnResolve 1
TransPort 9040
DNSPort 5353
ControlPort 9051
CookieAuthentication 1
# === END TOR PROXY CONFIGURATION ===
```

### Mekanisme Firewall (Nftables — Mode Utama)

Aturan diterapkan dalam tabel terisolasi `inet tor_proxy` yang **tidak menimpa** konfigurasi nftables/iptables yang sudah ada:

- **Loopback bypass** → `oifname "lo" accept` (mencegah loop pada ControlPort)
- **LAN bypass** → `127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16`
- **DNS redirect** → UDP/TCP port 53 → `DNSPort 5353`
- **TCP redirect** → Semua TCP → `TransPort 9040`
- **IPv6 drop** → `meta nfproto ipv6 drop` (cegah kebocoran IPv6)
- **ICMP reject** → Blokir ping keluar

### Mekanisme Rotasi Identitas (NEWNYM)

Urutan fallback saat `-n` dijalankan:
1. **Stem** → Koneksi ke `ControlPort 9051`, kirim sinyal `NEWNYM`
2. **Netcat + Cookie Auth** → Baca `/run/tor/control.authcookie`, kirim via `nc`
3. **Netcat + Empty Auth** → Fallback tanpa autentikasi cookie

---

## Pengujian & Diagnostik

### Uji Kebocoran Lengkap (`-t`)

```bash
sudo tor-proxy -t
```

Output contoh:
```
╔══════════════════════════════╗
║   PENGUJIAN KEBOCORAN       ║
╚══════════════════════════════╝

  [*] Uji Kebocoran DNS (Menganalisis IP Resolver)...
  [!] IP DNS Resolver  : 185.220.101.x
  [✓] DNS di-resolve oleh server di atas.
  [*] Menghubungi server deteksi IP geografis...
  [!] IP Publik        : 185.220.xxx.xxx
  [!] Penyedia (ISP)   : Tor Project / Exit Node
  [!] Lokasi Terdeteksi: Germany
  [✓] Koneksi TERVERIFIKASI AMAN. (ISP komersial/Tor).
```

> ⚠️ **Waspada:** Jika "Penyedia (ISP)" menampilkan nama ISP rumahan Anda (misalnya Telkomsel, IndiHome), **terjadi kebocoran!** Segera jalankan `sudo tor-proxy -x` lalu periksa konfigurasi.

### Memantau Log Real-time

```bash
tail -f /var/log/tor-proxy.log
```

### Cek Status Tor

```bash
systemctl status tor
```

---

## Penanganan Error & Failsafe

### Lock File

Saat proxy aktif, file kunci dibuat di `/var/run/tor-proxy/proxy.lock`. Jika skrip sebelumnya crash, jalankan:

```bash
sudo tor-proxy --cleanup
```

### Rollback Otomatis

Jika terjadi **error kritis** saat memulai proxy atau pengguna menekan `Ctrl+C`, sistem akan secara otomatis:
1. Menghapus aturan firewall Nftables/Iptables
2. Memulihkan `/etc/resolv.conf` ke pengaturan semula
3. Menghapus lock file

### Backup Firewall (Mode Iptables)

Sebelum menerapkan aturan, iptables-save dijalankan dan hasilnya disimpan beserta checksum SHA-256 di:
- `/var/run/tor-proxy/iptables_v4.bak`
- `/var/run/tor-proxy/iptables_v6.bak`
- `/var/run/tor-proxy/backup_metadata.json`

---

## Catatan Keamanan

> **PERINGATAN PENTING — Baca Sebelum Menggunakan**

1. **Bukan Tor Browser.** Tor-Proxy adalah *transparent proxy* tingkat OS. Ia mengamankan seluruh koneksi jaringan, namun **tidak** memberikan isolasi browser (fingerprinting, JavaScript, dll). Untuk anonimitas tertinggi di web, tetap gunakan **Tor Browser**.

2. **Tor bukan VPN.** Tor menyembunyikan IP Anda dari tujuan akhir, namun *exit node* Tor dapat melihat lalu lintas yang tidak terenkripsi. Selalu gunakan HTTPS.

3. **DNS Leak.** Fitur `--no-dns-redirect` **tidak disarankan** karena berisiko kebocoran DNS ke ISP Anda. Biarkan opsi DNS redirect aktif (default).

4. **UFW / Docker.** Jika UFW atau Docker terdeteksi aktif, akan muncul peringatan. UFW dapat menimpa aturan iptables. Pastikan tidak ada konflik aturan.

5. **Akses Root.** Skrip ini memerlukan `sudo` karena memodifikasi konfigurasi kernel-level (firewall dan DNS sistem). Jangan jalankan kode yang tidak Anda percaya sebagai root.

6. **Exit Node.** Pemilihan exit node dilakukan otomatis oleh Tor. Anda tidak dapat menjamin bahwa exit node bersifat jujur atau tidak memonitor lalu lintas.

---

## Pertanyaan Umum (FAQ)

**Q: Apakah ini berpengaruh pada koneksi LAN / printer / NAS saya?**  
A: Tidak. Seluruh subnet LAN (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`) dikecualikan secara eksplisit dari tunneling.

**Q: Bagaimana cara bypass SSH agar tidak ikut masuk ke Tor?**  
A: Gunakan `--exclude-ports 22` saat menjalankan `-s`. Contoh: `sudo tor-proxy -s --exclude-ports 22`.

**Q: Tor diblokir oleh ISP saya. Apa solusinya?**  
A: Gunakan opsi `--use-bridges`. Setelah itu, tambahkan daftar bridge ke `/etc/tor/torrc` di bagian yang sudah ditandai. Dapatkan bridge di [bridges.torproject.org](https://bridges.torproject.org).

**Q: Apakah DNS saya aman?**  
A: Ya, selama `--no-dns-redirect` tidak digunakan. DNS diarahkan ke `DNSPort 5353` milik Tor, bukan ke server ISP Anda. Verifikasi dengan `sudo tor-proxy -t`.

**Q: Apa yang terjadi jika komputer mati mendadak saat proxy aktif?**  
A: Aturan nftables akan hilang sendiri setelah reboot (tidak persisten). DNS akan kembali normal setelah reboot karena systemd-resolved akan mengambil alih. Tidak perlu tindakan tambahan.

**Q: Bagaimana cara mendapatkan IP baru lebih cepat?**  
A: Jalankan `sudo tor-proxy -n`. IP baru akan ditampilkan segera setelah sirkuit baru dibangun.

---

## Lisensi

Proyek ini didistribusikan untuk keperluan edukasi dan penggunaan pribadi yang sah. Pengguna bertanggung jawab penuh atas segala konsekuensi hukum dari penggunaan tools ini di wilayah masing-masing.

---

<div align="center">
  <sub>Tor-Proxy Enterprise v4.2.0 · Built for Ubuntu/Debian · Nftables Native Architecture</sub>
</div>