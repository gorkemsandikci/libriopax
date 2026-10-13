"""Uçtan uca: EPUB → sayfalar → (sahte motorla) ses + cümle zamanları; devam etme; PDF örneği (venv'de)."""
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from libriopax import donustur
from libriopax.ses import uretici
from libriopax.ses.motor import SahteMotor
from tests.test_epub import epub_yap

KOK = Path(__file__).resolve().parent.parent
try:
    import pypdfium2  # noqa: F401
    PDF_VAR = True
except ImportError:
    PDF_VAR = False


class Donustur(unittest.TestCase):
    def setUp(self):
        self.dizin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dizin, ignore_errors=True)
        self.kitap = self.dizin / "k.epub"
        paragraf = "<p>" + " ".join(["Kısa bir cümle daha yazıldı."] * 20) + "</p>"
        epub_yap(self.kitap, {"a.xhtml": "<h1>Bir</h1>" + paragraf * 4, "b.xhtml": "<h1>İki</h1><p>Dr. Ali 1923'te geldi.</p>"})

    def _calistir(self, *arg):
        cikti, hata = io.StringIO(), io.StringIO()
        with redirect_stdout(cikti), redirect_stderr(hata):
            kod = donustur.main([str(self.kitap), "--motor", "sahte", "--veri", str(self.dizin / "veri"), "--json", *arg])
        return kod, json.loads(cikti.getvalue().strip().splitlines()[-1])

    def test_uctan_uca_ve_devam(self):
        kod, ozet = self._calistir("--sayfalar", "1-2")
        self.assertEqual(kod, 0)
        self.assertEqual((ozet["uretilen"], ozet["atlanan"], ozet["basarisiz"]), (2, 0, []))
        ses = self.dizin / "veri" / "kitaplar" / ozet["kimlik"] / "ses" / "sahte-sinus"
        bilgi = json.loads((ses / "0001.json").read_text(encoding="utf-8"))
        kitap = json.loads((ses.parent.parent / "kitap.json").read_text(encoding="utf-8"))
        self.assertEqual(len(bilgi["zamanlar"]), len(kitap["sayfalar"][0]["cumleler"]))
        onceki = 0
        for bas, son in bilgi["zamanlar"]:            # cümle zamanları sıralı ve süre içinde
            self.assertLessEqual(onceki, bas)
            self.assertLess(bas, son)
            onceki = son
        self.assertLessEqual(onceki, bilgi["sure_ms"])
        self.assertFalse(list(ses.glob("*.tmp")))
        # Tekrar: üretilenler atlanır, kalanlar üretilir
        kod, ozet = self._calistir("--bolum-mp3")
        self.assertEqual(ozet["atlanan"], 2)
        self.assertEqual(ozet["tamamlanan"], ozet["sayfa"])
        if uretici.ffmpeg_yolu():
            bolumler = self.dizin / "veri" / "kitaplar" / ozet["kimlik"] / "bolumler" / "sahte-sinus"
            self.assertEqual(sorted(p.name for p in bolumler.glob("*.mp3")), ["001 - Bölüm 1.mp3", "002 - Bölüm 2.mp3"])
            self.assertIn("001 - Bölüm 1.mp3", (bolumler / "kitap.m3u").read_text(encoding="utf-8"))

    def test_okunus_motora_gider_metin_degismez(self):
        dizin, kitap = donustur.kitap_hazirla(self.kitap, self.dizin / "veri")
        motor = SahteMotor()
        son = kitap["sayfalar"][-1]
        donustur.donustur(dizin, kitap, motor, [son["sira"]])
        self.assertIn("Dr. Ali 1923'te geldi.", son["metin"])
        self.assertIn("Doktor Ali bin dokuz yüz yirmi üçte geldi.", motor.metinler)

    def test_desteklenmeyen_dosya(self):
        self.kitap = self.dizin / "k.txt"
        self.kitap.write_text("x", encoding="utf-8")
        kod, ozet = self._calistir()
        self.assertEqual(kod, 1)
        self.assertIn("EPUB ve PDF", ozet["hata"])


@unittest.skipUnless(PDF_VAR and (KOK / "ornekler" / "omer-seyfettin.pdf").exists(),
                     "pypdfium2 ya da örnek PDF yok (araclar/ornek_kitap.py)")
class OrnekPdf(unittest.TestCase):
    def test_gercek_boyutlu_kitap(self):
        from libriopax.metin import bol, pdf
        k = pdf.oku(KOK / "ornekler" / "omer-seyfettin.pdf")
        sayfalar = bol.sayfala(k)
        self.assertEqual(len(k.bolumler), 72)                 # kitap adı + 71 hikâye (yer imlerinden)
        self.assertEqual(k.bolumler[1], "Aleko")
        self.assertGreater(len(sayfalar), 500)
        tum = "\n".join(s.metin for s in sayfalar)
        self.assertNotIn("Ömer Seyfettin — Hikâyeler", tum)   # üst bilgi ayıklandı
        self.assertTrue(sayfalar[1].metin.startswith("Aleko\n\nKüçük Ali, yorgun uykusundan uyanınca kalktı."))
        # Her sayfa fiziksel sayfaya bağlı ve sıralı
        kaynaklar = [s.kaynak_sayfa for s in sayfalar]
        self.assertEqual(kaynaklar, sorted(kaynaklar))


if __name__ == "__main__":
    unittest.main()
