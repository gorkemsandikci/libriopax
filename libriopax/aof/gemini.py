"""Gemini API istemcisi (stdlib) + ücretsiz katman kotasına uyan hız sınırı.

Anahtar ortam değişkeninden: GEMINI_API_KEY (Google AI Studio → Get API key). Model: GEMINI_MODEL (varsayılan
gemini-flash-latest), kotası dolunca GEMINI_YEDEK_MODELLER (virgüllü; varsayılan gemini-flash-lite-latest).

Hız sınırı: istekler arasında en az ARALIK_SN; kota durumu veri/aof/kota.json'da tutulur. Bütün modeller 429 verince
`KotaDoldu` atılır ve "bekle" zamanı yazılır: o zamana kadar yeni koşular istek atmadan çıkar, iş kaldığı yerden sürer.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ADRES = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VARSAYILAN_MODEL = "gemini-flash-latest"
VARSAYILAN_YEDEKLER = ("gemini-flash-lite-latest",)   # 503/zaman aşımı/429'da sırayla
ARALIK_SN = 15                  # ücretsiz katmanın dakika sınırının altında kalmak için
GECICI = (500, 502, 503, 504)
BEKLE_SN = (20, 60)
YOGUN_DK = 30                   # 503/zaman aşımı veren model bu kadar atlanır
DAKIKA_BEKLE = 65               # dakika sınırı (429, gün sınırı değil): bir kez bekleyip yeniden


class GeminiHatasi(RuntimeError):
    pass


class KotaDoldu(GeminiHatasi):
    def __init__(self, mesaj: str, bekle: datetime):
        super().__init__(mesaj)
        self.bekle = bekle


def anahtar() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip()


def modeller() -> list:
    ana = os.environ.get("GEMINI_MODEL", "").strip() or VARSAYILAN_MODEL
    yedek = os.environ.get("GEMINI_YEDEK_MODELLER", "").strip()
    yedekler = [m.strip() for m in yedek.split(",")] if yedek else list(VARSAYILAN_YEDEKLER)
    return list(dict.fromkeys(m for m in [ana, *yedekler] if m))


def _gun_sonu() -> datetime:
    """Ücretsiz katman günlük kotası Pasifik gece yarısı yenilenir (≈ 08:00 UTC; yaz saatinde 07:00)."""
    simdi = datetime.now(timezone.utc)
    yenilenme = simdi.replace(hour=8, minute=5, second=0, microsecond=0)
    return yenilenme if yenilenme > simdi else yenilenme + timedelta(days=1)


class Istemci:
    def __init__(self, durum_dosyasi: Path, aralik_sn: float = ARALIK_SN, bekle=time.sleep, cagir=None):
        self.durum_dosyasi = Path(durum_dosyasi)
        self.aralik_sn = aralik_sn
        self.bekle = bekle
        self._cagir = cagir or self._http
        self.istek_sayisi = 0

    # --- kota durumu ---------------------------------------------------------------------------------------
    def durum(self) -> dict:
        try:
            return json.loads(self.durum_dosyasi.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _durum_yaz(self, d: dict) -> None:
        self.durum_dosyasi.parent.mkdir(parents=True, exist_ok=True)
        gecici = self.durum_dosyasi.with_name(self.durum_dosyasi.name + ".tmp")
        gecici.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(gecici, self.durum_dosyasi)

    def bekleme(self):
        """Kota beklemesi sürüyorsa bitiş zamanı (UTC), yoksa None."""
        deger = self.durum().get("bekle")
        if not deger:
            return None
        zaman = datetime.fromisoformat(deger)
        return zaman if zaman > datetime.now(timezone.utc) else None

    def _atlanacaklar(self) -> dict:
        """{model: {"kadar", "kota"}} — süresi dolmamış atlamalar (yoğun model ya da günlük kotası dolan model)."""
        simdi = datetime.now(timezone.utc)
        return {m: a for m, a in (self.durum().get("atla") or {}).items() if datetime.fromisoformat(a["kadar"]) > simdi}

    def _atla(self, model: str, kadar: datetime, kota: bool = False) -> None:
        d = self.durum()
        d["atla"] = {**self._atlanacaklar(), model: {"kadar": kadar.isoformat(), "kota": kota}}
        self._durum_yaz(d)

    # --- istek ---------------------------------------------------------------------------------------------
    def _http(self, model: str, govde: dict, zaman_asimi: float) -> dict:
        istek = urllib.request.Request(ADRES.format(model=model), data=json.dumps(govde).encode("utf-8"),
                                       headers={"Content-Type": "application/json", "x-goog-api-key": anahtar()})
        with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:
            return json.load(yanit)

    def _aralik(self) -> None:
        son = self.durum().get("son_istek")
        if son:
            gecen = time.time() - son
            if gecen < self.aralik_sn:
                self.bekle(self.aralik_sn - gecen)

    def json_uret(self, istem: str, sema: dict, sistem: str = "", sicaklik: float = 0.3,
                  zaman_asimi: float = 240) -> dict:
        if not anahtar():
            raise GeminiHatasi("GEMINI_API_KEY tanımlı değil.")
        bitis = self.bekleme()
        if bitis:
            raise KotaDoldu(f"Gemini kotası dolu; {bitis.isoformat(timespec='minutes')} sonrası sürer.", bitis)
        govde = {"contents": [{"role": "user", "parts": [{"text": istem}]}],
                 "generationConfig": {"temperature": sicaklik, "responseMimeType": "application/json",
                                      "responseSchema": sema}}
        if sistem:
            govde["systemInstruction"] = {"parts": [{"text": sistem}]}
        son_hata, kota_disi = None, False
        atla = self._atlanacaklar()
        for model in modeller():
            if model in atla:
                kota_disi = kota_disi or not atla[model]["kota"]
                son_hata = son_hata or GeminiHatasi(f"{model} {'kotası dolu' if atla[model]['kota'] else 'yoğun'}; atlandı")
                continue
            dakika_beklendi = False
            deneme = 0
            while True:
                self._aralik()
                d = self.durum()
                d["son_istek"] = time.time()
                self._durum_yaz(d)
                self.istek_sayisi += 1
                try:
                    veri = self._cagir(model, govde, zaman_asimi)
                except urllib.error.HTTPError as hata:
                    ayrinti = hata.read().decode("utf-8", "replace")[:600]
                    son_hata = GeminiHatasi(f"Gemini HTTP {hata.code} ({model}): {ayrinti[:300]}")
                    if hata.code == 429:
                        # Dakika sınırıysa bir kez bekle; gün sınırıysa (PerDay) sonraki modele geç
                        if not dakika_beklendi and "PerDay" not in ayrinti:
                            dakika_beklendi = True
                            gecikme = re.search(r'"retryDelay":\s*"(\d+)s"', ayrinti)
                            self.bekle(max(int(gecikme.group(1)) + 2 if gecikme else DAKIKA_BEKLE, 5))
                            continue
                        self._atla(model, _gun_sonu(), kota=True)
                        break
                    if hata.code in GECICI:
                        if deneme < len(BEKLE_SN):
                            self.bekle(BEKLE_SN[deneme])
                            deneme += 1
                            continue
                        kota_disi = True
                        self._atla(model, datetime.now(timezone.utc) + timedelta(minutes=YOGUN_DK))
                        break                       # hâlâ yoğun: sonraki model
                    raise son_hata from None
                except (urllib.error.URLError, TimeoutError) as hata:
                    # Zaman aşımı çoğunlukla modelin uzun düşünmesi: aynı modeli beklemek yerine sonraki model
                    son_hata = GeminiHatasi(f"Gemini'ye ulaşılamadı ({model}): {hata}")
                    kota_disi = True
                    self._atla(model, datetime.now(timezone.utc) + timedelta(minutes=YOGUN_DK))
                    break
                return self._ayikla(veri, model)
        if kota_disi:
            raise son_hata
        # Bütün modellerin kotası dolu: en erken yenilenmeye kadar bekle
        bitis = min([datetime.fromisoformat(a["kadar"]) for a in self._atlanacaklar().values() if a["kota"]] or
                    [_gun_sonu()])
        d = self.durum()
        d["bekle"] = bitis.isoformat()
        self._durum_yaz(d)
        raise KotaDoldu(f"Gemini günlük kotası doldu ({son_hata}); {bitis.isoformat(timespec='minutes')} sonrası sürer.",
                        bitis)

    def _ayikla(self, veri: dict, model: str) -> dict:
        d = self.durum()
        gun = datetime.now(timezone.utc).date().isoformat()
        sayac = d.setdefault("gunluk", {})
        if sayac.get("gun") != gun:
            sayac.clear()
            sayac["gun"] = gun
        sayac[model] = sayac.get(model, 0) + 1
        d.pop("bekle", None)
        self._durum_yaz(d)
        try:
            aday = veri["candidates"][0]
            metin = "".join(p.get("text", "") for p in aday["content"]["parts"])
            return json.loads(metin)
        except (KeyError, IndexError, ValueError) as hata:
            sebep = (veri.get("candidates") or [{}])[0].get("finishReason") or veri.get("promptFeedback")
            raise GeminiHatasi(f"Gemini yanıtı okunamadı ({model}: {sebep or hata})") from None
