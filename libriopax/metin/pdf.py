"""PDF ayrıştırıcı (pypdfium2). Sayfa satırları → temizlik → sayfalar arası paragraflar (fiziksel sayfa korunur)."""
import re
import statistics

from . import temizle
from .model import Blok, Kitap, KitapHatasi

AZ_METIN = 80          # sayfa başına ortalama karakter bunun altındaysa taranmış PDF
_PARAGRAF_SONU = re.compile(r"[.!?…:\"”»’)]$")
_DIYALOG = re.compile(r"^[—–-]\s")


def _anahtar(s: str) -> str:
    return re.sub(r"\W+", "", s.lower())


def _icindekiler(belge) -> dict:
    """{sayfa_indeksi: [başlık, ...]} — en üst düzey yer imleri."""
    ogeler = []
    for o in belge.get_toc():
        hedef = o.get_dest()                       # pypdfium2 5: get_title()/get_dest() (4'teki .title yok)
        indeks = hedef.get_index() if hedef is not None else None
        if indeks is not None:
            o.title, o.page_index = o.get_title(), indeks
            ogeler.append(o)
    if not ogeler:
        return {}
    # Bölüm düzeyi: en az iki yer imi olan en üst düzey (tek kökü kitap adı olan PDF'lerde bir alt düzey)
    duzeyler = sorted({o.level for o in ogeler})
    ust = next((d for d in duzeyler if sum(o.level == d for o in ogeler) >= 2), duzeyler[0])
    sonuc = {}
    for o in ogeler:
        if o.level == ust and (o.title or "").strip():
            sonuc.setdefault(o.page_index, []).append(" ".join(o.title.split()))
    return sonuc


def oku(yol) -> Kitap:
    import pypdfium2 as pdfium
    try:
        belge = pdfium.PdfDocument(str(yol))
    except pdfium.PdfiumError as hata:
        raise KitapHatasi("PDF açılamadı (bozuk ya da parola korumalı).") from hata
    try:
        sayfalar = []
        for i in range(len(belge)):
            sayfa = belge[i]
            metin = sayfa.get_textpage().get_text_range()
            sayfalar.append([temizle.satir(s) for s in metin.splitlines()])
            sayfa.close()
        meta = belge.get_metadata_dict()
        toc = _icindekiler(belge)
    finally:
        belge.close()

    if not sayfalar or sum(len(s) for p in sayfalar for s in p) / len(sayfalar) < AZ_METIN:
        raise KitapHatasi("Bu PDF taranmış (resim) görünüyor; içinde okunacak metin yok. Şimdilik okunamıyor.")
    sayfalar = temizle.ust_alt_bilgi_ayikla(sayfalar)
    dolu = [len(s) for p in sayfalar for s in p if len(s) > 20]
    tipik = statistics.median(dolu) if dolu else 60

    bolumler = [meta.get("Title") or "Kitap"] if 0 not in toc else []
    bloklar, paragraf, sinirlar = [], "", []

    def bitir(baslik=False):
        nonlocal paragraf, sinirlar
        metin = temizle.dipnot_isaretleri(paragraf).strip()
        if metin:
            bloklar.append(Blok(metin, len(bolumler) - 1, baslik, sinirlar if sinirlar else []))
        paragraf, sinirlar = "", []

    for indeks, satirlar in enumerate(sayfalar):
        bekleyen = list(toc.get(indeks, []))
        sayfa_basi = True
        for s in satirlar:
            if not s:
                bitir()
                continue
            # İçindekilerdeki başlık bu sayfada geçiyorsa yeni bölüm (başlık satırı blok olur)
            if bekleyen and _anahtar(s) and _anahtar(s) in _anahtar(bekleyen[0]):
                bitir()
                bolumler.append(bekleyen.pop(0))
                paragraf, sinirlar = s, [(0, indeks + 1)]
                bitir(baslik=True)
                continue
            if paragraf and _DIYALOG.match(s):
                bitir()
            if sayfa_basi or not paragraf:
                sinirlar.append((len(paragraf) + (1 if paragraf else 0), indeks + 1))
                sayfa_basi = False
            paragraf = temizle.birlestir(paragraf, s)
            if _PARAGRAF_SONU.search(s) and len(s) < tipik * 0.8:
                bitir()
        while bekleyen:   # metinde bulunamayan yer imi: bölüm yine de bu sayfadan başlar
            bitir()
            bolumler.append(bekleyen.pop(0))
    bitir()
    if not bolumler:
        bolumler.append(meta.get("Title") or "Kitap")
    # İlk bölüm yer iminden önce metin varsa -1 bölüme düşmüş olabilir
    for b in bloklar:
        b.bolum = max(b.bolum, 0)
    return Kitap(baslik=meta.get("Title", ""), yazar=meta.get("Author", ""), dil="tr", tur="pdf",
                 bolumler=bolumler, bloklar=bloklar, kaynak_sayfa_sayisi=len(sayfalar))
