"""AÖF ünite PDF'i ayrıştırıcı (kurallı, model yok): ders/ünite adı, amaçlar, anahtar kavramlar, ana başlıklara bölünmüş
gövde, kitabın özeti, "Kendimizi Sınayalım" soruları + yanıt anahtarı, "Sıra Sizde" yanıtları, okuma parçası.

Anadolu Üniversitesi ünite şablonu (InDesign): 1. sayfa Amaçlarımız / Anahtar Kavramlar / İçindekiler; sayfa üst bilgisi
"1. Ünite - <ünite adı> 5" ya da "4 <Ders Adı>"; ana başlıklar BÜYÜK HARF; sonda Özet, Kendimizi Sınayalım, Okuma
Parçası / Yaşamın İçinden, Yanıt Anahtarı, Yararlanılan Kaynaklar. Kenar notları ve şekil yazıları gövdeye karışık gelir.
"""
import re
from pathlib import Path

from ..metin import temizle
from ..metin.model import KitapHatasi

_UNITE_UST = re.compile(r"^(\d{1,2})\s*\.\s*Ünite\s*[-–]\s*(.+?)\s+\d{1,3}$")
_DERS_UST = re.compile(r"^\d{1,3}\s+(\S.{2,80})$")
_DOSYA = re.compile(r"^([A-Za-z]{2,5}\d{3}[A-Za-z]?)[_ -]+Unite\s*(\d{1,2})", re.I)
_TEK_RAKAM = re.compile(r"^\d{1,2}$")              # Sıra Sizde / amaç simgeleri
_MADDE = re.compile(r"^[•▪■●◦·-]\s*")
_SORU = re.compile(r"^(\d{1,2})\s*[.)]\s*(.*)$")
_SECENEK = re.compile(r"^([a-eA-E])\s*[.)]\s*(.*)$")
_YANIT = re.compile(r"^(\d{1,2})\s*\.?\s+([a-eA-E])\b[.)]?\s*(.*)$")
_SIRA_SIZDE = re.compile(r"^Sıra Sizde\s*(\d{1,2})\s*(.*)$", re.I)
# Bitiş bölümleri (sayfa satırı tam olarak bu başlıksa)
_BOLUMLER = {
    "ozet": ("özet",),
    "sorular": ("kendimizi sınayalım",),
    "okuma": ("okuma parçası", "yaşamın içinden", "yaşamla ilişkilendir"),
    "yanitlar": ("kendimizi sınayalım yanıt anahtarı",),
    "kaynaklar": ("yararlanılan kaynaklar", "yararlanılan ve başvurulabilecek kaynaklar", "kaynakça"),
}


def _anahtar(s: str) -> str:
    return re.sub(r"\W+", "", temizle.kucuk_harf(s))


def _buyuk_harf_mi(s: str) -> bool:
    harfler = [c for c in s if c.isalpha()]
    return len(harfler) >= 4 and sum(c.isupper() for c in harfler) / len(harfler) > 0.9


def sayfalari_oku(yol) -> list:
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
            sayfa.close()
            metin = re.sub("￾\\s*", "", metin)           # InDesign yumuşak tiresi: "kuy￾" + "ruk"
            sayfalar.append([temizle.satir(s) for s in metin.splitlines()])
    finally:
        belge.close()
    return sayfalar


def _paragraflar(satirlar: list) -> list:
    """Satırları paragraflara birleştirir: nokta ile biten kısa satır ya da boş satır paragrafı bitirir."""
    sonuc, p = [], ""
    for s in satirlar:
        if not s:
            if p:
                sonuc.append(p)
            p = ""
            continue
        p = temizle.birlestir(p, s)
        if re.search(r"[.!?:]$", s) and len(s) < 45:
            sonuc.append(p)
            p = ""
    if p:
        sonuc.append(p)
    return sonuc


def _ilk_sayfa(satirlar: list, ders_adi: str) -> dict:
    bilgi = {"amaclar": [], "kavramlar": [], "basliklar": []}
    kip, madde = None, None
    for s in satirlar:
        a = _anahtar(s)
        if a == "amaçlarımız":
            kip = "amaclar"
            continue
        if a == "anahtarkavramlar":
            kip = "kavramlar"
            continue
        if a == "içindekiler":
            kip = "basliklar"
            continue
        if not s or _TEK_RAKAM.match(s):
            continue
        if kip == "amaclar":
            if a.startswith("buüniteyitamamladıktansonra"):
                continue
            # Amaçlar satır satır gelir; büyük harfle başlayan satır yeni amaç
            if bilgi["amaclar"] and not s[0].isupper():
                bilgi["amaclar"][-1] = temizle.birlestir(bilgi["amaclar"][-1], s)
            else:
                bilgi["amaclar"].append(s)
        elif kip == "kavramlar":
            if _MADDE.match(s):
                bilgi["kavramlar"].append(_MADDE.sub("", s).strip())
        elif kip == "basliklar":
            if ders_adi and a == _anahtar(ders_adi):
                kip = None
            elif _MADDE.match(s):
                madde = _MADDE.sub("", s).strip()
                bilgi["basliklar"].append(madde)
            elif madde is not None and _buyuk_harf_mi(s):
                bilgi["basliklar"][-1] += " " + s
            else:
                madde = None
    # Son amaç "... kazanabileceksiniz." kalıbını taşır; anlamı bozmadan kırp
    bilgi["amaclar"] = [re.sub(r"\s*bilgi ve beceriler kazanabileceksiniz\.?$", "", m).strip() for m in bilgi["amaclar"]]
    return bilgi


def _sorular(satirlar: list) -> list:
    sorular, beklenen, son = [], 1, None
    for s in satirlar:
        if not s:
            continue
        m = _SORU.match(s)
        if m and int(m.group(1)) == beklenen and (son is None or len(son["secenekler"]) == 5):
            son = {"no": beklenen, "soru": m.group(2).strip(), "secenekler": []}
            sorular.append(son)
            beklenen += 1
            continue
        if son is None:
            continue
        m = _SECENEK.match(s)
        if m and "abcde".index(m.group(1).lower()) == len(son["secenekler"]):
            son["secenekler"].append(m.group(2).strip())
        elif son["secenekler"]:
            son["secenekler"][-1] = temizle.birlestir(son["secenekler"][-1], s)
        else:
            son["soru"] = temizle.birlestir(son["soru"], s)
    return [s for s in sorular if len(s["secenekler"]) == 5]


def _yanitlar(satirlar: list) -> tuple:
    """({soru_no: (harf, not)}, [{"no", "yanit"}]) — Kendimizi Sınayalım yanıt anahtarı ve Sıra Sizde yanıtları."""
    anahtar, sira, son, beklenen = {}, [], None, 1
    for s in satirlar:
        if not s:
            continue
        m = _SIRA_SIZDE.match(s)
        if m:
            son = {"no": int(m.group(1)), "yanit": m.group(2).strip()}
            sira.append(son)
            continue
        m = _YANIT.match(s)
        if m and int(m.group(1)) == beklenen and not sira:
            son = [m.group(2).lower(), m.group(3).strip()]
            anahtar[beklenen] = son
            beklenen += 1
            continue
        if isinstance(son, dict):
            son["yanit"] = temizle.birlestir(son["yanit"], s)
        elif isinstance(son, list):
            son[1] = temizle.birlestir(son[1], s)
    return anahtar, [x for x in sira if x["yanit"]]


def ayristir(yol) -> dict:
    yol = Path(yol)
    return sayfalardan(sayfalari_oku(yol), yol.stem)


def sayfalardan(sayfalar: list, dosya_adi: str = "") -> dict:
    """sayfalar: [[satır, ...], ...] (temizle.satir uygulanmış). dosya_adi: ders kodu/ünite no için (ör. LBV101U_Unite1)."""
    if not sayfalar or sum(len(s) for p in sayfalar for s in p) / len(sayfalar) < 80:
        raise KitapHatasi("Bu PDF taranmış (resim) görünüyor; içinde okunacak metin yok.")

    # Üst bilgiler: ünite no/adı ve ders adı (en az iki sayfada aynı)
    unite_no, unite_adi, ders_sayac = None, "", {}
    for satirlar in sayfalar:
        for s in satirlar[:3]:
            m = _UNITE_UST.match(s)
            if m:
                unite_no, unite_adi = int(m.group(1)), m.group(2).strip()
            m = _DERS_UST.match(s)
            if m and not _UNITE_UST.match(s):
                ders_sayac[m.group(1).strip()] = ders_sayac.get(m.group(1).strip(), 0) + 1
    ders_adi = max(ders_sayac, key=ders_sayac.get) if ders_sayac and max(ders_sayac.values()) >= 2 else ""
    m = _DOSYA.match(dosya_adi)
    ders_kodu = m.group(1).upper() if m else ""
    if unite_no is None and m:
        unite_no = int(m.group(2))
    if unite_no is None:
        raise KitapHatasi("Bu PDF AÖF ünite şablonunda görünmüyor (\"N. Ünite - ...\" üst bilgisi yok).")

    def ust_bilgi_mi(s):
        return bool(_UNITE_UST.match(s)) or (ders_adi and _DERS_UST.match(s) and s.endswith(ders_adi))

    temiz = [[s for s in p if not ust_bilgi_mi(s)] for p in sayfalar]
    bilgi = _ilk_sayfa(temiz[0], ders_adi)

    # Sayfa satırlarını tek akışa al, bitiş bölümlerini bul (gövdeden sonra ilk geçtikleri yer)
    akis = [(i + 1, s) for i, p in enumerate(temiz[1:], start=1) for s in p]
    isaret = {}
    for k, (_, s) in enumerate(akis):
        a = temizle.kucuk_harf(" ".join(s.split()))
        for ad, kaliplar in _BOLUMLER.items():
            if ad not in isaret and (a in kaliplar or (ad == "yanitlar" and a.startswith(kaliplar[0]))):
                isaret[ad] = k
    if "ozet" not in isaret:
        raise KitapHatasi("Ünitede \"Özet\" bölümü bulunamadı; şablon farklı.")
    sinirlar = sorted(isaret.items(), key=lambda x: x[1])

    def parca(ad):
        if ad not in isaret:
            return []
        bas = isaret[ad] + 1
        son = next((k for _, k in sinirlar if k > isaret[ad]), len(akis))
        return [s for _, s in akis[bas:son]]

    # Gövde: 2. sayfadan Özet'e; ana başlıklar (İçindekiler'dekiler, yoksa bütün BÜYÜK HARF satırlar) bölüm açar
    govde = akis[:isaret["ozet"]]
    ana = {_anahtar(b) for b in bilgi["basliklar"]}
    bolumler = [{"baslik": "", "sayfa": govde[0][0] if govde else 2, "satirlar": []}]
    for sayfa, s in govde:
        if _TEK_RAKAM.match(s):
            continue
        if _buyuk_harf_mi(s) and (_anahtar(s) in ana if ana else not s.lower().startswith(("şekil", "tablo"))):
            bolumler.append({"baslik": s, "sayfa": sayfa, "satirlar": []})
            continue
        bolumler[-1]["satirlar"].append(s)
    bolumler = [b for b in bolumler if b["baslik"] or any(len(s) > 40 for s in b["satirlar"])]
    for b in bolumler:
        b["metin"] = "\n".join(b.pop("satirlar")).strip()
    if not bolumler[0]["baslik"]:
        bolumler[0]["baslik"] = "Giriş"

    sorular = _sorular(parca("sorular"))
    anahtar, sira_sizde = _yanitlar(parca("yanitlar"))
    for s in sorular:
        if s["no"] in anahtar:
            s["dogru"] = "abcde".index(anahtar[s["no"]][0])
            s["aciklama"] = anahtar[s["no"]][1]
    ozet = [p for p in _paragraflar([s for s in parca("ozet") if not _TEK_RAKAM.match(s)])]
    okuma = _paragraflar(parca("okuma"))
    return {
        "ders_kodu": ders_kodu, "ders_adi": ders_adi, "unite_no": unite_no, "unite_adi": unite_adi,
        "sayfa_sayisi": len(sayfalar), "amaclar": bilgi["amaclar"], "kavramlar": bilgi["kavramlar"],
        "bolumler": bolumler, "ozet": ozet, "sorular": sorular, "sira_sizde": sira_sizde, "okuma": okuma,
    }
