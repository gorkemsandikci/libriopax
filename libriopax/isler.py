"""İş kuyruğu: sunucudan yüklenen kitap/AÖF ünitesi → (onay) → sıra → tek işçi → hazır.

    veri/isler/<id>.json   {"id", "eposta", "tur": "kitap"|"aof", "dosya_adi", "dosya", "secenek": {"motor", "ses"},
                            "durum": "onay"|"sirada"|"isleniyor"|"tamam"|"hata"|"red"|"iptal",
                            "olusturma", "guncelleme", "ilerleme": {"yuzde", "yazi"}, "sonuc": {"yol", ...}, "hata",
                            "bekle": ISO (kota dolunca bu zamana kadar sırada bekler)}

Durum geçişleri: yeni iş → "onay" (yönetici onaylayana kadar) ya da otomatik onaylı kullanıcıda doğrudan "sirada".
Onay: sunucunun yönetim sayfası ya da G-Maestro'nun Telegram düğmesi (`python -m libriopax.yonetim`). İşçi aynı anda
tek iş çalıştırır; dönüştürme ayrı süreçte (çökme sunucuyu düşürmez). Sunucu yeniden başlarsa "isleniyor" kalan iş
"sirada"ya döner ve kaldığı yerden sürer (dönüştürücüler zaten kaldığı yerden devam eder).
Sahibin klasör gelen kutuları (veri/gelen, veri/aof/gelen) da işçi tarafından onaysız işe çevrilir.
"""
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import gizli, hesap

KOK = Path(__file__).resolve().parent.parent
TURLER = {"kitap": (".epub", ".pdf"), "aof": (".pdf",)}
IMZA = {".pdf": b"%PDF-", ".epub": b"PK\x03\x04"}
AZAMI_BOYUT = 300 * 1024 * 1024
BEKLEYEN_SINIRI = 5                    # yönetici olmayan kullanıcının aynı anda onay/sırada işi
SESLER = ("fahrettin", "fettah", "dfki")
TAVAN_SN = 6 * 3600
AOF_DENEME = 4                         # geçici Gemini hatasında en fazla deneme (ilk + 3)
_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_kilit = threading.RLock()
log = logging.getLogger("libriopax.isler")


class IsHatasi(Exception):
    """Kullanıcıya gösterilebilir hata."""


def _dizin(veri: Path) -> Path:
    return Path(veri) / "isler"


def _simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


def oku(veri: Path, is_id: str):
    if not _ID.match(is_id or ""):
        return None
    try:
        return json.loads((_dizin(veri) / f"{is_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _yaz(veri: Path, is_: dict) -> None:
    is_["guncelleme"] = _simdi()
    yol = _dizin(veri) / f"{is_['id']}.json"
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_name(yol.name + ".tmp")
    gecici.write_text(json.dumps(is_, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(gecici, yol)


def listele(veri: Path, eposta: str = None) -> list:
    """En yeni önce; eposta verilirse sadece o kullanıcının işleri."""
    sonuc = []
    for yol in _dizin(veri).glob("*.json"):
        try:
            is_ = json.loads(yol.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if eposta is None or is_.get("eposta") == eposta:
            sonuc.append(is_)
    return sorted(sonuc, key=lambda x: x["id"], reverse=True)


def _guvenli_ad(ad: str, uzanti: str) -> str:
    kok_ad = re.sub(r"[^\w.\- ]+", "_", Path(ad or "").stem, flags=re.UNICODE).strip(" ._")[:80] or "dosya"
    return kok_ad + uzanti


def gemini_bugun(veri: Path, eposta: str) -> int:
    """Kullanıcının bugün paylaşılan anahtarla açtığı AÖF işi (red/iptal hariç)."""
    gun = datetime.now().strftime("%Y%m%d")
    return sum(1 for x in listele(veri, eposta)
               if x["tur"] == "aof" and x["id"].startswith(gun) and x["durum"] not in ("red", "iptal")
               and not x.get("kendi_anahtar"))


def yeni(veri: Path, eposta: str, tur: str, dosya_adi: str, akis, boyut: int, secenek: dict) -> dict:
    """Yüklenen dosyayı kullanıcının klasörüne yazar ve işi açar. akis: read(n) olan nesne, boyut: Content-Length."""
    k = hesap.bul(veri, eposta)
    if not hesap.onayli_mi(k):
        raise IsHatasi("Hesabın henüz onaylanmadı.")
    if tur not in TURLER:
        raise IsHatasi("Geçersiz tür.")
    uzanti = Path(dosya_adi or "").suffix.lower()
    if uzanti not in TURLER[tur]:
        raise IsHatasi("Bu tür için sadece " + ", ".join(u.upper().lstrip(".") for u in TURLER[tur]) + " yüklenebilir.")
    if not (0 < boyut <= AZAMI_BOYUT):
        raise IsHatasi(f"Dosya boyutu 1 bayt ile {AZAMI_BOYUT // 1024 // 1024} MB arasında olmalı.")
    motor = secenek.get("motor") or "piper"
    if motor not in k.get("motorlar", []):
        raise IsHatasi("Bu ses motoru hesabına açık değil.")
    if motor not in hesap.HAZIR_MOTORLAR:
        raise IsHatasi(f"{hesap.MOTORLAR.get(motor, motor)} henüz hazır değil.")
    ses = secenek.get("ses") or "fahrettin"
    if ses not in SESLER:
        raise IsHatasi("Geçersiz ses.")
    kendi = tur == "aof" and gizli.anahtar_var(veri, hesap.kid(eposta))
    with _kilit:
        if not k.get("yonetici"):
            acik = [x for x in listele(veri, eposta) if x["durum"] in ("onay", "sirada", "isleniyor")]
            if len(acik) >= BEKLEYEN_SINIRI:
                raise IsHatasi(f"Aynı anda en fazla {BEKLEYEN_SINIRI} bekleyen işin olabilir.")
            sinir = k.get("gemini_gunluk")
            if tur == "aof" and not kendi and sinir is not None and gemini_bugun(veri, eposta) >= sinir:
                raise IsHatasi(f"Bugünkü AÖF sınırın doldu ({sinir}). Yarın tekrar dene ya da Ayarlar'dan kendi "
                               "Gemini anahtarını ekle.")
        is_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    hedef = hesap.kok(veri, eposta) / "yuklenen" / f"{is_id}{uzanti}"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(hedef.name + ".tmp")
    kalan, ilk = boyut, b""
    try:
        with open(gecici, "wb") as f:
            while kalan > 0:
                parca = akis.read(min(1 << 20, kalan))
                if not parca:
                    raise IsHatasi("Yükleme yarıda kesildi.")
                if not ilk:
                    ilk = parca[:8]
                f.write(parca)
                kalan -= len(parca)
        if not ilk.startswith(IMZA[uzanti]):
            raise IsHatasi(f"Dosya gerçek bir {uzanti.upper().lstrip('.')} değil.")
        os.replace(gecici, hedef)
    except BaseException:
        gecici.unlink(missing_ok=True)
        raise
    is_ = {"id": is_id, "eposta": eposta, "tur": tur, "dosya_adi": _guvenli_ad(dosya_adi, uzanti),
           "dosya": str(hedef.relative_to(veri)).replace("\\", "/"), "boyut": boyut,
           "secenek": {"motor": motor, "ses": ses}, "kendi_anahtar": kendi,
           "durum": "sirada" if k.get("otomatik_onay") else "onay", "olusturma": _simdi(),
           "ilerleme": {"yuzde": 0, "yazi": ""}}
    _yaz(veri, is_)
    log.info("yeni iş %s (%s, %s)", is_id, tur, is_["durum"])
    return is_


def karar(veri: Path, is_id: str, onay: bool, neden: str = "") -> dict:
    """Yönetici kararı: sadece "onay" durumundaki iş."""
    with _kilit:
        is_ = oku(veri, is_id)
        if is_ is None:
            raise IsHatasi("İş bulunamadı.")
        if is_["durum"] != "onay":
            raise IsHatasi(f"İş onay beklemiyor (durum: {is_['durum']}).")
        is_["durum"] = "sirada" if onay else "red"
        if not onay:
            is_["hata"] = neden.strip()[:200] or "Yönetici reddetti."
        _yaz(veri, is_)
        return is_


def iptal(veri: Path, is_id: str, eposta: str) -> dict:
    with _kilit:
        is_ = oku(veri, is_id)
        if is_ is None or is_["eposta"] != eposta:
            raise IsHatasi("İş bulunamadı.")
        if is_["durum"] not in ("onay", "sirada"):
            raise IsHatasi("Sadece başlamamış iş iptal edilebilir.")
        is_["durum"] = "iptal"
        _yaz(veri, is_)
        return is_


# --- işçi ----------------------------------------------------------------------------------------------------
def _python() -> str:
    exe = Path(sys.executable)
    konsol = exe.with_name("python.exe")          # sunucu pythonw ile çalışır; alt süreç çıktısı için python.exe
    return str(konsol if konsol.exists() else exe)


def _ortam(gemini: str = "") -> dict:
    ortam = {k: v for k, v in os.environ.items() if not k.upper().startswith("GEMINI_")}
    ortam["PYTHONIOENCODING"] = "utf-8"
    if gemini:
        ortam["GEMINI_API_KEY"] = gemini
    return ortam


class Isci:
    """Tek iş parçacığı: gelen kutularını tarar, sıradaki en eski işi çalıştırır."""

    def __init__(self, veri: Path, aralik_sn: float = 20, motor: str = None):
        self.veri = Path(veri)
        self.aralik_sn = aralik_sn
        self.motor = motor                       # testlerde "sahte"
        self._dur = threading.Event()
        self._uyandir = threading.Event()
        self.thread = None

    def baslat(self):
        for is_ in listele(self.veri):           # yarıda kalan: sıraya geri
            if is_["durum"] == "isleniyor":
                is_["durum"] = "sirada"
                _yaz(self.veri, is_)
        self.thread = threading.Thread(target=self._dongu, name="libriopax-isci", daemon=True)
        self.thread.start()
        return self

    def durdur(self):
        self._dur.set()
        self._uyandir.set()

    def uyandir(self):
        self._uyandir.set()

    def _dongu(self):
        while not self._dur.is_set():
            try:
                self.gelen_kutulari()
                if self.bir_is():
                    continue
            except Exception:
                log.exception("işçi hatası")
            self._uyandir.wait(self.aralik_sn)
            self._uyandir.clear()

    def gelen_kutulari(self) -> None:
        """Sahibin klasör gelen kutuları (eski akış) → onaysız işler."""
        sahip = hesap.oku(self.veri).get("sahip")
        if not sahip:
            return
        for klasor, tur in ((self.veri / "gelen", "kitap"), (self.veri / "aof" / "gelen", "aof")):
            if not klasor.is_dir():
                continue
            for dosya in sorted(p for p in klasor.iterdir() if p.is_file() and p.suffix.lower() in TURLER[tur]):
                try:
                    if time.time() - dosya.stat().st_mtime < 10:       # kopyalanıyor olabilir
                        continue
                    with open(dosya, "rb") as f:
                        yeni(self.veri, sahip, tur, dosya.name, f, dosya.stat().st_size, {"motor": "piper"})
                    hedef = klasor / "islendi" / dosya.name
                    hedef.parent.mkdir(exist_ok=True)
                    os.replace(dosya, hedef)
                except (IsHatasi, OSError) as hata:
                    log.warning("gelen kutusu %s: %s", dosya.name, hata)
                    (klasor / "hatali").mkdir(exist_ok=True)
                    os.replace(dosya, klasor / "hatali" / dosya.name)

    def bir_is(self) -> bool:
        simdi = datetime.now(timezone.utc).isoformat()
        sirada = [x for x in listele(self.veri) if x["durum"] == "sirada" and (x.get("bekle") or "") <= simdi]
        if not sirada:
            return False
        is_ = min(sirada, key=lambda x: x["id"])
        is_["durum"] = "isleniyor"
        is_["baslangic"] = _simdi()
        _yaz(self.veri, is_)
        try:
            (self._kitap if is_["tur"] == "kitap" else self._aof)(is_)
        except Exception as hata:
            log.exception("iş %s", is_["id"])
            is_["durum"], is_["hata"] = "hata", f"Beklenmeyen hata: {type(hata).__name__}"
        _yaz(self.veri, is_)
        return True

    def _calistir(self, is_: dict, komut: list, ortam: dict, ilerleme=None) -> tuple:
        """(çıkış kodu, son JSON satırı ya da None). stderr satırları `ilerleme(satir)`'a akar."""
        cikti = self.veri / "isler" / f"{is_['id']}.cikti"
        with open(cikti, "w+", encoding="utf-8") as f:
            surec = subprocess.Popen(komut, cwd=str(KOK), env=ortam, stdout=f, stderr=subprocess.PIPE,
                                     creationflags=0x08000000 if os.name == "nt" else 0)
            tampon, son_yazim = b"", 0.0
            bitis = time.time() + TAVAN_SN
            while True:
                parca = surec.stderr.read1(4096) if hasattr(surec.stderr, "read1") else surec.stderr.read(4096)
                if not parca:
                    break
                tampon += parca
                *satirlar, tampon = re.split(rb"[\r\n]", tampon)
                if ilerleme and satirlar and time.time() - son_yazim > 3:
                    for s in satirlar:
                        ilerleme(s.decode("utf-8", "replace"))
                    _yaz(self.veri, is_)
                    son_yazim = time.time()
                if time.time() > bitis or self._dur.is_set():
                    surec.kill()
                    break
            kod = surec.wait()
            surec.stderr.close()
            f.seek(0)
            satir = next((s for s in reversed(f.read().strip().splitlines()) if s.startswith("{")), None)
        cikti.unlink(missing_ok=True)
        try:
            return kod, json.loads(satir) if satir else None
        except ValueError:
            return kod, None

    def _kitap(self, is_: dict) -> None:
        kok = hesap.kok(self.veri, is_["eposta"])
        komut = [_python(), "-m", "libriopax.donustur", str(self.veri / is_["dosya"]), "--veri", str(kok),
                 "--ses", is_["secenek"]["ses"], "--json"] + (["--motor", self.motor] if self.motor else [])

        def ilerleme(s):
            m = re.search(r"🔊 (\d+)/(\d+).*kalan ~(\d+) dk", s)
            if m:
                i, toplam = int(m.group(1)), int(m.group(2))
                is_["ilerleme"] = {"yuzde": round(100 * i / max(toplam, 1)), "yazi": f"{i}/{toplam} sayfa · kalan ~{m.group(3)} dk"}
            elif s.startswith("📖"):
                is_["ilerleme"] = {"yuzde": 1, "yazi": "Metin çıkarıldı, ses başlıyor"}

        is_["ilerleme"] = {"yuzde": 0, "yazi": "Metin çıkarılıyor"}
        kod, ozet = self._calistir(is_, komut, _ortam(), ilerleme)
        if ozet is None:
            is_["durum"], is_["hata"] = "hata", f"Dönüştürücü çıktı vermedi (kod {kod})."
        elif "hata" in ozet:
            is_["durum"], is_["hata"] = "hata", ozet["hata"]
        elif ozet.get("tamamlanan", 0) < ozet.get("sayfa", 0) or ozet.get("basarisiz"):
            is_["durum"] = "hata"
            is_["hata"] = f"{len(ozet.get('basarisiz') or [])} sayfa üretilemedi ({ozet.get('tamamlanan')}/{ozet.get('sayfa')})."
        else:
            is_["durum"] = "tamam"
            is_["ilerleme"] = {"yuzde": 100, "yazi": ""}
            is_["sonuc"] = {"yol": f"k/{ozet['kimlik']}/", "baslik": ozet.get("kitap"), "ses_sn": ozet.get("ses_sn")}

    def _aof(self, is_: dict) -> None:
        kok = hesap.kok(self.veri, is_["eposta"])
        kapsam = hesap.kid(is_["eposta"]) if is_.get("kendi_anahtar") else "ortak"
        try:
            anahtar = gizli.anahtar_oku(self.veri, kapsam)
        except gizli.GizliHatasi:
            anahtar = ""
        if not anahtar:
            is_["durum"], is_["hata"] = "hata", "Gemini anahtarı kayıtlı değil (yönetici: python -m libriopax.yonetim gemini-anahtar)."
            return
        if not is_.get("unite"):                 # ilk koşu: dosyayı kullanıcının AÖF gelen kutusuna (adıyla) koy
            gelen = kok / "aof" / "gelen"
            gelen.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.veri / is_["dosya"], gelen / is_["dosya_adi"])
        kota = self.veri / "gizli" / f"kota-{kapsam}.json"
        komut = [_python(), "-m", "libriopax.aof", "--veri", str(kok), "--kota", str(kota), "--ses",
                 is_["secenek"]["ses"], "--json"] + (["--motor", self.motor] if self.motor else [])
        is_["ilerleme"] = {"yuzde": 10, "yazi": "Gemini anlatımı hazırlanıyor"}
        _yaz(self.veri, is_)
        kod, ozet = self._calistir(is_, komut, _ortam(anahtar))
        if ozet is None:
            is_["durum"], is_["hata"] = "hata", f"AÖF işleyici çıktı vermedi (kod {kod})."
            return
        if ozet.get("red"):
            is_["durum"], is_["hata"] = "hata", ozet["red"][0]["hata"]
            return
        if ozet.get("yeni") and not is_.get("unite"):
            is_["unite"] = ozet["yeni"][0]
        unite = is_.get("unite")
        dizin = kok / "aof" / "dersler" / unite if unite else None
        if dizin and (dizin / "ses" / "anlatim.json").exists() and (dizin / "hazirlik.json").exists():
            is_["durum"] = "tamam"
            is_["ilerleme"] = {"yuzde": 100, "yazi": ""}
            is_["sonuc"] = {"yol": f"aof/{unite}/"}
        elif ozet.get("kota_bekle"):
            is_["durum"], is_["bekle"] = "sirada", ozet["kota_bekle"]
            is_["ilerleme"] = {"yuzde": 50, "yazi": f"Gemini kotası doldu; {ozet['kota_bekle'][11:16]} UTC sonrası sürer"}
        elif ozet.get("hatalar"):                # çoğunlukla Gemini'nin geçici hatası: 30 dk sonra yeniden
            is_["deneme"] = is_.get("deneme", 0) + 1
            if is_["deneme"] < AOF_DENEME:
                sonra = datetime.fromtimestamp(time.time() + 1800, timezone.utc)
                is_["durum"], is_["bekle"] = "sirada", sonra.isoformat()
                is_["ilerleme"] = {"yuzde": 30, "yazi": f"Geçici hata; {sonra:%H:%M} UTC'de yeniden denenecek"}
            else:
                is_["durum"], is_["hata"] = "hata", ozet["hatalar"][0]["hata"][:200]
        else:
            is_["durum"], is_["hata"] = "hata", "Ünite tamamlanamadı."
