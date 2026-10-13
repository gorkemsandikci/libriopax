"""Ses motoruna giden metnin okunuşu (kurallı). Gösterilen metin değişmez; bu sadece sentez kopyası.

Piper'ın espeak-ng'si sayıları, saati, yüzdeyi, ondalığı zaten doğru okuyor (S0 ölçümü, 07.10). Burada sadece
eksikler var: kısaltmalar, sıra sayıları ("19. yüzyıl"), Roma rakamları, kesme işaretli sayılar ("1923'te"),
sesli okunan işaretler ("*" → "yıldız").
"""
import re
import unicodedata

BIRLER = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
ONLAR = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
BUYUKLER = [(10 ** 12, "trilyon"), (10 ** 9, "milyar"), (10 ** 6, "milyon"), (1000, "bin")]
SIRA_EKI = {"bir": "birinci", "iki": "ikinci", "üç": "üçüncü", "dört": "dördüncü", "beş": "beşinci",
            "altı": "altıncı", "yedi": "yedinci", "sekiz": "sekizinci", "dokuz": "dokuzuncu", "on": "onuncu",
            "yirmi": "yirminci", "otuz": "otuzuncu", "kırk": "kırkıncı", "elli": "ellinci", "altmış": "altmışıncı",
            "yetmiş": "yetmişinci", "seksen": "sekseninci", "doksan": "doksanıncı", "yüz": "yüzüncü",
            "bin": "bininci", "milyon": "milyonuncu", "milyar": "milyarıncı", "trilyon": "trilyonuncu",
            "sıfır": "sıfırıncı"}

KISALTMA = [  # (desen, okunuş) — sıra önemli
    (r"\[?\b[Ee]d\. ?[Nn]\.\]?", "editörün notu"), (r"\[?\b[Çç]\. ?[Nn]\.\]?", "çevirmenin notu"),
    (r"\[?\b[Yy]\. ?[Nn]\.\]?", "yazarın notu"),
    (r"\bYrd\. ?Doç\.", "Yardımcı Doçent"), (r"\bM\.Ö\.", "milattan önce"), (r"\bM\.S\.", "milattan sonra"),
    (r"\bDr\.", "Doktor"), (r"\bProf\.", "Profesör"), (r"\bDoç\.", "Doçent"), (r"\bOp\.", "Operatör"),
    (r"\bAv\.", "Avukat"), (r"\bSn\.", "Sayın"), (r"\bHz\.", "Hazreti"), (r"\bUzm\.", "Uzman"),
    (r"\bvb\.", "ve benzeri"), (r"\bvs\.", "vesaire"), (r"\bvd\.", "ve diğerleri"), (r"\b[Öö]rn\.", "örneğin"),
    (r"\b[Bb]kz\.", "bakınız"), (r"\bçev\.", "çeviren"), (r"\bhaz\.", "hazırlayan"),
    (r"\bCad\.", "Caddesi"), (r"\bSok\.", "Sokağı"), (r"\bMah\.", "Mahallesi"), (r"\bLtd\.", "Limitet"),
    (r"\bŞti\.", "Şirketi"), (r"\bA\.Ş\.", "Anonim Şirketi"),
    (r"\b[Ss]f?\.(?= ?\d)", "sayfa"), (r"\b[Nn]o\.(?= ?\d)", "numara"),
]
_KISALTMA = [(re.compile(d), o) for d, o in KISALTMA]
_KUCUK = "a-zçğıöşüâîû"
_SIRA = re.compile(rf"\b(\d{{1,4}})\.(?=\s+[{_KUCUK}])")
_ROMA_SIRA = re.compile(r"\b([IVXLCDM]{1,7})\.(?=\s)")
_ROMA_TEK = re.compile(r"\b([IVXLCDM]{1,7})\b")
_KESMELI = re.compile(rf"\b(\d{{1,3}}(?:\.\d{{3}})+|\d+)['’]([{_KUCUK}]+)")
_URL = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\w+")
_ISARET = [(re.compile(r"[*#_|•·~^]+"), " "), (re.compile(r"\.{4,}"), "..."), (re.compile(r"\s{2,}"), " ")]
ROMA = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def sayi_yazi(n: int) -> str:
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + sayi_yazi(-n)
    kelimeler = []
    for deger, ad in BUYUKLER:
        if n >= deger:
            bolum, n = divmod(n, deger)
            if not (deger == 1000 and bolum == 1):        # "bir bin" denmez
                kelimeler.append(sayi_yazi(bolum))
            kelimeler.append(ad)
    if n >= 100:
        yuz, n = divmod(n, 100)
        kelimeler += ([BIRLER[yuz]] if yuz > 1 else []) + ["yüz"]
    if n >= 10:
        kelimeler.append(ONLAR[n // 10])
        n %= 10
    if n:
        kelimeler.append(BIRLER[n])
    return " ".join(kelimeler)


def sira_yazi(n: int) -> str:
    kelimeler = sayi_yazi(n).split()
    kelimeler[-1] = SIRA_EKI[kelimeler[-1]]
    return " ".join(kelimeler)


def roma_coz(s: str):
    """Geçerli Roma rakamıysa değeri, değilse None ("MIX" gibi kelimeleri yanlış çevirmemek için sıkı)."""
    if not s or any(c not in ROMA for c in s):
        return None
    toplam = 0
    for i, c in enumerate(s):
        d = ROMA[c]
        toplam += -d if i + 1 < len(s) and ROMA[s[i + 1]] > d else d
    return toplam if 0 < toplam < 4000 and _roma_yaz(toplam) == s else None


def _roma_yaz(n: int) -> str:
    sonuc = ""
    for d, h in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"),
                 (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= d:
            sonuc, n = sonuc + h, n - d
    return sonuc


def okunus(metin: str, baslik: bool = False) -> str:
    s = _URL.sub(" ", metin)
    for desen, okunusu in _KISALTMA:
        s = desen.sub(okunusu, s)
    s = _KESMELI.sub(lambda m: sayi_yazi(int(m.group(1).replace(".", ""))) + m.group(2), s)
    s = _SIRA.sub(lambda m: sira_yazi(int(m.group(1))), s)

    def roma_sira(m):
        n = roma_coz(m.group(1))
        return sira_yazi(n) if n and (len(m.group(1)) > 1 or baslik) else m.group(0)
    s = _ROMA_SIRA.sub(roma_sira, s)
    if baslik:
        s = _ROMA_TEK.sub(lambda m: sayi_yazi(roma_coz(m.group(1))) if roma_coz(m.group(1)) else m.group(0), s)
    s = s.replace("&", " ve ")
    s = "".join(c for c in s if unicodedata.category(c) not in ("So", "Sk", "Co", "Cn"))   # süs, emoji
    for desen, yerine in _ISARET:
        s = desen.sub(yerine, s)
    s = s.strip()
    if baslik and s and s[-1] not in ".!?…:":
        s += "."                                          # başlıktan sonra duraklasın
    return s
