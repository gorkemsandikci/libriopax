"""Yönetim komutları (G-Maestro'nun Telegram düğmeleri ve sahibin terminali için).

    python -m libriopax.yonetim durum --json                 # onay bekleyen işler/kullanıcılar + son işler
    python -m libriopax.yonetim is-onayla <id>
    python -m libriopax.yonetim is-reddet <id> [neden]
    python -m libriopax.yonetim kullanici-onayla <e-posta>
    python -m libriopax.yonetim kullanici-reddet <e-posta>
    python -m libriopax.yonetim gemini-anahtar                # paylaşılan anahtar; stdin'den (ekrana yazılmaz)
    python -m libriopax.yonetim gemini-anahtar --env C:\\yol\\.env   # .env'deki GEMINI_API_KEY'i okur, yazdırmaz

Çıktılar hiçbir zaman anahtar içermez.
"""
import argparse
import getpass
import json
import sys
from pathlib import Path

from . import gizli, hesap, isler

KOK = Path(__file__).resolve().parent.parent


def durum(veri: Path, son: int = 30) -> dict:
    tum = isler.listele(veri)
    alanlar = ("id", "eposta", "tur", "dosya_adi", "durum", "olusturma", "guncelleme", "hata", "sonuc", "secenek")
    try:
        genel = json.loads((Path(veri) / "sunucu.json").read_text(encoding="utf-8")).get("genel_adres") or ""
    except (OSError, ValueError):
        genel = ""
    kayit = hesap.oku(veri)
    return {
        "sahip": kayit.get("sahip"), "genel_adres": genel,
        "isler": [{k: x.get(k) for k in alanlar} for x in tum[:son]],
        "kullanicilar": [{"eposta": e, "kid": hesap.kid(e), "durum": k["durum"], "ad": k.get("ad", ""),
                          "olusturma": k.get("olusturma")} for e, k in kayit["kullanicilar"].items()],
    }


def _env_oku(yol: Path, ad: str) -> str:
    for satir in yol.read_text(encoding="utf-8").splitlines():
        k, _, v = satir.strip().partition("=")
        if k == ad:
            return v.strip().strip('"')
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m libriopax.yonetim")
    ap.add_argument("--veri", type=Path, default=KOK / "veri")
    alt = ap.add_subparsers(dest="komut", required=True)
    d = alt.add_parser("durum")
    d.add_argument("--json", action="store_true")
    for ad in ("is-onayla", "is-reddet"):
        p = alt.add_parser(ad)
        p.add_argument("id")
        if ad == "is-reddet":
            p.add_argument("neden", nargs="?", default="")
    for ad in ("kullanici-onayla", "kullanici-reddet"):
        alt.add_parser(ad).add_argument("eposta")
    g = alt.add_parser("gemini-anahtar")
    g.add_argument("--kullanici", help="kendi anahtarı (e-posta); verilmezse paylaşılan anahtar")
    g.add_argument("--env", type=Path, help=".env dosyasından GEMINI_API_KEY oku")
    g.add_argument("--sil", action="store_true")
    a = ap.parse_args(argv)
    for akim in (sys.stdout, sys.stderr):
        if hasattr(akim, "reconfigure"):
            akim.reconfigure(encoding="utf-8", errors="replace")
    hesap.hazirla(a.veri)
    try:
        if a.komut == "durum":
            sonuc = durum(a.veri)
            if a.json:
                print(json.dumps(sonuc, ensure_ascii=False))
            else:
                for x in sonuc["isler"]:
                    print(f"{x['id']}  {x['durum']:9}  {x['tur']:5}  {x['eposta']}  {x['dosya_adi']}")
            return 0
        if a.komut in ("is-onayla", "is-reddet"):
            is_ = isler.karar(a.veri, a.id, a.komut == "is-onayla", getattr(a, "neden", ""))
            print(json.dumps({"id": is_["id"], "durum": is_["durum"], "dosya_adi": is_["dosya_adi"],
                              "eposta": is_["eposta"]}, ensure_ascii=False))
            return 0
        if a.komut in ("kullanici-onayla", "kullanici-reddet"):
            k = hesap.guncelle(a.veri, a.eposta, durum="onayli" if a.komut == "kullanici-onayla" else "reddedildi")
            print(json.dumps({"eposta": a.eposta.lower(), "durum": k["durum"]}, ensure_ascii=False))
            return 0
        if a.komut == "gemini-anahtar":
            kapsam = hesap.kid(a.kullanici) if a.kullanici else "ortak"
            if a.sil:
                gizli.anahtar_sil(a.veri, kapsam)
                print("Anahtar silindi.")
                return 0
            if a.env:
                deger = _env_oku(a.env, "GEMINI_API_KEY")
            elif sys.stdin.isatty():
                deger = getpass.getpass("Gemini anahtarı (görünmez): ")
            else:
                deger = sys.stdin.readline()
            gizli.anahtar_yaz(a.veri, kapsam, deger)
            print(f"Anahtar kaydedildi ({'paylaşılan' if kapsam == 'ortak' else a.kullanici}).")
            return 0
    except (isler.IsHatasi, hesap.HesapHatasi, gizli.GizliHatasi, OSError) as hata:
        print(f"❌ {hata}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
