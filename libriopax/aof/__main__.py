"""AÖF ünitelerini anlatıma çevirir: veri/aof/gelen/*.pdf → veri/aof/dersler/<DERS>/<NN>/.

    python -m libriopax.aof                 # gelen kutusu + bekleyen bütün üniteler (kota dolarsa kalanı sonraki koşuya)
    python -m libriopax.aof --gemini-yok    # sadece ayrıştırma ve ses (Gemini isteği atmaz)
    python -m libriopax.aof --json          # son satırda JSON özet (otomasyon için)

Gemini anahtarı GEMINI_API_KEY ortam değişkeninden okunur.
"""
import argparse
import json
import sys
from pathlib import Path

from . import anlat
from .gemini import Istemci

KOK = Path(__file__).resolve().parent.parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m libriopax.aof", description="AÖF ünite PDF'lerini anlatıma çevirir.")
    ap.add_argument("--veri", type=Path, default=KOK / "veri")
    ap.add_argument("--ses", default="fahrettin", help="Piper sesi: fahrettin, fettah, dfki")
    ap.add_argument("--hiz", type=float, default=0.8)
    ap.add_argument("--motor", default="piper", choices=["piper", "sahte"])
    ap.add_argument("--gemini-yok", action="store_true", help="Gemini adımlarını atla")
    ap.add_argument("--kota", type=Path, help="kota durum dosyası (varsayılan <veri>/aof/kota.json; anahtar başına ayrı)")
    ap.add_argument("--json", action="store_true", help="son satırda JSON özet")
    a = ap.parse_args(argv)
    for akim in (sys.stdout, sys.stderr):
        if hasattr(akim, "reconfigure"):
            akim.reconfigure(encoding="utf-8", errors="replace")

    def motor_yap():
        if a.motor == "sahte":
            from ..ses.motor import SahteMotor
            return SahteMotor()
        from ..ses.motor import PiperMotor
        return PiperMotor(a.ses, a.hiz)

    aof = a.veri / "aof"
    (aof / "gelen").mkdir(parents=True, exist_ok=True)
    ozet = anlat.calistir(aof, Istemci(a.kota or aof / "kota.json"), motor_yap, gemini_acik=not a.gemini_yok)
    for d in ozet["yeni"]:
        print(f"+ yeni ünite: {d}")
    for r in ozet["red"]:
        print(f"✗ {r['dosya']}: {r['hata']}")
    for d in ozet["hazir"]:
        print(f"✓ anlatım hazır: {d}")
    for h in ozet["hatalar"]:
        print(f"! {h['unite']}: {h['hata']}")
    if ozet.get("kota_bekle"):
        print(f"⏸ Gemini kotası doldu; {ozet['kota_bekle']} (UTC) sonrası sürer.")
    print(f"Bekleyen: {len(ozet['bekleyen'])} · Gemini isteği: {ozet['gemini_istek']}")
    if a.json:
        print(json.dumps(ozet, ensure_ascii=False))
    return 1 if ozet["hatalar"] or ozet["red"] else 0


if __name__ == "__main__":
    sys.exit(main())
