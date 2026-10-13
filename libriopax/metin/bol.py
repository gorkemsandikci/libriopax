"""Türkçe cümle bölme ve sayfalama.

Sayfa: PDF'te fiziksel sayfa (cümle, BAŞLADIĞI sayfaya aittir); EPUB'da bölüm içinde ~HEDEF karakter, cümle sınırında.
Bölüm sınırı her zaman yeni sayfa başlatır.
"""
import bisect
import re

from .model import Kitap, Sayfa

HEDEF = 1500
AZAMI_CUMLE = 900      # bundan uzun cümle ses motoru için ; , ya da boşlukta bölünür
KISALTMALAR = {"dr", "prof", "doç", "doc", "yrd", "av", "sn", "st", "vb", "vs", "vd", "örn", "bkz", "no", "nr",
               "s", "sf", "ss", "c", "haz", "çev", "ed", "mah", "cad", "sok", "apt", "tel", "alb", "yzb", "bnb",
               "org", "gen", "kur", "ltd", "şti", "hz", "mr", "mrs", "ms", "bay", "bayan", "op", "uzm", "ord", "müh"}
_SON = re.compile(r"(?:[.!?]+|…)[\"'”»’)\]]*")
_KELIME_SONU = re.compile(r"[\w.]+$")
KUCUK = set("abcçdefgğhıijklmnoöprsştuüvyzâîûqwx")


def _bolunmez(metin: str, bas: int, nokta: str, sonraki: str) -> bool:
    if sonraki in KUCUK or sonraki in ",;:":
        return True                                   # "Dr. ahmet", "Ne? dedi" — cümle sürüyor
    if nokta != ".":
        return False
    m = _KELIME_SONU.search(metin, 0, bas)
    kelime = m.group(0) if m else ""
    if not kelime:
        return False
    if kelime.lower() in KISALTMALAR or "." in kelime:  # "Prof.", "A.Ş.", "M.Ö."
        return True
    if len(kelime) == 1 and kelime.isalpha() and kelime.isupper():
        return True                                   # baş harf: "A. Haluk"
    if kelime.isdigit() and len(kelime) <= 2 and sonraki.isupper():
        return True                                   # sıra: "3. Bölüm"
    return False


def _uzun_bol(metin: str, bas: int, son: int) -> list:
    parcalar = []
    while son - bas > AZAMI_CUMLE:
        parca = metin[bas:bas + AZAMI_CUMLE]
        kes = max(parca.rfind("; "), parca.rfind(", "))
        if kes < AZAMI_CUMLE // 3:
            kes = parca.rfind(" ")
        if kes <= 0:
            break
        parcalar.append((bas, bas + kes + 1))
        bas += kes + 1
        while bas < son and metin[bas] == " ":
            bas += 1
    return parcalar + [(bas, son)]


def cumlelere_bol(metin: str) -> list:
    """[(bas, son)] — metin içindeki cümle aralıkları (baştaki/sondaki boşluk hariç)."""
    araliklar, bas = [], 0
    for m in _SON.finditer(metin):
        son = m.end()
        i = son
        while i < len(metin) and metin[i] == " ":
            i += 1
        if i >= len(metin):
            break
        if i == son:                                  # noktadan sonra boşluk yok: "3.500", "a.ş."
            continue
        if _bolunmez(metin, m.start(), m.group(0)[0], metin[i]):
            continue
        araliklar.append((bas, son))
        bas = i
    if metin[bas:].strip():
        araliklar.append((bas, len(metin.rstrip())))
    sonuc = []
    for b, s in araliklar:
        while b < s and metin[b].isspace():
            b += 1
        if s > b:
            sonuc += _uzun_bol(metin, b, s)
    return sonuc


def _cumle_akisi(kitap: Kitap):
    """(metin, bolum, kaynak_sayfa, ara) dizisi."""
    for blok in kitap.bloklar:
        araliklar = [(0, len(blok.metin))] if blok.baslik else cumlelere_bol(blok.metin)
        konumlar = [k for k, _ in blok.sayfa_sinirlari]
        for n, (b, s) in enumerate(araliklar):
            kaynak = None
            if konumlar:
                kaynak = blok.sayfa_sinirlari[max(bisect.bisect_right(konumlar, b) - 1, 0)][1]
            ara = "baslik" if blok.baslik else ("paragraf" if n == len(araliklar) - 1 else "cumle")
            yield blok.metin[b:s], blok.bolum, kaynak, ara


def sayfala(kitap: Kitap, hedef: int = HEDEF) -> list:
    sayfalar, parcalar, onceki = [], [], None

    def kapat():
        if not parcalar:
            return
        metin, cumleler = "", []
        for i, (m, ara, _, _) in enumerate(parcalar):
            if i:
                metin += "\n\n" if parcalar[i - 1][1] in ("paragraf", "baslik") else " "
            cumleler.append({"bas": len(metin), "son": len(metin) + len(m), "ara": ara})
            metin += m
        sayfalar.append(Sayfa(len(sayfalar) + 1, parcalar[0][2], metin, cumleler, parcalar[0][3]))
        parcalar.clear()

    uzunluk = 0
    for m, bolum, kaynak, ara in _cumle_akisi(kitap):
        yeni = bool(parcalar) and (
            bolum != onceki[0]
            or (kitap.tur == "pdf" and kaynak != onceki[1])
            or (kitap.tur != "pdf" and uzunluk + len(m) > hedef)
            or (kitap.tur != "pdf" and ara == "baslik" and uzunluk > hedef * 0.6))
        if yeni:
            kapat()
            uzunluk = 0
        parcalar.append((m, ara, bolum, kaynak))
        uzunluk += len(m) + 1
        onceki = (bolum, kaynak)
    kapat()
    return sayfalar
