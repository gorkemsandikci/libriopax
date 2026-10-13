# Libriopax sunucusu (Windows): oturum açılışında başlayan görev + (varsa) sadece Tailscale ağına HTTPS yolu.
#   powershell -NoProfile -ExecutionPolicy Bypass -File kurulum\sunucu_kur.ps1
# Geri almak:  Unregister-ScheduledTask Libriopax-Sunucu -Confirm:$false ; tailscale serve --set-path /libriopax off
# Yönetici gerekmez; internete port açılmaz (sunucu 127.0.0.1'de, dışarıya tek yol tailnet).

$ErrorActionPreference = "Stop"
$Kok = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $Kok ".venv\Scripts\pythonw.exe"
$Port = 8790
$Yol = "/libriopax"
if (-not (Test-Path $Pythonw)) { throw "Önce sanal ortam: py -3.12 -m venv .venv ve pip install -r requirements.txt" }

# 1) Zamanlanmış görev (kullanıcı oturumu, gizli pencere, çökerse yeniden başlat)
$Eylem = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m libriopax.sunucu" -WorkingDirectory $Kok
$Tetik = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Ayar = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Libriopax-Sunucu" -Action $Eylem -Trigger $Tetik -Settings $Ayar `
    -Description "Libriopax sesli kitap sunucusu (127.0.0.1:$Port)" -Force | Out-Null
Start-ScheduledTask -TaskName "Libriopax-Sunucu"

# 2) Tailscale varsa: https://<makine>.<tailnet>.ts.net/libriopax -> 127.0.0.1:8790 (diğer serve yollarına dokunmaz)
$Veri = Join-Path $Kok "veri"
New-Item -ItemType Directory -Force $Veri | Out-Null
$Adres = $null
if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    tailscale serve --bg --set-path $Yol "http://127.0.0.1:$Port" | Out-Null
    # veri\sunucu.json: genel adres + kitaplığın sahibi (başka tailnet kullanıcısı 403 alır)
    $Durum = tailscale status --json | ConvertFrom-Json
    $Dns = $Durum.Self.DNSName.TrimEnd(".")
    $Giris = $Durum.User.($Durum.Self.UserID.ToString()).LoginName
    $Adres = "https://$Dns$Yol/"
    $Ayarlar = @{ genel_adres = $Adres; kullanici = $Giris } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $Veri "sunucu.json"), $Ayarlar, (New-Object Text.UTF8Encoding $false))
} else {
    Write-Output "Tailscale bulunamadı: sunucu sadece bu bilgisayarda açık (http://127.0.0.1:$Port/)."
    Write-Output "Telefondan erişim için Tailscale kurun (önerilen) ya da README'deki 'Ev ağı' bölümüne bakın."
}

# 3) Doğrulama
Start-Sleep -Seconds 2
try { $Cevap = Invoke-WebRequest "http://127.0.0.1:$Port/saglik" -UseBasicParsing -TimeoutSec 5 } catch { $Cevap = $null }
if ($Cevap -and $Cevap.Content -eq "ok") { Write-Output "Sunucu çalışıyor: http://127.0.0.1:$Port/" } else { Write-Output "UYARI: sunucu cevap vermedi (veri\sunucu.log)." }
if ($Adres) { Write-Output "Telefondan (Tailscale açık): $Adres" }
