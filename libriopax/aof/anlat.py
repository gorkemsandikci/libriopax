"""AÖF ünitesi → hoca anlatımı (Gemini) + sınav hazırlığı (Gemini) + ses (Piper).

Her adımın çıktısı ünite klasörüne yazılır; kota dolup yarıda kalan iş bir sonraki koşuda kaldığı yerden sürer:

    veri/aof/dersler/<DERS>/<NN>/
        kaynak.pdf          gelen kutusundan taşınan PDF
        unite.json          kurallı ayrıştırma (unite.ayristir), model yok
        anlatim/01.json     ana başlık başına anlatım: {"kisimlar": [{"baslik", "paragraflar"}], "dikkat": [...]}
        hazirlik.json       kavramlar, ek deneme soruları, Sıra Sizde soruları
        ses/anlatim.mp3     anlatımın tamamı + anlatim.json (başlık başlangıç zamanları)
        ses/ozet.mp3        kitabın kendi özeti (birebir)
"""
import json
import os
import re
from types import SimpleNamespace
from pathlib import Path

from ..metin import bol
from ..ses import uretici
from . import unite as unite_mod

SISTEM_ANLATIM = """Sen Anadolu Üniversitesi Açıköğretim Fakültesi'nde ders anlatan deneyimli bir öğretim elemanısın.
Sana bir ders kitabı ünitesinin bir bölümü, PDF'ten çıkarılmış ham metin olarak verilecek. Görevin bu bölümü öğrencinin
sesli dinleyeceği ve okuyacağı bir ders anlatımına dönüştürmek.

Kurallar:
1. Sadece metindeki bilgiyi anlat. Metinde olmayan olgu, sayı, tarih, isim ya da örnek ekleme.
2. Metindeki bütün konuları sırasıyla ve eksiksiz anlat; özetleyip atlama. Tanımların kitaptaki anlamını koru.
3. Sade, net Türkçe kullan; kısa ve orta uzunlukta cümleler kur. Selamlama, "harika", "hadi başlayalım" gibi dolgu yok.
4. Yabancı terimlerde metinde verilen Türkçe karşılığı mutlaka söyle; okunuşu metinde varsa onu da kullan.
5. Metin sesli okunacak: tablo, madde imi, markdown, emoji kullanma. Listeleri cümleyle anlat
   ("Dört düzlem vardır. Birincisi ..., ikincisi ...").
6. Ham metne şekil açıklamaları, "Kaynak:" künyeleri ve sayfa kenarı notları karışık gelir. Şekil yazılarını ve künyeleri
   anlatma; kenar notundaki tanım konuyla ilgiliyse uygun yerde anlat. Satır kırılmasıyla bozulmuş kelimeleri bağlamdan düzelt.
7. Anlamayı kolaylaştırmak için günlük hayattan bir benzetme yapabilirsin; bunu açıkça benzetme olarak söyle, yeni bilgi gibi sunma.
8. Anlatımı alt konulara böl (kisimlar); her kısmın kısa bir başlığı olsun. Paragraflar 2-6 cümle.
   Kitaptaki her tanımı, sınıflandırmayı, sayıyı ve örneği koru; ham metindeki her paragraf anlatımda karşılık bulsun.
9. "dikkat" alanına bu bölümden sınavda sorulma olasılığı yüksek 3-6 kısa nokta yaz (tanım, sınıflandırma, karıştırılan kavramlar)."""

SISTEM_HAZIRLIK = """Sen Anadolu Üniversitesi Açıköğretim sınavlarına soru hazırlayan bir öğretim elemanısın. Sana bir ünitenin
ham metni, kitabın kendi soruları ve "Sıra Sizde" etkinliklerinin yanıtları verilecek.

1. kavramlar: ünitenin 10-20 temel kavramı; her biri için metne sadık, tek cümlelik açıklama.
2. sorular: AÖF tarzında 10 yeni çoktan seçmeli soru. Beş seçenek, tek doğru cevap ("dogru": 0-4, seçenek sırası).
   Soru kökleri çeşitli olsun ("aşağıdakilerden hangisidir", "hangisi yanlıştır", "hangisi ... değildir").
   Sadece metindeki bilgiden sor; kitabın kendi sorularını tekrarlama. Çeldiriciler metindeki benzer kavramlardan seçilsin.
   "aciklama": doğru cevabın neden doğru olduğunu tek-iki cümleyle, metne dayanarak anlat.
3. sira_sizde: her "Sıra Sizde" yanıtı için, o yanıtın cevapladığı soruyu yaz (kısa, açık uçlu)."""

_DIZI = {"type": "ARRAY", "items": {"type": "STRING"}}
SEMA_ANLATIM = {
    "type": "OBJECT",
    "properties": {
        "kisimlar": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "baslik": {"type": "STRING"}, "paragraflar": _DIZI}, "required": ["baslik", "paragraflar"]}},
        "dikkat": _DIZI,
    },
    "required": ["kisimlar", "dikkat"],
}
SEMA_HAZIRLIK = {
    "type": "OBJECT",
    "properties": {
        "kavramlar": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "terim": {"type": "STRING"}, "aciklama": {"type": "STRING"}}, "required": ["terim", "aciklama"]}},
        "sorular": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "soru": {"type": "STRING"}, "secenekler": _DIZI, "dogru": {"type": "INTEGER"},
            "aciklama": {"type": "STRING"}}, "required": ["soru", "secenekler", "dogru", "aciklama"]}},
        "sira_sizde": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "no": {"type": "INTEGER"}, "soru": {"type": "STRING"}}, "required": ["no", "soru"]}},
    },
    "required": ["kavramlar", "sorular", "sira_sizde"],
}
_GUVENLI = re.compile(r"[^A-Za-z0-9]+")
PARCA_SINIRI = 6000             # bir anlatım isteğine giden en uzun ham metin (karakter)


def json_oku(yol: Path, varsayilan=None):
    try:
        return json.loads(Path(yol).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return varsayilan


def json_yaz(veri, yol: Path) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_name(yol.name + ".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(gecici, yol)


# --- gelen kutusu --------------------------------------------------------------------------------------------
def ders_klasoru(u: dict) -> str:
    if u["ders_kodu"]:
        return u["ders_kodu"]
    ad = unite_mod.temizle.kucuk_harf(u["ders_adi"] or "ders")
    ad = ad.translate(str.maketrans("çğıöşü", "cgiosu"))
    return _GUVENLI.sub("-", ad).strip("-")[:40] or "ders"


def gelenleri_al(aof: Path) -> tuple:
    """gelen/*.pdf → dersler/<DERS>/<NN>/ (unite.json + kaynak.pdf). ([yeni ünite dizinleri], [(dosya, hata)])."""
    gelen = aof / "gelen"
    yeniler, hatalar = [], []
    if not gelen.is_dir():
        return yeniler, hatalar
    for pdf in sorted(p for p in gelen.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"):
        try:
            u = unite_mod.ayristir(pdf)
        except unite_mod.KitapHatasi as hata:
            hatalar.append((pdf.name, str(hata)))
            (gelen / "hatali").mkdir(exist_ok=True)
            os.replace(pdf, gelen / "hatali" / pdf.name)
            continue
        dizin = aof / "dersler" / ders_klasoru(u) / f"{u['unite_no']:02}"
        u["kaynak_dosya"] = pdf.name
        if dizin.exists() and json_oku(dizin / "unite.json", {}).get("kaynak_dosya") != pdf.name:
            # Aynı ünite başka bir dosyadan yeniden geldi: eski çıktılar geçersiz
            for alt in ("anlatim", "ses"):
                for f in (dizin / alt).glob("*") if (dizin / alt).is_dir() else []:
                    f.unlink()
            (dizin / "hazirlik.json").unlink(missing_ok=True)
        json_yaz(u, dizin / "unite.json")
        os.replace(pdf, dizin / "kaynak.pdf")
        yeniler.append(dizin)
    return yeniler, hatalar


def uniteler(aof: Path) -> list:
    return sorted(p.parent for p in (aof / "dersler").glob("*/*/unite.json"))


# --- Gemini adımları -----------------------------------------------------------------------------------------
def _baslik(u: dict) -> str:
    return f"Ders: {u['ders_adi'] or u['ders_kodu']}\nÜnite {u['unite_no']}: {u['unite_adi']}"


def parcalara_bol(metin: str, sinir: int = None) -> list:
    """Uzun bölüm metnini BÜYÜK HARF alt başlıklardan (yoksa satır sınırından) en fazla `sinir` karakterlik parçalara
    böler. Model tek istekte uzun metni sıkıştırıyor (13.800 → 3.800 kar.); parça parça anlatınca kapsam korunur."""
    sinir = sinir or PARCA_SINIRI
    if len(metin) <= sinir:
        return [metin]
    bloklar, blok = [], []
    for satir in metin.split("\n"):
        if blok and unite_mod._buyuk_harf_mi(satir):
            bloklar.append("\n".join(blok))
            blok = []
        blok.append(satir)
    bloklar.append("\n".join(blok))
    parcalar, simdiki = [], ""
    for b in bloklar:
        while len(b) > sinir:                             # alt başlıksız uzun blok: satır sınırından kes
            kes = b.rfind("\n", 0, sinir)
            kes = kes if kes > sinir // 2 else sinir
            if simdiki:
                parcalar.append(simdiki)
                simdiki = ""
            parcalar.append(b[:kes])
            b = b[kes:].lstrip("\n")
        if simdiki and len(simdiki) + len(b) + 1 > sinir:
            parcalar.append(simdiki)
            simdiki = b
        else:
            simdiki = f"{simdiki}\n{b}" if simdiki else b
    if simdiki:
        parcalar.append(simdiki)
    return parcalar


def _anlatim_iste(u: dict, baslik: str, metin: str, istemci, parca: str = "") -> dict:
    amaclar = "\n".join(f"- {a}" for a in u["amaclar"])
    istem = (f"{_baslik(u)}\nBölüm: {baslik}{parca}\nÜnitenin amaçları:\n{amaclar}\n\n"
             f"Anlatımın uzunluğu, ham metnin şekil yazıları ve künyeler dışındaki kısmından kısa olmasın "
             f"(ham metin yaklaşık {len(metin) // 100 * 100} karakter).\n\nHAM METİN (PDF'ten):\n{metin}")
    cevap = istemci.json_uret(istem, SEMA_ANLATIM, sistem=SISTEM_ANLATIM)
    kisimlar = [{"baslik": (k.get("baslik") or "").strip(),
                 "paragraflar": [p.strip() for p in k.get("paragraflar") or [] if p and p.strip()]}
                for k in cevap.get("kisimlar") or []]
    kisimlar = [k for k in kisimlar if k["paragraflar"]]
    if not kisimlar:
        raise unite_mod.KitapHatasi(f"Gemini '{baslik}' için boş anlatım döndü.")
    return {"kisimlar": kisimlar, "dikkat": [d.strip() for d in cevap.get("dikkat") or [] if d and d.strip()]}


def anlatim_yap(dizin: Path, u: dict, istemci) -> int:
    """Eksik bölüm anlatımlarını üretir; yapılan istek sayısı. Uzun bölümün parçaları ayrı dosyaya (01-2.json) yazılır,
    hepsi bitince bölüm dosyasında (01.json) birleşir. KotaDoldu yukarı geçer (yazılanlar kalır)."""
    sayi = 0
    for i, b in enumerate(u["bolumler"], start=1):
        hedef = dizin / "anlatim" / f"{i:02}.json"
        if hedef.exists():
            continue
        parcalar = parcalara_bol(b["metin"])
        sonuclar = []
        for j, metin in enumerate(parcalar, start=1):
            ara = dizin / "anlatim" / f"{i:02}-{j}.json"
            if len(parcalar) > 1 and ara.exists():
                sonuclar.append(json_oku(ara))
                continue
            etiket = (f" (bölümün {j}/{len(parcalar)}. parçası; diğer parçalar ayrı anlatılıyor, giriş ve kapanış "
                      f"cümlesi yazma)") if len(parcalar) > 1 else ""
            sonuc = _anlatim_iste(u, b["baslik"], metin, istemci, etiket)
            sayi += 1
            if len(parcalar) > 1:
                json_yaz(sonuc, ara)
            sonuclar.append(sonuc)
        json_yaz({"baslik": b["baslik"], "kisimlar": [k for x in sonuclar for k in x["kisimlar"]],
                  "dikkat": [d for x in sonuclar for d in x["dikkat"]]}, hedef)
        for ara in (dizin / "anlatim").glob(f"{i:02}-*.json"):
            ara.unlink()
    return sayi


def _soru_gecerli(s: dict) -> bool:
    secenekler = [x.strip() for x in s.get("secenekler") or []]
    return (bool((s.get("soru") or "").strip()) and len(secenekler) == 5 and all(secenekler)
            and len({x.lower() for x in secenekler}) == 5 and isinstance(s.get("dogru"), int) and 0 <= s["dogru"] < 5)


def hazirlik_yap(dizin: Path, u: dict, istemci) -> bool:
    hedef = dizin / "hazirlik.json"
    if hedef.exists():
        return False
    kitap_sorulari = "\n".join(f"{s['no']}. {s['soru']}" for s in u["sorular"]) or "(yok)"
    sira = "\n".join(f"Sıra Sizde {x['no']}: {x['yanit']}" for x in u["sira_sizde"]) or "(yok)"
    govde = "\n\n".join(f"## {b['baslik']}\n{b['metin']}" for b in u["bolumler"])
    istem = (f"{_baslik(u)}\n\nKİTABIN KENDİ SORULARI (tekrarlama):\n{kitap_sorulari}\n\nSIRA SİZDE YANITLARI:\n{sira}"
             f"\n\nÜNİTE METNİ (PDF'ten, ham):\n{govde}")
    cevap = istemci.json_uret(istem, SEMA_HAZIRLIK, sistem=SISTEM_HAZIRLIK)
    sorular = [{"soru": s["soru"].strip(), "secenekler": [x.strip() for x in s["secenekler"]], "dogru": s["dogru"],
                "aciklama": (s.get("aciklama") or "").strip()} for s in cevap.get("sorular") or [] if _soru_gecerli(s)]
    sira_no = {x["no"] for x in u["sira_sizde"]}
    json_yaz({
        "kavramlar": [k for k in cevap.get("kavramlar") or [] if k.get("terim") and k.get("aciklama")],
        "sorular": sorular,
        "sira_sizde": [x for x in cevap.get("sira_sizde") or [] if x.get("no") in sira_no and x.get("soru")],
    }, hedef)
    return True


# --- ses -----------------------------------------------------------------------------------------------------
def _parca(metin: str, ara: str = "paragraf") -> SimpleNamespace:
    """uretici.sayfa_sesi'nin beklediği biçim: metin + cümle aralıkları (son cümleden sonra `ara` kadar sessizlik)."""
    cumleler = [{"bas": b, "son": s, "ara": "cumle"} for b, s in bol.cumlelere_bol(metin)]
    if cumleler:
        cumleler[-1]["ara"] = ara
    return SimpleNamespace(metin=metin, cumleler=cumleler)


def anlatim_tamam_mi(dizin: Path, u: dict) -> bool:
    return all((dizin / "anlatim" / f"{i:02}.json").exists() for i in range(1, len(u["bolumler"]) + 1))


def ses_yap(dizin: Path, u: dict, motor) -> list:
    """Eksik ses dosyalarını üretir (anlatım bittiyse anlatim.mp3, her zaman ozet.mp3); üretilen adlar."""
    hedef = dizin / "ses"
    uretilen = []
    if not (hedef / "ozet.json").exists() and u["ozet"]:
        parcalar = [_parca(f"{u['unite_no']}. Ünite özeti. {u['unite_adi']}.", "baslik")]
        parcalar += [_parca(p) for p in u["ozet"]]
        _yaz(motor, parcalar, hedef / "ozet.mp3", [])
        uretilen.append("ozet")
    if not (hedef / "anlatim.json").exists() and anlatim_tamam_mi(dizin, u):
        parcalar, imler = [_parca(f"{u['ders_adi']}. {u['unite_no']}. Ünite. {u['unite_adi']}.", "baslik")], []
        dikkat = []
        for i in range(1, len(u["bolumler"]) + 1):
            a = json_oku(dizin / "anlatim" / f"{i:02}.json")
            for k in a["kisimlar"]:
                imler.append((len(parcalar), k["baslik"]))
                parcalar.append(_parca(k["baslik"] + ".", "baslik"))
                parcalar += [_parca(p) for p in k["paragraflar"]]
            dikkat += a.get("dikkat") or []
        if dikkat:
            imler.append((len(parcalar), "Sınavda dikkat"))
            parcalar.append(_parca("Sınavda dikkat edilecek noktalar.", "baslik"))
            parcalar += [_parca(d) for d in dikkat]
        _yaz(motor, parcalar, hedef / "anlatim.mp3", imler)
        uretilen.append("anlatim")
    return uretilen


def _yaz(motor, parcalar: list, yol: Path, imler: list) -> None:
    pcm, baslar = bytearray(), []
    for p in parcalar:
        baslar.append(round(len(pcm) / 2 * 1000 / motor.ornekleme))
        parca_pcm, _ = uretici.sayfa_sesi(motor, p)
        pcm += parca_pcm
    dosya = uretici.yaz(bytes(pcm), motor.ornekleme, yol)
    json_yaz({"dosya": dosya.name, "sure_ms": round(len(pcm) / 2 * 1000 / motor.ornekleme), "motor": f"{motor.ad}-{motor.ses}",
              "imler": [{"baslik": b, "ms": baslar[i]} for i, b in imler]}, yol.with_suffix(".json"))


# --- tüm hat -------------------------------------------------------------------------------------------------
def calistir(aof: Path, istemci, motor_yap, gemini_acik: bool = True) -> dict:
    """Gelen kutusu → her ünite için eksik adımlar. Kota dolarsa Gemini adımları durur, ses adımları sürer."""
    from .gemini import GeminiHatasi, KotaDoldu
    yeniler, hatalar = gelenleri_al(aof)
    ozet = {"yeni": [str(d.relative_to(aof / "dersler")).replace("\\", "/") for d in yeniler],
            "red": [{"dosya": d, "hata": h} for d, h in hatalar], "hazir": [], "bekleyen": [], "hatalar": [],
            "gemini_istek": 0}
    kota = None
    motor = None
    for dizin in uniteler(aof):
        ad = str(dizin.relative_to(aof / "dersler")).replace("\\", "/")
        u = json_oku(dizin / "unite.json")
        if gemini_acik and kota is None:
            try:
                anlatim_yap(dizin, u, istemci)
                hazirlik_yap(dizin, u, istemci)
            except KotaDoldu as hata:
                kota = hata.bekle.isoformat(timespec="minutes")
            except (GeminiHatasi, unite_mod.KitapHatasi) as hata:
                ozet["hatalar"].append({"unite": ad, "hata": str(hata)[:300]})
        eksik_ses = (not (dizin / "ses" / "ozet.json").exists() and u["ozet"]) or \
                    (anlatim_tamam_mi(dizin, u) and not (dizin / "ses" / "anlatim.json").exists())
        if eksik_ses:
            motor = motor or motor_yap()
            yeni = ses_yap(dizin, u, motor)
            if "anlatim" in yeni:
                ozet["hazir"].append(ad)
        tamam = anlatim_tamam_mi(dizin, u) and (dizin / "hazirlik.json").exists() and \
            (dizin / "ses" / "anlatim.json").exists()
        if not tamam:
            ozet["bekleyen"].append(ad)
    ozet["gemini_istek"] = getattr(istemci, "istek_sayisi", 0)
    if kota:
        ozet["kota_bekle"] = kota
    return ozet
