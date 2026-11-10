"""Çok kullanıcılı arayüz: kayıt defteri, anahtar saklama, iş kuyruğu (sahte motorla uçtan uca), yükleme ve yönetim
uçları, kullanıcılar arası ayrım ve başka siteden gelen istek koruması."""
import io
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from libriopax import gizli, hesap, isler, sunucu, yonetim
from libriopax.ses import uretici
from tests.test_epub import epub_yap

SAHIP, AYSE, YABANCI = "sahip@ornek.com", "ayse@ornek.com", "yabanci@ornek.com"


def _veri(kok: Path) -> Path:
    veri = kok / "veri"
    veri.mkdir(parents=True)
    (veri / "sunucu.json").write_text(json.dumps({"kullanici": SAHIP}), encoding="utf-8")
    return veri


class Hesap(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.kok, True)
        self.veri = _veri(self.kok)

    def test_ilk_acilista_sahip_yonetici_ve_eski_veri_tasinir(self):
        (self.veri / "kitaplar" / "abc").mkdir(parents=True)
        (self.veri / "aof" / "dersler" / "X").mkdir(parents=True)
        hesap.hazirla(self.veri)
        k = hesap.bul(self.veri, SAHIP)
        self.assertTrue(k["yonetici"] and k["otomatik_onay"] and hesap.onayli_mi(k))
        self.assertTrue((hesap.kok(self.veri, SAHIP) / "kitaplar" / "abc").is_dir())
        self.assertTrue((hesap.kok(self.veri, SAHIP) / "aof" / "dersler" / "X").is_dir())
        self.assertFalse((self.veri / "kitaplar").exists())
        hesap.hazirla(self.veri)                                  # ikinci açılış: değişiklik yok
        self.assertEqual(list(hesap.oku(self.veri)["kullanicilar"]), [SAHIP])

    def test_basvuru_ve_yonetici_ayari(self):
        hesap.hazirla(self.veri)
        k = hesap.basvur(self.veri, "Ayse@Ornek.com")
        self.assertEqual((k["durum"], k["motorlar"], k["gemini_gunluk"]), ("bekliyor", ["piper"], 3))
        hesap.guncelle(self.veri, AYSE, durum="onayli", motorlar=["piper", "gemini-tts", "uydurma"], gemini_gunluk="5")
        k = hesap.bul(self.veri, AYSE)
        self.assertEqual((k["durum"], k["motorlar"], k["gemini_gunluk"]), ("onayli", ["piper", "gemini-tts"], 5))
        with self.assertRaises(hesap.HesapHatasi):
            hesap.guncelle(self.veri, SAHIP, durum="reddedildi")    # yönetici kapatılamaz
        with self.assertRaises(hesap.HesapHatasi):
            hesap.basvur(self.veri, "eposta-degil")


@unittest.skipUnless(sys.platform == "win32", "DPAPI sadece Windows")
class Gizli(unittest.TestCase):
    def test_sifreli_saklanir_ve_cozulur(self):
        veri = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, veri, True)
        deger = "TEST-anahtar-0123456789-abcdef"
        gizli.anahtar_yaz(veri, "ortak", deger)
        self.assertNotIn(deger.encode(), (veri / "gizli" / "ortak.dpapi").read_bytes())
        self.assertEqual(gizli.anahtar_oku(veri, "ortak"), deger)
        with self.assertRaises(gizli.GizliHatasi):
            gizli.anahtar_yaz(veri, "../kaçış", deger)
        with self.assertRaises(gizli.GizliHatasi):
            gizli.anahtar_yaz(veri, "ortak", "kısa")

    def test_env_dosyasindan_anahtar_ciktiya_yazilmaz(self):
        veri = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, veri, True)
        env = veri / ".env"
        env.write_text("BASKA=1\nGEMINI_API_KEY=GIZLI-deger-0123456789-xyz\n", encoding="utf-8")
        from contextlib import redirect_stdout, redirect_stderr
        with redirect_stdout(io.StringIO()) as o, redirect_stderr(io.StringIO()) as e:
            yonetim.main(["--veri", str(veri), "gemini-anahtar", "--env", str(env)])
        self.assertNotIn("GIZLI", o.getvalue() + e.getvalue())
        self.assertEqual(gizli.anahtar_oku(veri, "ortak"), "GIZLI-deger-0123456789-xyz")


class Kuyruk(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.kok, True)
        self.veri = _veri(self.kok)
        hesap.hazirla(self.veri)
        hesap.basvur(self.veri, AYSE)
        hesap.guncelle(self.veri, AYSE, durum="onayli")

    def yukle(self, eposta=AYSE, ad="k.pdf", icerik=b"%PDF-1.4 x", tur="kitap", **secenek):
        return isler.yeni(self.veri, eposta, tur, ad, io.BytesIO(icerik), len(icerik), secenek)

    def test_onay_akisi(self):
        is_ = self.yukle()
        self.assertEqual(is_["durum"], "onay")
        self.assertTrue((self.veri / is_["dosya"]).is_file())
        self.assertIn(hesap.kid(AYSE), is_["dosya"])
        self.assertEqual(isler.karar(self.veri, is_["id"], True)["durum"], "sirada")
        with self.assertRaises(isler.IsHatasi):
            isler.karar(self.veri, is_["id"], False)               # artık onay beklemiyor
        sahibin = self.yukle(SAHIP)
        self.assertEqual(sahibin["durum"], "sirada")               # sahip onaysız

    def test_dogrulamalar(self):
        for kw, beklenen in (({"ad": "a.txt"}, "sadece"), ({"icerik": b"<html>"}, "gerçek bir PDF"),
                             ({"motor": "gemini-tts"}, "açık değil"), ({"ses": "x"}, "Geçersiz ses"),
                             ({"tur": "aof", "ad": "a.epub", "icerik": b"PK\x03\x04"}, "sadece PDF")):
            with self.subTest(kw=kw), self.assertRaisesRegex(isler.IsHatasi, beklenen):
                self.yukle(**kw)
        self.assertEqual(list((hesap.kok(self.veri, AYSE) / "yuklenen").glob("*")), [])   # yarım dosya kalmaz
        hesap.basvur(self.veri, YABANCI)
        with self.assertRaisesRegex(isler.IsHatasi, "onaylanmadı"):
            self.yukle(YABANCI)
        hesap.guncelle(self.veri, AYSE, motorlar=["piper", "chatterbox"])
        with self.assertRaisesRegex(isler.IsHatasi, "henüz hazır değil"):
            self.yukle(motor="chatterbox")

    def test_sinirlar(self):
        hesap.guncelle(self.veri, AYSE, gemini_gunluk=1)
        self.yukle(tur="aof")
        with self.assertRaisesRegex(isler.IsHatasi, "AÖF sınırın doldu"):
            self.yukle(tur="aof")
        for _ in range(isler.BEKLEYEN_SINIRI - 1):
            self.yukle()
        with self.assertRaisesRegex(isler.IsHatasi, "en fazla"):
            self.yukle()

    def test_iptal_sadece_kendi_isi(self):
        is_ = self.yukle()
        with self.assertRaises(isler.IsHatasi):
            isler.iptal(self.veri, is_["id"], SAHIP)
        self.assertEqual(isler.iptal(self.veri, is_["id"], AYSE)["durum"], "iptal")


@unittest.skipUnless(uretici.ffmpeg_yolu(), "ffmpeg yok")
class Isci(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.kok, True)
        self.veri = _veri(self.kok)
        hesap.hazirla(self.veri)
        self.epub = self.kok / "k.epub"
        epub_yap(self.epub, {"a.xhtml": "<h1>Bir</h1><p>Kısa bir cümle.</p>"})

    def test_kitap_isi_uctan_uca_ve_gelen_kutusu(self):
        (self.veri / "gelen").mkdir()
        shutil.copy(self.epub, self.veri / "gelen" / "kutudan.epub")
        eski = time.time() - 60
        import os
        os.utime(self.veri / "gelen" / "kutudan.epub", (eski, eski))
        isci = isler.Isci(self.veri, motor="sahte")
        isci.gelen_kutulari()
        self.assertTrue((self.veri / "gelen" / "islendi" / "kutudan.epub").exists())
        self.assertTrue(isci.bir_is())
        is_ = isler.listele(self.veri)[0]
        self.assertEqual(is_["durum"], "tamam", is_.get("hata"))
        self.assertTrue(is_["sonuc"]["yol"].startswith("k/"))
        self.assertEqual(len(sunucu.kitaplar(hesap.kok(self.veri, SAHIP))), 1)
        self.assertFalse(isci.bir_is())                           # sırada iş kalmadı

    def test_aof_anahtarsiz_hata(self):
        is_ = isler.yeni(self.veri, SAHIP, "aof", "u.pdf", io.BytesIO(b"%PDF-1"), 6, {})
        isci = isler.Isci(self.veri, motor="sahte")
        isci.bir_is()
        is_ = isler.oku(self.veri, is_["id"])
        self.assertEqual(is_["durum"], "hata")
        self.assertIn("anahtarı", is_["hata"])

    def test_yarim_kalan_is_siraya_doner(self):
        is_ = isler.yeni(self.veri, SAHIP, "kitap", "k.epub", io.BytesIO(self.epub.read_bytes()), self.epub.stat().st_size, {})
        is_["durum"] = "isleniyor"
        isler._yaz(self.veri, is_)
        isci = isler.Isci(self.veri, motor="sahte", aralik_sn=3600).baslat()
        self.addCleanup(isci.durdur)
        for _ in range(100):
            if isler.oku(self.veri, is_["id"])["durum"] == "tamam":
                break
            time.sleep(0.1)
        self.assertEqual(isler.oku(self.veri, is_["id"])["durum"], "tamam")


class Sunucu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kok = Path(tempfile.mkdtemp())
        cls.veri = _veri(cls.kok)
        cls.s = sunucu.sunucu(cls.veri, port=0)
        cls.taban = f"http://127.0.0.1:{cls.s.server_address[1]}/"
        threading.Thread(target=cls.s.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.s.shutdown()
        cls.s.server_close()
        shutil.rmtree(cls.kok, ignore_errors=True)

    def istek(self, yol, kim=None, govde=None, basliklar=None, yontem=None):
        b = dict(basliklar or {})
        if kim:
            b["Tailscale-User-Login"] = kim
        if govde is not None and "X-Libriopax" not in b:
            b["X-Libriopax"] = "1"
        r = urllib.request.Request(self.taban + yol, data=govde, headers=b, method=yontem)
        try:
            with urllib.request.urlopen(r) as y:
                return y.status, y.read().decode()
        except urllib.error.HTTPError as h:
            return h.code, h.read().decode()

    def test_yabanci_once_bekler_sonra_yonetici_onaylar(self):
        kod, govde = self.istek("", YABANCI)
        self.assertEqual(kod, 403)
        self.assertIn("Onay bekleniyor", govde)
        self.assertEqual(hesap.bul(self.veri, YABANCI)["durum"], "bekliyor")
        kod, _ = self.istek("api/yonetim/kullanici", YABANCI, json.dumps({"eposta": YABANCI, "durum": "onayli"}).encode())
        self.assertEqual(kod, 403)                                   # kendi kendini onaylayamaz
        kod, _ = self.istek("api/yonetim/kullanici", None, json.dumps({"eposta": YABANCI, "durum": "onayli"}).encode())
        self.assertEqual(kod, 200)                                   # başlıksız = bilgisayardaki sahip
        kod, govde = self.istek("yukle/", YABANCI)
        self.assertEqual(kod, 200)
        self.assertNotIn("yonetim/", govde)                          # yönetim sekmesi sadece yöneticide

    def test_yukleme_ve_ayrim(self):
        hesap.basvur(self.veri, AYSE)
        hesap.guncelle(self.veri, AYSE, durum="onayli")
        icerik = b"%PDF-1.4 deneme"
        kod, govde = self.istek("api/yukle?tur=kitap&motor=piper&ses=fettah", AYSE, icerik,
                                {"X-Dosya-Adi": "Benim%20Kitab%C4%B1m.pdf", "Content-Type": "application/octet-stream"})
        self.assertEqual(kod, 200, govde)
        is_id = json.loads(govde)["id"]
        self.assertEqual(json.loads(govde)["durum"], "onay")
        kod, govde = self.istek("api/isler", AYSE)
        self.assertIn("Benim Kitabım.pdf", json.loads(govde)["html"])
        kod, govde = self.istek("api/isler", SAHIP)
        self.assertNotIn("Benim Kitab", json.loads(govde)["html"])   # başkasının işi görünmez
        kod, govde = self.istek("yonetim/", SAHIP)
        self.assertIn(is_id, govde)
        kod, _ = self.istek(f"api/yonetim/is/{is_id}/onayla", AYSE, b"{}")
        self.assertEqual(kod, 403)
        kod, _ = self.istek(f"api/yonetim/is/{is_id}/onayla", SAHIP, b"{}")
        self.assertEqual(kod, 200)
        self.assertEqual(isler.oku(self.veri, is_id)["durum"], "sirada")

    def test_baska_siteden_istek_reddedilir(self):
        icerik = b"%PDF-1.4"
        kod, _ = self.istek("api/yukle?tur=kitap", SAHIP, icerik, {"X-Libriopax": "0", "X-Dosya-Adi": "a.pdf"})
        self.assertEqual(kod, 403)
        kod, _ = self.istek("api/yukle?tur=kitap", SAHIP, icerik, {"Sec-Fetch-Site": "cross-site", "X-Dosya-Adi": "a.pdf"})
        self.assertEqual(kod, 403)

    def test_hatali_yukleme_mesaji(self):
        kod, govde = self.istek("api/yukle?tur=kitap", SAHIP, b"duz metin", {"X-Dosya-Adi": "a.pdf"})
        self.assertEqual(kod, 400)
        self.assertIn("gerçek bir PDF", json.loads(govde)["hata"])

    @unittest.skipUnless(sys.platform == "win32", "DPAPI sadece Windows")
    def test_kendi_anahtari_sayfada_gorunmez(self):
        deger = "KENDI-anahtar-0123456789-abc"
        kod, _ = self.istek("api/anahtar", SAHIP, json.dumps({"anahtar": deger}).encode(), {"Content-Type": "application/json"})
        self.assertEqual(kod, 200)
        for yol in ("ayarlar/", "yukle/", "yonetim/"):
            self.assertNotIn(deger, self.istek(yol, SAHIP)[1])
        self.assertIn("Kayıtlı", self.istek("ayarlar/", SAHIP)[1])
        self.istek("api/anahtar/sil", SAHIP, b"{}")
        self.assertFalse(gizli.anahtar_var(self.veri, hesap.kid(SAHIP)))


if __name__ == "__main__":
    unittest.main()
