"""EPUB ayrıştırıcı (sadece stdlib). Dosya diske açılmaz; zip içinden adla okunur."""
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from .model import Blok, Kitap, KitapHatasi

AZAMI_ACIK_BOYUT = 500 * 1024 * 1024   # zip bombası koruması
AZAMI_DOSYA = 5000
# Sadece yazı tiplerini gizleyen "şifreleme" DRM değildir (IDPF / Adobe font obfuscation)
FONT_GIZLEME = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}

BLOK_ETIKETLER = {"p", "div", "li", "blockquote", "section", "article", "tr", "dd", "dt", "pre", "figcaption",
                  "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer", "aside", "table", "ul", "ol", "body"}
BASLIK_ETIKETLER = {"h1", "h2", "h3", "h4", "h5", "h6"}
ATLA_ETIKETLER = {"script", "style", "head", "title", "svg", "math", "noscript", "rt", "rp"}
_DIPNOT_NO = re.compile(r"^[\s\d*†‡,\[\]]+$")
DIPNOT_TURLERI = {"noteref", "footnote", "endnote", "rearnote", "note"}


def _yerel(etiket: str) -> str:
    return etiket.rsplit("}", 1)[-1]


class _MetinCikarici(HTMLParser):
    """XHTML'den paragraf/başlık listesi: [(metin, baslik_mi)]. Betik/stil ve dipnot göndermeleri atlanır."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraflar, self._tampon, self._atla, self._baslik, self._ust = [], [], [], 0, 0

    def _bosalt(self):
        metin = " ".join("".join(self._tampon).split())
        if metin:
            self.paragraflar.append((metin, self._baslik > 0))
        self._tampon = []

    def handle_starttag(self, etiket, nitelikler):
        nit = dict(nitelikler)
        tur = set((nit.get("epub:type") or nit.get("role") or "").replace("doc-", "").split())
        if self._atla:
            if etiket not in ("br", "img", "hr", "meta", "link"):
                self._atla.append(etiket)
            return
        if etiket in ATLA_ETIKETLER or tur & DIPNOT_TURLERI:
            self._atla.append(etiket)
            return
        if etiket == "br" or etiket in BLOK_ETIKETLER:
            self._bosalt()
        if etiket in BASLIK_ETIKETLER:
            self._baslik += 1
        if etiket == "sup" or (etiket == "a" and "#" in (nit.get("href") or "")):
            self._ust += 1                                # <sup>3</sup> ya da <a href="notlar#3">3</a>

    def handle_startendtag(self, etiket, nitelikler):
        if etiket == "br" and not self._atla:
            self._bosalt()

    def handle_endtag(self, etiket):
        if self._atla:
            if etiket == self._atla[-1]:
                self._atla.pop()
            return
        if etiket in BLOK_ETIKETLER:
            self._bosalt()
        if etiket in BASLIK_ETIKETLER and self._baslik:
            self._baslik -= 1
        if etiket in ("sup", "a") and self._ust:
            self._ust -= 1

    def handle_data(self, veri):
        if self._atla or (self._ust and _DIPNOT_NO.match(veri)):   # <sup>3</sup>: dipnot numarası
            return
        self._tampon.append(veri)

    def close(self):
        super().close()
        self._bosalt()


def _xhtml_paragraflari(veri: bytes) -> list:
    c = _MetinCikarici()
    c.feed(veri.decode("utf-8", errors="replace"))
    c.close()
    return c.paragraflar


class _NavOkuyucu(HTMLParser):
    """EPUB3 nav belgesinden toc bağlantıları: [(href, metin)]."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.baglantilar, self._toc, self._href, self._metin = [], 0, None, []

    def handle_starttag(self, etiket, nitelikler):
        nit = dict(nitelikler)
        if etiket == "nav":
            self._toc = self._toc + 1 if (self._toc or "toc" in (nit.get("epub:type") or "").split()) else 0
        elif etiket == "a" and self._toc:
            self._href, self._metin = nit.get("href"), []

    def handle_endtag(self, etiket):
        if etiket == "nav" and self._toc:
            self._toc -= 1
        elif etiket == "a" and self._href is not None:
            self.baglantilar.append((self._href, " ".join("".join(self._metin).split())))
            self._href = None

    def handle_data(self, veri):
        if self._href is not None:
            self._metin.append(veri)


def _guvenlik(z: zipfile.ZipFile) -> None:
    bilgiler = z.infolist()
    if len(bilgiler) > AZAMI_DOSYA or sum(b.file_size for b in bilgiler) > AZAMI_ACIK_BOYUT:
        raise KitapHatasi("Bu EPUB çok büyük ya da bozuk görünüyor.")
    if "META-INF/encryption.xml" in z.namelist():
        kok = ET.fromstring(z.read("META-INF/encryption.xml"))
        for veri in (e for e in kok.iter() if _yerel(e.tag) == "EncryptedData"):
            yontem = next((e.get("Algorithm") for e in veri.iter() if _yerel(e.tag) == "EncryptionMethod"), "")
            if yontem not in FONT_GIZLEME:
                raise KitapHatasi("Bu EPUB şifreli (DRM). Sadece DRM'siz EPUB dosyaları okunabilir.")


def oku(yol) -> Kitap:
    try:
        z = zipfile.ZipFile(yol)
    except (zipfile.BadZipFile, OSError) as hata:
        raise KitapHatasi("Bu dosya geçerli bir EPUB değil (zip açılamadı).") from hata
    with z:
        _guvenlik(z)
        try:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            opf_yolu = next(e.get("full-path") for e in container.iter() if _yerel(e.tag) == "rootfile")
            opf = ET.fromstring(z.read(opf_yolu))
        except (KeyError, StopIteration, ET.ParseError) as hata:
            raise KitapHatasi("EPUB'un içindekiler dosyası (OPF) okunamadı.") from hata
        taban = posixpath.dirname(opf_yolu)
        tam = lambda href: posixpath.normpath(posixpath.join(taban, unquote(href.split("#")[0])))

        meta = {}
        for e in opf.iter():
            ad = _yerel(e.tag)
            if ad in ("title", "creator", "language") and ad not in meta and (e.text or "").strip():
                meta[ad] = " ".join(e.text.split())
        ogeler = {e.get("id"): e for e in opf.iter() if _yerel(e.tag) == "item"}
        spine_el = next((e for e in opf.iter() if _yerel(e.tag) == "spine"), None)
        if spine_el is None:
            raise KitapHatasi("EPUB'da okuma sırası (spine) yok.")
        spine = [ogeler[i.get("idref")] for i in spine_el if _yerel(i.tag) == "itemref"
                 and i.get("idref") in ogeler and i.get("linear", "yes") != "no"]

        # İçindekiler: dosya → ilk başlık
        toc, nav_dosya = [], None
        nav = next((o for o in ogeler.values() if "nav" in (o.get("properties") or "").split()), None)
        if nav is not None:
            nav_dosya = tam(nav.get("href"))
            n = _NavOkuyucu()
            n.feed(z.read(nav_dosya).decode("utf-8", errors="replace"))
            toc = [(posixpath.normpath(posixpath.join(posixpath.dirname(nav_dosya), unquote(h.split("#")[0]))), m)
                   for h, m in n.baglantilar if h]
        elif spine_el.get("toc") in ogeler:
            ncx_yolu = tam(ogeler[spine_el.get("toc")].get("href"))
            for nokta in (e for e in ET.fromstring(z.read(ncx_yolu)).iter() if _yerel(e.tag) == "navPoint"):
                etiket = next((" ".join((t.text or "").split()) for t in nokta.iter() if _yerel(t.tag) == "text"), "")
                kaynak = next((c.get("src") for c in nokta if _yerel(c.tag) == "content"), None)
                if kaynak:
                    toc.append((posixpath.normpath(posixpath.join(posixpath.dirname(ncx_yolu),
                                                                  unquote(kaynak.split("#")[0]))), etiket))
        toc_basliklari = {}
        for dosya, metin in toc:
            if metin:
                toc_basliklari.setdefault(dosya, metin)

        bolumler, bloklar = [], []
        for oge in spine:
            if "html" not in (oge.get("media-type") or ""):
                continue
            dosya = tam(oge.get("href"))
            if dosya == nav_dosya:
                continue
            try:
                paragraflar = _xhtml_paragraflari(z.read(dosya))
            except KeyError:
                continue
            if not paragraflar:
                continue
            yeni = toc_basliklari.get(dosya)
            if yeni is None and not toc_basliklari:
                yeni = next((m for m, b in paragraflar if b), None)   # içindekiler yoksa dosyanın ilk başlığı
            if yeni is not None or not bolumler:
                bolumler.append(yeni or meta.get("title") or "Giriş")
            bloklar += [Blok(m, len(bolumler) - 1, b) for m, b in paragraflar]

    if not bloklar:
        raise KitapHatasi("EPUB'da okunacak metin bulunamadı.")
    return Kitap(baslik=meta.get("title", ""), yazar=meta.get("creator", ""), dil=meta.get("language", "tr"),
                 tur="epub", bolumler=bolumler, bloklar=bloklar)
