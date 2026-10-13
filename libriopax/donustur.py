"""Kitabı sayfa sayfa sese çevirir (komut satırı). Yarıda kesilirse tekrar çalıştırınca kaldığı yerden devam eder.

    python -m libriopax.donustur kitap.epub                    # tüm kitap, Piper dfki sesi
    python -m libriopax.donustur kitap.pdf --sayfalar 1-10 --ses fettah
    python -m libriopax.donustur kitap.pdf --sadece-metin       # ses üretmeden sayfalara bölünmüş metni hazırla
    python -m libriopax.donustur kitap.epub --bolum-mp3        # bitince bölüm başına tek MP3 + kitap.m3u

Çıktı: veri/kitaplar/<kimlik>/kitap.json (sayfalar, cümleler) ve ses/<motor>-<ses>/0001.mp3 + 0001.json (süre, cümle
zamanları). --json ile son satırda makinece okunabilir özet (otomasyon için).
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from .metin import bol
from .metin.model import KitapHatasi, Sayfa
from .ses import uretici

SURUM = 3                       # kitap.json biçimi / ayrıştırma sürümü; değişirse metin yeniden çıkarılır
KOK = Path(__file__).resolve().parent.parent


def _kimlik(yol: Path) -> str:
    h = hashlib.sha1()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1 << 20), b""):
            h.update(parca)
    return h.hexdigest()[:12]


def ayristir(yol: Path):
    uzanti = yol.suffix.lower()
    if uzanti == ".epub":
        from .metin import epub
        return epub.oku(yol)
    if uzanti == ".pdf":
        from .metin import pdf
        return pdf.oku(yol)
    raise KitapHatasi("Sadece EPUB ve PDF dosyaları okunabilir.")


def kitap_hazirla(yol: Path, veri: Path) -> tuple:
    """(dizin, kitap_json) — metin bir kez çıkarılır, sonra kitap.json'dan okunur."""
    dizin = veri / "kitaplar" / _kimlik(yol)
    kayit = dizin / "kitap.json"
    if kayit.exists():
        mevcut = json.loads(kayit.read_text(encoding="utf-8"))
        if mevcut.get("surum") == SURUM:
            return dizin, mevcut
        for eski in ("ses", "bolumler"):         # sayfalama değişmiş olabilir: eski sesler yeni sayfalara uymaz
            shutil.rmtree(dizin / eski, ignore_errors=True)
    kitap = ayristir(yol)
    sayfalar = bol.sayfala(kitap)
    if not sayfalar:
        raise KitapHatasi("Kitapta okunacak metin bulunamadı.")
    dizin.mkdir(parents=True, exist_ok=True)
    kayit_veri = {"surum": SURUM, "kimlik": dizin.name, "kaynak": yol.name, "baslik": kitap.baslik or yol.stem,
                  "yazar": kitap.yazar, "dil": kitap.dil, "tur": kitap.tur, "bolumler": kitap.bolumler,
                  "kaynak_sayfa_sayisi": kitap.kaynak_sayfa_sayisi, "karakter": sum(len(s.metin) for s in sayfalar),
                  "sayfalar": [asdict(s) for s in sayfalar]}
    uretici.json_yaz(kayit_veri, kayit)
    return dizin, kayit_veri


def _secim(ifade: str, son: int) -> list:
    if not ifade:
        return list(range(1, son + 1))
    secilen = set()
    for parca in ifade.split(","):
        a, _, b = parca.partition("-")
        secilen.update(range(int(a), (int(b) if b else int(a)) + 1))
    return sorted(n for n in secilen if 1 <= n <= son)


def ses_dizini(dizin: Path, motor) -> Path:
    return dizin / "ses" / f"{motor.ad}-{motor.ses}"


def donustur(dizin: Path, kitap: dict, motor, secim: list, ilerleme=None) -> dict:
    hedef = ses_dizini(dizin, motor)
    hedef.mkdir(parents=True, exist_ok=True)
    sayfalar = {s["sira"]: Sayfa(**s) for s in kitap["sayfalar"]}
    yapilacak = [n for n in secim if not (hedef / f"{n:04}.json").exists()]
    ozet = {"kitap": kitap["baslik"], "kimlik": kitap["kimlik"], "motor": f"{motor.ad}-{motor.ses}",
            "sayfa": len(sayfalar), "secilen": len(secim), "atlanan": len(secim) - len(yapilacak),
            "uretilen": 0, "basarisiz": [], "ses_sn": 0.0, "sure_sn": 0.0, "durduruldu": False}
    baslangic = time.time()

    def bitir(n, pcm, zamanlar, sure):
        dosya = uretici.yaz(pcm, motor.ornekleme, hedef / f"{n:04}.mp3")
        sure_ms = round(len(pcm) / 2 * 1000 / motor.ornekleme)
        uretici.json_yaz({"sayfa": n, "dosya": dosya.name, "sure_ms": sure_ms, "zamanlar": zamanlar,
                          "uretim_sn": round(sure, 2)}, hedef / f"{n:04}.json")
        return sure_ms

    havuz = ThreadPoolExecutor(max_workers=2)      # kodlama (ffmpeg) sentezle örtüşsün
    bekleyen = []
    try:
        for i, n in enumerate(yapilacak, 1):
            t0 = time.time()
            try:
                pcm, zamanlar = uretici.sayfa_sesi(motor, sayfalar[n])
            except Exception as hata:  # tek sayfa kitabı durdurmasın
                ozet["basarisiz"].append({"sayfa": n, "hata": str(hata)[:200]})
                continue
            bekleyen.append((n, havuz.submit(bitir, n, pcm, zamanlar, time.time() - t0)))
            if ilerleme:
                gecen = time.time() - baslangic
                ilerleme(i, len(yapilacak), n, gecen / i * (len(yapilacak) - i))
    except KeyboardInterrupt:
        ozet["durduruldu"] = True
    finally:
        havuz.shutdown(wait=True)
    for n, f in bekleyen:
        try:
            ozet["ses_sn"] += f.result() / 1000
            ozet["uretilen"] += 1
        except Exception as hata:
            ozet["basarisiz"].append({"sayfa": n, "hata": str(hata)[:200]})
    ozet["ses_sn"] = round(ozet["ses_sn"], 1)
    ozet["sure_sn"] = round(time.time() - baslangic, 1)
    ozet["tamamlanan"] = sum(1 for n in sayfalar if (hedef / f"{n:04}.json").exists())
    return ozet


def bolum_dosyalari(dizin: Path, kitap: dict, motor) -> list:
    """Tüm sayfaları biten bölümleri tek MP3'te birleştirir (yeniden kodlamadan) + kitap.m3u. Telefondaki herhangi
    bir oynatıcıyla dinlemek için (web arayüzü S1'de)."""
    ffmpeg = uretici.ffmpeg_yolu()
    hedef = ses_dizini(dizin, motor)
    cikti = dizin / "bolumler" / f"{motor.ad}-{motor.ses}"
    cikti.mkdir(parents=True, exist_ok=True)
    yapilan = []
    for b, ad in enumerate(kitap["bolumler"]):
        sayfalar = [s["sira"] for s in kitap["sayfalar"] if s["bolum"] == b]
        dosyalar = [hedef / f"{n:04}.mp3" for n in sayfalar]
        if not ffmpeg or not dosyalar or not all(d.exists() for d in dosyalar):
            continue
        guvenli = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", ad)[:60].strip() or "Bölüm"
        yol = cikti / f"{b + 1:03} - {guvenli}.mp3"
        liste = cikti / "liste.txt"
        liste.write_text("".join(f"file '{d.as_posix()}'\n" for d in dosyalar), encoding="utf-8")
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i",
                        str(liste), "-c", "copy", "-metadata", f"title={ad}", "-metadata",
                        f"album={kitap['baslik']}", "-metadata", f"artist={kitap['yazar']}", "-metadata",
                        f"track={b + 1}", str(yol)], check=True, capture_output=True)
        liste.unlink()
        yapilan.append(yol)
    (cikti / "kitap.m3u").write_text("#EXTM3U\n" + "".join(f"{y.name}\n" for y in yapilan), encoding="utf-8")
    return yapilan


def indirme_linki(ozet: dict, veri: Path) -> None:
    """Sunucu kuruluysa (kurulum/sunucu_kur.ps1) telefondan indirme linki + terminalde QR kod."""
    from . import sunucu
    link = sunucu.kitap_linki(ozet["kimlik"], veri)
    if not link:
        print("📱 Telefondan indirme linki için bir kez: kurulum/sunucu_kur.ps1", file=sys.stderr)
        return
    ozet["link"] = link
    print(f"📱 Telefondan dinle / indir: {link}", file=sys.stderr)
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(link)
        qr.print_ascii(out=sys.stderr, invert=True)
    except (ImportError, UnicodeEncodeError):
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m libriopax.donustur", description="EPUB/PDF'i yerel sesle sese çevirir.")
    ap.add_argument("kitap", type=Path)
    ap.add_argument("--ses", default="dfki", help="Piper sesi: dfki, fahrettin, fettah")
    ap.add_argument("--hiz", type=float, default=1.0, help="konuşma hızı (sentezde; oynatıcıda ayrıca değişir)")
    ap.add_argument("--motor", default="piper", choices=["piper", "sahte"])
    ap.add_argument("--veri", type=Path, default=KOK / "veri")
    ap.add_argument("--sayfalar", default="", help="ör. 1-20,35")
    ap.add_argument("--sadece-metin", action="store_true")
    ap.add_argument("--bolum-mp3", action=argparse.BooleanOptionalAction, default=True,
                    help="bölüm başına MP3 + telefondan indirme linki (kapatmak: --no-bolum-mp3)")
    ap.add_argument("--json", action="store_true", help="son satırda JSON özet")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    try:
        t0 = time.time()
        dizin, kitap = kitap_hazirla(a.kitap, a.veri)
        print(f"📖 {kitap['baslik']} — {kitap['yazar'] or '?'} · {len(kitap['sayfalar'])} sayfa, "
              f"{len(kitap['bolumler'])} bölüm, {kitap['karakter']:,} karakter ({time.time() - t0:.1f} sn)",
              file=sys.stderr)
        print(f"   {dizin}", file=sys.stderr)
        if a.sadece_metin:
            if a.json:
                print(json.dumps({"kimlik": kitap["kimlik"], "sayfa": len(kitap["sayfalar"])}, ensure_ascii=False))
            return 0
        if a.motor == "sahte":
            from .ses.motor import SahteMotor
            motor = SahteMotor()
        else:
            from .ses.motor import PiperMotor
            motor = PiperMotor(a.ses, a.hiz)
    except (KitapHatasi, FileNotFoundError) as hata:
        print(f"❌ {hata}", file=sys.stderr)
        if a.json:
            print(json.dumps({"hata": str(hata)}, ensure_ascii=False))
        return 1

    def ilerleme(i, toplam, n, kalan):
        print(f"\r🔊 {i}/{toplam} · sayfa {n} · kalan ~{kalan / 60:.0f} dk   ", end="", file=sys.stderr, flush=True)

    ozet = donustur(dizin, kitap, motor, _secim(a.sayfalar, len(kitap["sayfalar"])), ilerleme)
    print(file=sys.stderr)
    if a.bolum_mp3 and not ozet["durduruldu"]:
        ozet["bolum_dosyalari"] = len(bolum_dosyalari(dizin, kitap, motor))
    sa = ozet["ses_sn"] / 3600
    print(f"✅ {ozet['uretilen']} sayfa üretildi ({sa:.1f} sa ses, {ozet['sure_sn'] / 60:.1f} dk), "
          f"{ozet['atlanan']} zaten vardı, {len(ozet['basarisiz'])} başarısız · "
          f"tamamlanan {ozet['tamamlanan']}/{ozet['sayfa']}" + (" · ⏸ durduruldu" if ozet["durduruldu"] else ""),
          file=sys.stderr)
    for b in ozet["basarisiz"][:5]:
        print(f"   ❌ sayfa {b['sayfa']}: {b['hata']}", file=sys.stderr)
    if ozet.get("bolum_dosyalari"):
        indirme_linki(ozet, a.veri)
    if a.json:
        print(json.dumps(ozet, ensure_ascii=False))
    return 1 if ozet["basarisiz"] else 0


if __name__ == "__main__":
    sys.exit(main())
