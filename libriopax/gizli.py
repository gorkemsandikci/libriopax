"""Gemini anahtarlarının saklanması: Windows DPAPI (CryptProtectData) ile şifreli dosya, sadece bu Windows hesabı çözer.

    veri/gizli/ortak.dpapi      paylaşılan anahtar (sahibin; kullanıcı başına günlük sınırla)
    veri/gizli/<kid>.dpapi      kullanıcının kendi anahtarı (sınırsız; kendi kotası)

Anahtar hiçbir sayfaya, loga ya da iş kaydına yazılmaz; sadece işçinin alt sürecinin ortamına verilir. Sayfalar
yalnızca "kayıtlı / değil" bilgisini ve son 4 karakteri değil, hiçbir parçasını göstermez.
"""
import ctypes
import os
import sys
from pathlib import Path


class GizliHatasi(Exception):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(veri: bytes) -> _Blob:
    tampon = ctypes.create_string_buffer(veri, len(veri))
    return _Blob(len(veri), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char)))


def _cagir(islev, veri: bytes) -> bytes:
    if sys.platform != "win32":
        raise GizliHatasi("Anahtar saklama şimdilik sadece Windows'ta (DPAPI).")
    giren, cikan = _blob(veri), _Blob()
    if not islev(ctypes.byref(giren), None, None, None, None, 0x1, ctypes.byref(cikan)):   # 0x1: arayüzsüz
        raise GizliHatasi("DPAPI işlemi başarısız.")
    try:
        return ctypes.string_at(cikan.pbData, cikan.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(cikan.pbData)


def koru(veri: bytes) -> bytes:
    return _cagir(ctypes.windll.crypt32.CryptProtectData, veri) if sys.platform == "win32" else _cagir(None, veri)


def coz(veri: bytes) -> bytes:
    return _cagir(ctypes.windll.crypt32.CryptUnprotectData, veri) if sys.platform == "win32" else _cagir(None, veri)


def _dosya(veri: Path, kapsam: str) -> Path:
    if not (kapsam == "ortak" or (len(kapsam) == 12 and all(c in "0123456789abcdef" for c in kapsam))):
        raise GizliHatasi("Geçersiz kapsam.")
    return Path(veri) / "gizli" / f"{kapsam}.dpapi"


def anahtar_yaz(veri: Path, kapsam: str, deger: str) -> None:
    deger = (deger or "").strip()
    if not (20 <= len(deger) <= 200) or any(c.isspace() for c in deger):
        raise GizliHatasi("Anahtar biçimi geçersiz.")
    yol = _dosya(veri, kapsam)
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_name(yol.name + ".tmp")
    gecici.write_bytes(koru(deger.encode("utf-8")))
    os.replace(gecici, yol)


def anahtar_oku(veri: Path, kapsam: str) -> str:
    yol = _dosya(veri, kapsam)
    if not yol.is_file():
        return ""
    return coz(yol.read_bytes()).decode("utf-8")


def anahtar_var(veri: Path, kapsam: str) -> bool:
    return _dosya(veri, kapsam).is_file()


def anahtar_sil(veri: Path, kapsam: str) -> None:
    _dosya(veri, kapsam).unlink(missing_ok=True)
