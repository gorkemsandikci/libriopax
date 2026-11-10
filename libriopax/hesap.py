"""Kullanıcılar: kayıt defteri (veri/kullanicilar.json) ve kullanıcı başına veri klasörü.

    veri/kullanicilar.json                  {"kullanicilar": {e-posta: {...}}}
    veri/kullanicilar/<kid>/kitaplar/       kitap modu çıktıları (donustur --veri <kök>)
    veri/kullanicilar/<kid>/aof/            AÖF sekmesi (aof --veri <kök>)
    veri/kullanicilar/<kid>/yuklenen/       sunucudan yüklenen ham dosyalar

Kimlik e-postadır (Tailscale-User-Login; dışarıya açılınca Cloudflare Access). Sahip (`veri/sunucu.json` "kullanici")
yöneticidir, işleri onaysız sıraya girer. Yeni e-posta "bekliyor" olarak kaydolur; yönetici onaylayana kadar hiçbir
şey göremez ve yükleyemez. Herkes sadece kendi klasörünü görür.
"""
import hashlib
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

MOTORLAR = {"piper": "Piper (yerel, ücretsiz)", "chatterbox": "Chatterbox (GPU)", "gemini-tts": "Gemini TTS"}
HAZIR_MOTORLAR = ("piper",)                   # şu an çalışan; diğerleri izin verilse de "yakında"
VARSAYILAN_GEMINI_GUNLUK = 3                  # paylaşılan anahtarla günde en fazla AÖF ünitesi
_EPOSTA = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
_kilit = threading.RLock()


class HesapHatasi(Exception):
    pass


def kid(eposta: str) -> str:
    return hashlib.sha256(eposta.strip().lower().encode()).hexdigest()[:12]


def kok(veri: Path, eposta: str) -> Path:
    return Path(veri) / "kullanicilar" / kid(eposta)


def _yol(veri: Path) -> Path:
    return Path(veri) / "kullanicilar.json"


def oku(veri: Path) -> dict:
    try:
        return json.loads(_yol(veri).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"kullanicilar": {}}


def _yaz(veri: Path, d: dict) -> None:
    yol = _yol(veri)
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_name(yol.name + ".tmp")
    gecici.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(gecici, yol)


def _simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sahip(veri: Path) -> str:
    try:
        ayar = json.loads((Path(veri) / "sunucu.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ayar = {}
    return (ayar.get("kullanici") or "").strip().lower()


def hazirla(veri: Path) -> None:
    """İlk açılış: sahibi yönetici olarak kaydeder ve eski tek kullanıcılı veriyi (veri/kitaplar, veri/aof/dersler)
    sahibin klasörüne taşır (aynı disk: anında). Sahip tanımlı değilse yerel kullanıcı "yerel@libriopax" olur."""
    with _kilit:
        d = oku(veri)
        e = sahip(veri) or "yerel@libriopax"
        if e not in d["kullanicilar"]:
            d["kullanicilar"][e] = {"durum": "onayli", "yonetici": True, "otomatik_onay": True,
                                    "motorlar": list(MOTORLAR), "gemini_gunluk": None, "ad": "",
                                    "olusturma": _simdi()}
            d["sahip"] = e
            _yaz(veri, d)
        hedef = kok(veri, e)
        for eski, yeni in ((Path(veri) / "kitaplar", hedef / "kitaplar"),
                           (Path(veri) / "aof" / "dersler", hedef / "aof" / "dersler")):
            if eski.is_dir() and not yeni.exists():
                yeni.parent.mkdir(parents=True, exist_ok=True)
                os.replace(eski, yeni)


def bul(veri: Path, eposta: str):
    if not eposta:
        return None
    return oku(veri)["kullanicilar"].get(eposta.strip().lower())


def yerel_kullanici(veri: Path) -> str:
    """Başlıksız (doğrudan 127.0.0.1) istek: bilgisayardaki sahip."""
    return oku(veri).get("sahip") or sahip(veri) or "yerel@libriopax"


def basvur(veri: Path, eposta: str, ad: str = "") -> dict:
    """Bilinmeyen e-posta: "bekliyor" kaydı açar (bir kez). Kayıt döner."""
    e = eposta.strip().lower()
    if not _EPOSTA.match(e):
        raise HesapHatasi("Geçersiz e-posta.")
    with _kilit:
        d = oku(veri)
        if e not in d["kullanicilar"]:
            d["kullanicilar"][e] = {"durum": "bekliyor", "yonetici": False, "otomatik_onay": False,
                                    "motorlar": ["piper"], "gemini_gunluk": VARSAYILAN_GEMINI_GUNLUK,
                                    "ad": ad.strip()[:60], "olusturma": _simdi()}
            _yaz(veri, d)
        return d["kullanicilar"][e]


def guncelle(veri: Path, eposta: str, **alanlar) -> dict:
    """Yönetici ayarı: durum (onayli/reddedildi/bekliyor), motorlar, gemini_gunluk, otomatik_onay, ad."""
    e = eposta.strip().lower()
    with _kilit:
        d = oku(veri)
        k = d["kullanicilar"].get(e)
        if k is None:
            raise HesapHatasi("Kullanıcı yok.")
        if "durum" in alanlar:
            if alanlar["durum"] not in ("onayli", "reddedildi", "bekliyor"):
                raise HesapHatasi("Geçersiz durum.")
            if k.get("yonetici") and alanlar["durum"] != "onayli":
                raise HesapHatasi("Yönetici kapatılamaz.")
            k["durum"] = alanlar["durum"]
            k["karar"] = _simdi()
        if "motorlar" in alanlar:
            motorlar = [m for m in alanlar["motorlar"] if m in MOTORLAR]
            k["motorlar"] = motorlar or ["piper"]
        if "gemini_gunluk" in alanlar:
            g = alanlar["gemini_gunluk"]
            k["gemini_gunluk"] = None if g in (None, "") else max(0, min(int(g), 50))
        if "otomatik_onay" in alanlar:
            k["otomatik_onay"] = bool(alanlar["otomatik_onay"])
        if "ad" in alanlar:
            k["ad"] = str(alanlar["ad"]).strip()[:60]
        _yaz(veri, d)
        return k


def onayli_mi(k) -> bool:
    return bool(k) and k.get("durum") == "onayli"
