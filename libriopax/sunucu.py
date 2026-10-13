"""İndirme sunucusu: üretilen bölüm MP3'lerini telefondan dinlemek/indirmek için (S1 web oynatıcısından önceki ara adım).

    python -m libriopax.sunucu            # 127.0.0.1:8790; telefona `tailscale serve` ile açılır (kurulum/sunucu_kur.ps1)

Sadece 127.0.0.1'e bağlanır: dışarıdan tek yol Tailscale (sadece tailnet, HTTPS). veri/sunucu.json'da "kullanici"
varsa Tailscale-User-Login başlığı ona eşit olmayan istek 403 alır. tailscale serve "/libriopax" önekini sildiği için
sayfalardaki bütün bağlantılar görelidir.
"""
import html
import json
import logging
import os
import re
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit, parse_qs

KOK = Path(__file__).resolve().parent.parent
VERI = KOK / "veri"
ADRES, PORT = "127.0.0.1", 8790
_KITAP = re.compile(r"^[0-9a-f]{12}$")
_VARYANT = re.compile(r"^[a-z]+-[a-z0-9]+$")
_zip_kilidi = threading.Lock()
log = logging.getLogger("libriopax.sunucu")


def ayarlar(veri: Path = VERI) -> dict:
    """veri/sunucu.json: {"genel_adres": "https://.../libriopax/", "kullanici": "..."} (kurulum betiği yazar)."""
    try:
        return json.loads((veri / "sunucu.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def kitap_linki(kimlik: str, veri: Path = VERI):
    adres = ayarlar(veri).get("genel_adres")
    return f"{adres.rstrip('/')}/k/{kimlik}/" if adres else None


def _boyut(n: int) -> str:
    return f"{n / 2 ** 20:.0f} MB" if n >= 2 ** 20 else f"{n / 1024:.0f} KB"


def _sure(ms: int) -> str:
    dk = round(ms / 60000)
    return f"{dk // 60} sa {dk % 60} dk" if dk >= 60 else f"{dk} dk"


_onbellek = {}   # dizin -> (imza, kitap) — ses çalarken her aralık isteğinde yüzlerce JSON okunmasın


def _imza(dizin: Path) -> tuple:
    bolumler = dizin / "bolumler"
    alt = tuple((p.name, p.stat().st_mtime_ns) for p in bolumler.glob("*")) if bolumler.is_dir() else ()
    return (dizin / "kitap.json").stat().st_mtime_ns, alt


def kitaplar(veri: Path = VERI) -> list:
    """Bölüm MP3'i olan kitaplar (en yeni önce): [{kimlik, baslik, yazar, varyantlar: {ad: [bolum...]}}]."""
    sonuc = []
    for kayit in sorted((veri / "kitaplar").glob("*/kitap.json"), key=lambda p: -p.stat().st_mtime):
        dizin = kayit.parent
        try:
            imza = _imza(dizin)
        except OSError:
            continue
        if dizin in _onbellek and _onbellek[dizin][0] == imza:
            if _onbellek[dizin][1]:
                sonuc.append(_onbellek[dizin][1])
            continue
        _onbellek[dizin] = (imza, _kitap_oku(dizin))
        if _onbellek[dizin][1]:
            sonuc.append(_onbellek[dizin][1])
    return sonuc


def _kitap_oku(dizin: Path):
    kayit = dizin / "kitap.json"
    try:
        k = json.loads(kayit.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    varyantlar = {}
    for v in sorted(p for p in (dizin / "bolumler").glob("*") if p.is_dir() and _VARYANT.match(p.name)):
        sureler = {}
        for s in k["sayfalar"]:
            bilgi = v.parent.parent / "ses" / v.name / f"{s['sira']:04}.json"
            try:
                sureler[s["bolum"]] = sureler.get(s["bolum"], 0) + json.loads(bilgi.read_text())["sure_ms"]
            except (OSError, ValueError, KeyError):
                pass
        bolumler = []
        for mp3 in sorted(v.glob("*.mp3")):
            no = int(mp3.name[:3])
            bolumler.append({"no": no, "ad": k["bolumler"][no - 1] if no <= len(k["bolumler"]) else mp3.stem,
                             "dosya": mp3, "boyut": mp3.stat().st_size, "sure_ms": sureler.get(no - 1, 0)})
        if bolumler:
            varyantlar[v.name] = bolumler
    if not varyantlar:
        return None
    return {"kimlik": dizin.name, "baslik": k["baslik"], "yazar": k.get("yazar", ""),
            "bolum_sayisi": len(k["bolumler"]), "varyantlar": varyantlar, "dizin": dizin}


def zip_yolu(kitap: dict, varyant: str) -> Path:
    """Bölüm MP3'lerinin ZIP'i (sıkıştırmasız; MP3 zaten sıkışık). Bölümlerden eskiyse yeniden kurulur."""
    bolumler = kitap["varyantlar"][varyant]
    hedef = kitap["dizin"] / "indir" / f"{varyant}.zip"
    with _zip_kilidi:
        en_yeni = max(b["dosya"].stat().st_mtime for b in bolumler)
        if not hedef.exists() or hedef.stat().st_mtime < en_yeni:
            hedef.parent.mkdir(exist_ok=True)
            gecici = hedef.with_name(hedef.name + ".tmp")
            klasor = re.sub(r'[<>:"/\\|?*]', "", kitap["baslik"])[:60] or kitap["kimlik"]
            with zipfile.ZipFile(gecici, "w", zipfile.ZIP_STORED) as z:
                for b in bolumler:
                    z.write(b["dosya"], f"{klasor}/{b['dosya'].name}")
            os.replace(gecici, hedef)
    return hedef


# --- sayfalar -----------------------------------------------------------------------------------------------
STIL = """
:root{--zemin:#FFFFFF;--zemin-sicak:#FDFBF7;--krem:#F8F3EB;--bej:#EFE5D6;--bej-orta:#E2D3BC;--bej-koyu:#CDB596;
--vurgu:#B08A5F;--vurgu-yazi:#7C5B39;--yazi:#2A251F;--yazi-2:#6B6157;--yazi-3:#9A9085;
--cam:rgba(255,255,255,.62);--cam-kenar:rgba(255,255,255,.85);--cam-cizgi:rgba(205,181,150,.28);
--golge:0 8px 32px rgba(122,94,60,.08),0 1px 2px rgba(122,94,60,.06)}
*{box-sizing:border-box}
body{margin:0;font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--yazi);min-height:100vh;
background:radial-gradient(60vw 50vh at 85% -10%,#F6EEE2 0%,transparent 60%),
radial-gradient(50vw 40vh at -10% 90%,#F9F4EC 0%,transparent 60%),var(--zemin)}
.ust{position:sticky;top:0;z-index:2;padding:14px 16px;background:var(--cam);backdrop-filter:blur(20px) saturate(140%);
-webkit-backdrop-filter:blur(20px) saturate(140%);border-bottom:1px solid var(--cam-cizgi);display:flex;align-items:center;gap:10px;
padding-inline:max(16px,calc((100% - 720px) / 2 + 16px))}
.ust a{color:var(--vurgu-yazi);text-decoration:none;font-weight:600}
.ust h1{font-size:18px;margin:0;font-weight:650;letter-spacing:-.01em}
main{max-width:720px;margin:0 auto;padding:16px}
.kart{display:block;background:var(--cam);border:1px solid var(--cam-kenar);border-bottom-color:var(--cam-cizgi);
box-shadow:var(--golge),inset 0 1px 0 rgba(255,255,255,.9);border-radius:18px;padding:16px;margin:0 0 12px;
color:inherit;text-decoration:none;backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
.kitap{display:flex;gap:14px;align-items:center}
.kapak{flex:none;width:56px;height:76px;border-radius:8px;background:linear-gradient(160deg,var(--krem),var(--bej-orta));
display:grid;place-items:center;font:700 20px Georgia,serif;color:var(--vurgu-yazi);box-shadow:var(--golge)}
.baslik{font-weight:650}.ikincil{color:var(--yazi-2);font-size:14px}
.dugme{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;padding:0 20px;border-radius:999px;
background:var(--vurgu);color:#fff;font-weight:600;text-decoration:none;box-shadow:0 6px 18px rgba(176,138,95,.25)}
.bolum{display:flex;align-items:center;gap:10px;padding:10px 0;border-top:1px solid var(--bej)}
.bolum:first-child{border-top:0}
.bolum .ad{flex:1;min-width:0}.bolum .ad div:first-child{overflow-wrap:anywhere}
.yuvarlak{flex:none;width:44px;height:44px;border-radius:50%;border:1px solid var(--bej-orta);background:var(--zemin-sicak);
display:grid;place-items:center;color:var(--vurgu-yazi);text-decoration:none;font-size:18px;cursor:pointer}
audio{width:100%;margin-top:8px}
.qr{display:flex;gap:16px;align-items:center}.qr svg{width:132px;height:132px;flex:none}.qr>div{min-width:0;overflow-wrap:anywhere}
.bos{text-align:center;color:var(--yazi-2);padding:40px 16px}
@media (prefers-reduced-transparency:reduce){.ust,.kart{background:var(--zemin-sicak);backdrop-filter:none}}
"""


def _sayfa(baslik: str, govde: str, geri: str = "") -> bytes:
    geri_html = f'<a href="{geri}" aria-label="Geri">‹ Kitaplar</a>' if geri else ""
    return (f'<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><meta name="theme-color" content="#FFFFFF">'
            f'<title>{html.escape(baslik)} · Libriopax</title><style>{STIL}</style></head><body>'
            f'<div class="ust">{geri_html}<h1>{html.escape(baslik)}</h1></div><main>{govde}</main></body></html>'
            ).encode("utf-8")


def _qr_svg(metin: str) -> str:
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return ""
    img = qrcode.make(metin, image_factory=qrcode.image.svg.SvgPathImage, border=1)
    return img.to_string(encoding="unicode")


def ana_sayfa(liste: list, yerel: bool, ayar: dict) -> bytes:
    parcalar = []
    if yerel and ayar.get("genel_adres"):
        parcalar.append(f'<div class="kart qr">{_qr_svg(ayar["genel_adres"])}<div><div class="baslik">Telefonla tara</div>'
                        f'<div class="ikincil">Tailscale açıkken telefonda açılır:<br>{html.escape(ayar["genel_adres"])}'
                        f'</div></div></div>')
    for k in liste:
        varyant, bolumler = next(iter(k["varyantlar"].items()))
        toplam = sum(b["sure_ms"] for b in bolumler)
        bas = "".join(w[0] for w in k["baslik"].split()[:2]).upper() or "?"
        parcalar.append(f'<a class="kart kitap" href="k/{k["kimlik"]}/"><div class="kapak">{html.escape(bas)}</div><div>'
                        f'<div class="baslik">{html.escape(k["baslik"])}</div><div class="ikincil">'
                        f'{html.escape(k["yazar"] or "")}</div><div class="ikincil">{len(bolumler)} bölüm · '
                        f'{_sure(toplam)}</div></div></a>')
    if not liste:
        parcalar.append('<div class="bos">Henüz hazır kitap yok.<br>Bilgisayarda: <code>python -m libriopax.donustur '
                        'kitap.epub --bolum-mp3</code></div>')
    return _sayfa("Kitaplarım", "".join(parcalar))


def kitap_sayfasi(k: dict) -> bytes:
    varyant, bolumler = next(iter(k["varyantlar"].items()))
    toplam_boyut = sum(b["boyut"] for b in bolumler)
    satirlar = []
    for b in bolumler:
        dosya = f'{varyant}/{b["no"]}.mp3'
        satirlar.append(
            f'<div class="bolum"><div class="ad"><div>{html.escape(b["ad"])}</div><div class="ikincil">'
            f'{_sure(b["sure_ms"])} · {_boyut(b["boyut"])}</div><audio preload="none" controls hidden src="{dosya}"></audio></div>'
            f'<button class="yuvarlak" type="button" aria-label="Dinle" onclick="dinle(this)">▶</button>'
            f'<a class="yuvarlak" href="{dosya}?indir=1" download aria-label="İndir">⬇</a></div>')
    betik = ("<script>function dinle(d){const a=d.parentElement.querySelector('audio');"
             "document.querySelectorAll('audio').forEach(x=>{if(x!==a){x.pause();x.hidden=true}});"
             "a.hidden=false;a.play();}</script>")
    govde = (f'<div class="kart"><div class="baslik">{html.escape(k["baslik"])}</div><div class="ikincil">'
             f'{html.escape(k["yazar"] or "")} · {len(bolumler)} bölüm · {_sure(sum(b["sure_ms"] for b in bolumler))}'
             f'</div><p><a class="dugme" href="{varyant}/kitap.zip" download>⬇ Tümünü indir (ZIP, '
             f'{_boyut(toplam_boyut)})</a></p><div class="ikincil">iPhone: indirilen ZIP Dosyalar uygulamasında '
             f'dokununca açılır. Tek bölüm için ⬇, hemen dinlemek için ▶.</div></div>'
             f'<div class="kart">{"".join(satirlar)}</div>{betik}')
    return _sayfa(k["baslik"], govde, geri="../../")


# --- HTTP ---------------------------------------------------------------------------------------------------
class Isleyici(BaseHTTPRequestHandler):
    server_version = "Libriopax"
    veri = VERI

    def log_message(self, bicim, *arg):
        log.info("%s %s", self.address_string(), bicim % arg)

    def _gonder(self, kod: int, govde: bytes = b"", tur: str = "text/plain; charset=utf-8", basliklar=None):
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for a, d in (basliklar or {}).items():
            self.send_header(a, d)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(govde)

    def _dosya(self, yol: Path, tur: str, indirme_adi: str = None):
        boyut = yol.stat().st_size
        bas, son = 0, boyut - 1
        aralik = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if aralik and (aralik.group(1) or aralik.group(2)):
            if aralik.group(1):
                bas = int(aralik.group(1))
                son = min(int(aralik.group(2)), boyut - 1) if aralik.group(2) else boyut - 1
            else:
                bas = max(boyut - int(aralik.group(2)), 0)
            if bas > son:
                return self._gonder(416, basliklar={"Content-Range": f"bytes */{boyut}"})
        self.send_response(206 if aralik else 200)
        self.send_header("Content-Type", tur)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(son - bas + 1))
        if aralik:
            self.send_header("Content-Range", f"bytes {bas}-{son}/{boyut}")
        if indirme_adi:
            ascii_ad = re.sub(r"[^A-Za-z0-9._ -]", "_", indirme_adi)
            self.send_header("Content-Disposition",
                             f"attachment; filename=\"{ascii_ad}\"; filename*=UTF-8''{quote(indirme_adi)}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(yol, "rb") as f:
            f.seek(bas)
            kalan = son - bas + 1
            while kalan > 0:
                parca = f.read(min(1 << 16, kalan))
                if not parca:
                    break
                try:
                    self.wfile.write(parca)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    return                                   # telefon indirmeyi bıraktı / ileri sardı
                kalan -= len(parca)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        ayar = ayarlar(self.veri)
        giris = (self.headers.get("Tailscale-User-Login") or "").strip().lower()
        if ayar.get("kullanici") and giris and giris != ayar["kullanici"].lower():
            return self._gonder(403, "Bu kitaplık başka bir hesaba ait.".encode())
        url = urlsplit(self.path)
        parcalar = [p for p in url.path.split("/") if p]
        indir = "indir" in parse_qs(url.query)
        try:
            if not parcalar:
                return self._gonder(200, ana_sayfa(kitaplar(self.veri), yerel=not giris, ayar=ayar), "text/html; charset=utf-8")
            if parcalar == ["saglik"]:
                return self._gonder(200, b"ok")
            if parcalar[0] != "k" or len(parcalar) < 2 or not _KITAP.match(parcalar[1]):
                return self._gonder(404, "Bulunamadı.".encode())
            k = next((x for x in kitaplar(self.veri) if x["kimlik"] == parcalar[1]), None)
            if k is None:
                return self._gonder(404, "Kitap bulunamadı.".encode())
            if len(parcalar) == 2:
                if not url.path.endswith("/"):
                    return self._gonder(301, basliklar={"Location": f"{parcalar[1]}/"})
                return self._gonder(200, kitap_sayfasi(k), "text/html; charset=utf-8")
            if len(parcalar) == 4 and parcalar[2] in k["varyantlar"]:
                varyant, ad = parcalar[2], parcalar[3]
                if ad == "kitap.zip":
                    yol = zip_yolu(k, varyant)
                    return self._dosya(yol, "application/zip", f"{k['baslik']}.zip")
                m = re.match(r"^(\d{1,3})\.mp3$", ad)
                b = next((b for b in k["varyantlar"][varyant] if m and b["no"] == int(m.group(1))), None)
                if b:
                    return self._dosya(b["dosya"], "audio/mpeg", b["dosya"].name if indir else None)
            return self._gonder(404, "Bulunamadı.".encode())
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return
        except Exception:
            log.exception("istek hatası: %s", self.path)
            return self._gonder(500, "Sunucu hatası.".encode())


def sunucu(veri: Path = VERI, adres: str = ADRES, port: int = PORT) -> ThreadingHTTPServer:
    isleyici = type("Isleyici", (Isleyici,), {"veri": veri})
    return ThreadingHTTPServer((adres, port), isleyici)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m libriopax.sunucu", description="Libriopax indirme/dinleme sunucusu")
    ap.add_argument("--adres", default=ADRES, help="varsayılan 127.0.0.1 (dışarıya Tailscale ile); ev ağı: 0.0.0.0")
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args(argv)
    VERI.mkdir(exist_ok=True)
    logging.basicConfig(filename=VERI / "sunucu.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        s = sunucu(adres=a.adres, port=a.port)
    except OSError:
        if sys.stderr:
            print(f"{a.adres}:{a.port} kullanımda — sunucu zaten çalışıyor olabilir.", file=sys.stderr)
        return 1
    log.info("başladı %s:%s", a.adres, a.port)
    adres = ayarlar().get("genel_adres")
    if sys.stderr:   # pythonw'da stderr yok
        print(f"Libriopax sunucusu: http://{a.adres}:{a.port}/" + (f"  ·  telefondan: {adres}" if adres else ""), file=sys.stderr)
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
