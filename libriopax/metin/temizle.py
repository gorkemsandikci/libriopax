"""Kurallı metin temizliği (yapay zeka yok; metin uydurulmaz): üst/alt bilgi, sayfa numarası, tireleme, görünmez karakterler."""
import re
import unicodedata
from collections import Counter

_LIGATURLER = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
_GORUNMEZ = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")   # sıfır genişlik + yumuşak tire
_SAYFA_NO = re.compile(r"^[\s\-–—.]*(?:sayfa\s*|s\.\s*|page\s*)?(\d{1,4}|[ivxlcdm]{1,8})[\s\-–—.]*$", re.I)
_DIPNOT = re.compile(r"(?<=[a-zçğıöşüâîû])\d{1,2}(?=[\s.,;:!?)\"”’]|$)")
KUCUK = "abcçdefgğhıijklmnoöprsştuüvyzâîûqwx"


def satir(s: str) -> str:
    """Tek satırı normalleştirir (birleştirmeden önce)."""
    s = unicodedata.normalize("NFC", s)
    for eski, yeni in _LIGATURLER.items():
        s = s.replace(eski, yeni)
    s = s.replace("\x02", "-")          # pdfium satır sonu tiresini U+0002 olarak verir
    s = _GORUNMEZ.sub("", s).replace("\u00a0", " ").replace("\t", " ")
    return " ".join(s.split())


def dipnot_isaretleri(s: str) -> str:
    """'konağın3 kapısı' → 'konağın kapısı' (PDF'te üst simge dipnot numaraları düz rakam gelir)."""
    return _DIPNOT.sub("", s)


def _anahtar(s: str) -> str:
    return re.sub(r"\d+", "#", kucuk_harf(s)).strip()


def kucuk_harf(s: str) -> str:
    """Türkçe küçük harf: "KİTABIN" → "kitabın" (str.lower "ki̇tabin" verir)."""
    return s.replace("İ", "i").replace("I", "ı").lower()


def ust_alt_bilgi_ayikla(sayfalar: list) -> list:
    """sayfalar: her sayfa için satır listesi. Sayfaların çoğunda AYNI KONUMDA (baştan 1./2. ya da sondan 1./2. satır)
    tekrar eden satırları (kitap adı, bölüm adı, "Sayfa 12") ve kenardaki tek başına sayfa numaralarını siler.
    Konum şartı, sayfa kenarına denk gelen sıradan satırların ("— Evet.") silinmesini önler."""
    def kenarlar(satirlar):
        dolu = [i for i, s in enumerate(satirlar) if s.strip()]
        return {i: k for k, i in [(1, x) for x in dolu[:1]] + [(2, x) for x in dolu[1:2]]
                + [(-2, x) for x in dolu[-2:-1]] + [(-1, x) for x in dolu[-1:]]} if len(dolu) > 2 else {}

    sayac = Counter()
    for satirlar in sayfalar:
        sayac.update({(k, _anahtar(satirlar[i])) for i, k in kenarlar(satirlar).items()})
    esik = max(3, int(len(sayfalar) * 0.3))
    tekrar = {a for a, n in sayac.items() if n >= esik and a[1]}
    sonuc = []
    for satirlar in sayfalar:
        kenar = kenarlar(satirlar)
        sonuc.append([s for i, s in enumerate(satirlar)
                      if not (i in kenar and ((kenar[i], _anahtar(s)) in tekrar or _SAYFA_NO.match(s)))])
    return sonuc


def birlestir(onceki: str, sonraki: str) -> str:
    """İki satırı paragraf içinde birleştirir. 'kelime-' + 'si' → 'kelimesi'; 'Ankara-' + 'İstanbul' → 'Ankara-İstanbul'."""
    if not onceki:
        return sonraki
    if onceki.endswith("-") and len(onceki) > 1 and onceki[-2].isalpha() and sonraki:
        return onceki[:-1] + sonraki if sonraki[0] in KUCUK else onceki + sonraki
    return onceki + " " + sonraki
