"""AÖF sekmesi: ünite ayrıştırma (sentetik sayfa satırları), Gemini istemcisinin kota/yedek davranışı (sahte HTTP),
kaldığı yerden süren hat (sahte Gemini + sahte motor) ve sunucu sayfaları."""
import io
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from libriopax import sunucu
from libriopax.aof import anlat, unite
from libriopax.aof.gemini import GeminiHatasi, Istemci, KotaDoldu
from libriopax.ses import uretici
from libriopax.ses.motor import SahteMotor

UST = "1. Ünite - Deneme Kavramları {}"
DERS = "{} Deneme Dersi"
SAYFALAR = [
    ["1", "Amaçlarımız", "Bu üniteyi tamamladıktan sonra;", "Birinci kavramı açıklayabilecek,",
     "İkinci kavramı tanımlayabilecek bilgi ve beceriler kazanabileceksiniz.", "Anahtar Kavramlar", "• Birinci", "• İkinci",
     "İçindekiler", "• BİRİNCİ KONU", "• İKİNCİ UZUN", "KONU BAŞLIĞI", "DENEME DERSİ"],
    [DERS.format(2), "BİRİNCİ KONU", "Birinci konu çok önemli bir konudur ve burada uzun uzun anlatılmaktadır, öyle ki.",
     "Şekil 1.1", "1"],
    [UST.format(3), "İKİNCİ UZUN KONU BAŞLIĞI", "İkinci konu da en az birincisi kadar önemlidir ve uzun anlatılır, tamam.",
     "ALT BAŞLIK BURADA", "Alt başlığın metni de gövdede kalır ve ayrı bölüm açmaz, çünkü içindekilerde yok."],
    [DERS.format(4), "Özet", "Birinci kavramı açıklamak.", "Birinci konu önemlidir.", "1"],
    [UST.format(5), "Kendimizi Sınayalım", "1. Hangisi birinci konu", "hakkında doğrudur?", "a. Önemlidir", "b. Önemsizdir",
     "c. Yoktur", "d. İkincidir", "e. Hiçbiri", "2. İkinci soru nedir?", "a. Bir", "b. İki", "c. Üç", "d. Dört",
     "e. Beş ve", "devamı"],
    [DERS.format(6), "Okuma Parçası", "Kısa bir okuma parçası.", "Kendimizi Sınayalım Yanıt Anahtarı Sıra Sizde Yanıt Anahtarı",
     "1. a Yanıtınız yanlışsa birinci konuyu", "gözden geçirin.", "2 b Yanıtınız yanlışsa ikinciyi.", "Sıra Sizde 1",
     "Birinci etkinliğin yanıtı budur."],
    [UST.format(7), "Yararlanılan Kaynaklar", "Yazar A. (2020) Kitap."],
]


class Ayristirma(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.u = unite.sayfalardan(SAYFALAR, "DNM101U_Unite1_Kitap")

    def test_kimlik(self):
        self.assertEqual((self.u["ders_kodu"], self.u["ders_adi"], self.u["unite_no"], self.u["unite_adi"]),
                         ("DNM101U", "Deneme Dersi", 1, "Deneme Kavramları"))

    def test_ilk_sayfa(self):
        self.assertEqual(self.u["amaclar"], ["Birinci kavramı açıklayabilecek,", "İkinci kavramı tanımlayabilecek"])
        self.assertEqual(self.u["kavramlar"], ["Birinci", "İkinci"])

    def test_bolumler_icindekilerden(self):
        self.assertEqual([b["baslik"] for b in self.u["bolumler"]], ["BİRİNCİ KONU", "İKİNCİ UZUN KONU BAŞLIĞI"])
        self.assertIn("ALT BAŞLIK BURADA", self.u["bolumler"][1]["metin"])
        govde = " ".join(b["metin"] for b in self.u["bolumler"])
        self.assertNotIn("Deneme Dersi", govde)          # üst bilgi ayıklandı
        self.assertNotIn("\n1\n", "\n" + govde + "\n")   # tek rakamlı simge satırı

    def test_sorular_ve_yanit_anahtari(self):
        s = self.u["sorular"]
        self.assertEqual(len(s), 2)
        self.assertEqual(s[0]["soru"], "Hangisi birinci konu hakkında doğrudur?")
        self.assertEqual((s[0]["dogru"], s[1]["dogru"]), (0, 1))
        self.assertEqual(s[1]["secenekler"][4], "Beş ve devamı")
        self.assertEqual(s[0]["aciklama"], "Yanıtınız yanlışsa birinci konuyu gözden geçirin.")

    def test_ozet_okuma_sira_sizde(self):
        self.assertEqual(self.u["ozet"], ["Birinci kavramı açıklamak.", "Birinci konu önemlidir."])
        self.assertEqual(self.u["okuma"], ["Kısa bir okuma parçası."])
        self.assertEqual(self.u["sira_sizde"], [{"no": 1, "yanit": "Birinci etkinliğin yanıtı budur."}])

    def test_sablon_disi(self):
        with self.assertRaises(unite.KitapHatasi):
            unite.sayfalardan([["Sıradan bir kitap sayfası " * 10]] * 3, "kitap")


def _http_hatasi(kod: int, govde: str = "{}"):
    return urllib.error.HTTPError("u", kod, "x", {}, io.BytesIO(govde.encode()))


class GeminiIstemci(unittest.TestCase):
    def setUp(self):
        self.dizin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dizin, True)
        self.cagrilar = []
        self.yanitlar = {}
        import os
        self.eski = {k: os.environ.get(k) for k in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_YEDEK_MODELLER")}
        os.environ.update(GEMINI_API_KEY="deneme", GEMINI_MODEL="ana", GEMINI_YEDEK_MODELLER="yedek")
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in self.eski.items()])

    def istemci(self):
        def cagir(model, govde, zaman_asimi):
            self.cagrilar.append(model)
            y = self.yanitlar[model].pop(0) if isinstance(self.yanitlar[model], list) else self.yanitlar[model]
            if isinstance(y, Exception):
                raise y
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(y)}]}}]}
        return Istemci(self.dizin / "kota.json", aralik_sn=0, bekle=lambda sn: None, cagir=cagir)

    def test_yogun_model_atlanir(self):
        self.yanitlar = {"ana": _http_hatasi(503), "yedek": {"tamam": 1}}
        i = self.istemci()
        self.assertEqual(i.json_uret("x", {}), {"tamam": 1})
        self.assertEqual(self.cagrilar, ["ana", "ana", "ana", "yedek"])   # iki bekleyip yeniden, sonra yedek
        self.cagrilar.clear()
        i.json_uret("x", {})
        self.assertEqual(self.cagrilar, ["yedek"])                       # 30 dk boyunca yoğun model denenmez

    def test_gunluk_kota_dolunca_durur_ve_hatirlar(self):
        self.yanitlar = {"ana": _http_hatasi(429, '{"quotaId": "GenerateRequestsPerDay"}'),
                         "yedek": _http_hatasi(429, '{"quotaId": "GenerateRequestsPerDay"}')}
        i = self.istemci()
        with self.assertRaises(KotaDoldu) as h:
            i.json_uret("x", {})
        self.assertGreater(h.exception.bekle, datetime.now(timezone.utc))
        self.cagrilar.clear()
        with self.assertRaises(KotaDoldu):
            self.istemci().json_uret("x", {})                           # yeni koşu: istek atmadan çıkar
        self.assertEqual(self.cagrilar, [])

    def test_dakika_siniri_bir_kez_beklenir(self):
        self.yanitlar = {"ana": [_http_hatasi(429, '{"retryDelay": "7s"}'), {"tamam": 2}], "yedek": {}}
        bekleme = []
        i = self.istemci()
        i.bekle = bekleme.append
        self.assertEqual(i.json_uret("x", {}), {"tamam": 2})
        self.assertEqual(bekleme, [9])

    def test_kalici_hata_yukari_cikar(self):
        self.yanitlar = {"ana": _http_hatasi(400), "yedek": {}}
        with self.assertRaises(GeminiHatasi):
            self.istemci().json_uret("x", {})


class SahteGemini:
    """Anlatım ve hazırlık şemasına uyan sabit yanıtlar; `kota_sonra` istekten sonra KotaDoldu."""
    def __init__(self, kota_sonra=None):
        self.istek_sayisi = 0
        self.kota_sonra = kota_sonra

    def json_uret(self, istem, sema, sistem="", **_):
        if self.kota_sonra is not None and self.istek_sayisi >= self.kota_sonra:
            raise KotaDoldu("dolu", datetime(2030, 1, 1, tzinfo=timezone.utc))
        self.istek_sayisi += 1
        if "kisimlar" in sema["properties"]:
            return {"kisimlar": [{"baslik": "Kısım", "paragraflar": ["Bir anlatım cümlesi. İkinci cümle."]}],
                    "dikkat": ["Önemli nokta."]}
        return {"kavramlar": [{"terim": "Birinci", "aciklama": "Açıklama."}],
                "sorular": [{"soru": "Geçerli?", "secenekler": list("abcde"), "dogru": 2, "aciklama": "Çünkü."},
                            {"soru": "Geçersiz", "secenekler": ["a", "a", "b", "c", "d"], "dogru": 0, "aciklama": ""}],
                "sira_sizde": [{"no": 1, "soru": "Etkinlik sorusu?"}, {"no": 9, "soru": "olmayan"}]}


def _unite_koy(aof: Path) -> Path:
    u = unite.sayfalardan(SAYFALAR, "DNM101U_Unite1")
    dizin = aof / "dersler" / "DNM101U" / "01"
    anlat.json_yaz(u, dizin / "unite.json")
    (dizin / "kaynak.pdf").write_bytes(b"%PDF-1.4 deneme")
    return dizin


@unittest.skipUnless(uretici.ffmpeg_yolu(), "ffmpeg yok")
class Hat(unittest.TestCase):
    def setUp(self):
        self.aof = Path(tempfile.mkdtemp()) / "aof"
        self.addCleanup(shutil.rmtree, self.aof.parent, True)
        self.dizin = _unite_koy(self.aof)

    def test_kota_dolunca_kaldigi_yerden_surer(self):
        ozet = anlat.calistir(self.aof, SahteGemini(kota_sonra=1), SahteMotor)
        self.assertEqual(ozet["kota_bekle"], "2030-01-01T00:00+00:00")
        self.assertTrue((self.dizin / "anlatim" / "01.json").exists())
        self.assertFalse((self.dizin / "anlatim" / "02.json").exists())
        self.assertTrue((self.dizin / "ses" / "ozet.mp3").exists())       # özet sesi Gemini'yi beklemez
        self.assertFalse((self.dizin / "ses" / "anlatim.json").exists())
        self.assertEqual(ozet["bekleyen"], ["DNM101U/01"])

        g = SahteGemini()
        ozet = anlat.calistir(self.aof, g, SahteMotor)
        self.assertEqual(g.istek_sayisi, 2)                               # sadece eksik bölüm + hazırlık
        self.assertEqual((ozet["hazir"], ozet["bekleyen"]), (["DNM101U/01"], []))
        h = anlat.json_oku(self.dizin / "hazirlik.json")
        self.assertEqual(len(h["sorular"]), 1)                            # tekrarlı seçenekli soru atıldı
        self.assertEqual(h["sira_sizde"], [{"no": 1, "soru": "Etkinlik sorusu?"}])
        ses = anlat.json_oku(self.dizin / "ses" / "anlatim.json")
        self.assertEqual([i["baslik"] for i in ses["imler"]], ["Kısım", "Kısım", "Sınavda dikkat"])
        self.assertEqual(anlat.calistir(self.aof, g, SahteMotor)["gemini_istek"], 2)   # yapılacak iş kalmadı

    def test_uzun_bolum_parca_parca(self):
        metin = "\n".join(["GİRİŞ BAŞLIĞI"] + ["Gövde satırı burada uzunca bir cümle."] * 30 +
                          ["İKİNCİ ALT BAŞLIK"] + ["Başka bir satır da burada yer alıyor."] * 30)
        parcalar = anlat.parcalara_bol(metin, 1200)
        self.assertGreater(len(parcalar), 1)
        self.assertTrue(all(len(p) <= 1200 for p in parcalar))
        self.assertEqual("\n".join(parcalar).count("Gövde satırı"), 30)        # metin kaybolmaz
        self.assertTrue(any(p.startswith("İKİNCİ ALT BAŞLIK") for p in parcalar))   # alt başlıktan bölünür

        u = anlat.json_oku(self.dizin / "unite.json")
        u["bolumler"][0]["metin"] = metin
        anlat.json_yaz(u, self.dizin / "unite.json")
        eski, anlat.PARCA_SINIRI = anlat.PARCA_SINIRI, 1200
        self.addCleanup(setattr, anlat, "PARCA_SINIRI", eski)
        anlat.calistir(self.aof, SahteGemini(kota_sonra=1), SahteMotor)
        self.assertTrue((self.dizin / "anlatim" / "01-1.json").exists())     # yarım bölümün parçaları saklanır
        self.assertFalse((self.dizin / "anlatim" / "01.json").exists())
        anlat.calistir(self.aof, SahteGemini(), SahteMotor)
        bolum = anlat.json_oku(self.dizin / "anlatim" / "01.json")
        self.assertEqual(len(bolum["kisimlar"]), len(parcalar))
        self.assertEqual(list((self.dizin / "anlatim").glob("01-*.json")), [])

    def test_gelen_kutusu_hatali_pdf(self):
        (self.aof / "gelen").mkdir(parents=True)
        (self.aof / "gelen" / "bozuk.pdf").write_bytes(b"bu bir pdf degil")
        ozet = anlat.calistir(self.aof, SahteGemini(), SahteMotor, gemini_acik=False)
        self.assertEqual([r["dosya"] for r in ozet["red"]], ["bozuk.pdf"])
        self.assertTrue((self.aof / "gelen" / "hatali" / "bozuk.pdf").exists())


@unittest.skipUnless(uretici.ffmpeg_yolu(), "ffmpeg yok")
class Sayfalar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.veri = Path(tempfile.mkdtemp())
        aof = cls.veri / "aof"
        _unite_koy(aof)
        anlat.calistir(aof, SahteGemini(), SahteMotor)
        cls.s = sunucu.sunucu(cls.veri, port=0)
        cls.taban = f"http://127.0.0.1:{cls.s.server_address[1]}/"
        threading.Thread(target=cls.s.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.s.shutdown()
        cls.s.server_close()
        shutil.rmtree(cls.veri, ignore_errors=True)

    def al(self, yol):
        with urllib.request.urlopen(self.taban + yol) as y:
            return y.status, y.headers.get("Content-Type"), y.read()

    def test_sekmeler(self):
        _, _, ana = self.al("")
        self.assertIn('href="aof/"', ana.decode())
        _, _, liste = self.al("aof/")
        liste = liste.decode()
        self.assertIn('href="../"', liste)
        self.assertIn('href="DNM101U/01/"', liste)
        self.assertIn("✓", liste)

    def test_unite_sayfasi(self):
        _, tur, govde = self.al("aof/DNM101U/01/")
        govde = govde.decode()
        self.assertTrue(tur.startswith("text/html"))
        for parca in ("Deneme Kavramları", "Bir anlatım cümlesi.", "Sınavda dikkat", 'data-dogru="0"', "Geçerli?",
                      "Etkinlik sorusu?", 'src="anlatim.mp3"', 'src="ozet.mp3"'):
            self.assertIn(parca, govde)

    def test_dosyalar(self):
        self.assertEqual(self.al("aof/DNM101U/01/anlatim.mp3")[1], "audio/mpeg")
        self.assertEqual(self.al("aof/DNM101U/01/kaynak.pdf")[1], "application/pdf")

    def test_gecersiz_yollar(self):
        for yol in ("aof/../01/", "aof/DNM101U/1/", "aof/DNM101U/01/unite.json", "aof/DNM101U/01/baska.mp3",
                    "aof/YOK/01/"):
            with self.subTest(yol=yol), self.assertRaises(urllib.error.HTTPError) as h:
                self.al(yol)
            self.assertEqual(h.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
