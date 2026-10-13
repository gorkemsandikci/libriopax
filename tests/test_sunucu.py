"""İndirme sunucusu: gerçek HTTP (rastgele port), sahte motorla üretilmiş kitap."""
import io
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from libriopax import donustur, sunucu
from libriopax.ses import uretici
from tests.test_epub import epub_yap


@unittest.skipUnless(uretici.ffmpeg_yolu(), "ffmpeg yok (bölüm MP3'i üretilemez)")
class Sunucu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dizin = Path(tempfile.mkdtemp())
        cls.veri = cls.dizin / "veri"
        kitap = cls.dizin / "k.epub"
        epub_yap(kitap, {"a.xhtml": "<h1>Bir</h1><p>Kısa bir cümle.</p>", "b.xhtml": "<h1>İki</h1><p>Bir cümle daha.</p>"})
        with redirect_stdout(io.StringIO()) as cikti, redirect_stderr(io.StringIO()) as cls.hata:
            donustur.main([str(kitap), "--motor", "sahte", "--veri", str(cls.veri), "--json"])
        cls.ozet = json.loads(cikti.getvalue().strip().splitlines()[-1])
        (cls.veri / "sunucu.json").write_text(json.dumps({"genel_adres": "https://pc.ts.net/libriopax/",
                                                          "kullanici": "sahip@ornek.com"}), encoding="utf-8")
        cls.s = sunucu.sunucu(cls.veri, port=0)
        cls.taban = f"http://127.0.0.1:{cls.s.server_address[1]}/"
        threading.Thread(target=cls.s.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.s.shutdown()
        cls.s.server_close()
        shutil.rmtree(cls.dizin, ignore_errors=True)

    def _al(self, yol, **basliklar):
        istek = urllib.request.Request(self.taban + yol, headers=basliklar)
        with urllib.request.urlopen(istek, timeout=10) as c:
            return c.status, dict(c.headers), c.read()

    def test_ana_sayfa_ve_kitap_sayfasi(self):
        kod, _, govde = self._al("", **{"Tailscale-User-Login": "sahip@ornek.com"})
        metin = govde.decode()
        self.assertEqual(kod, 200)
        self.assertIn("Deneme Kitabı", metin)
        self.assertIn(f'href="k/{self.ozet["kimlik"]}/"', metin)      # görece bağlantı (tailscale /libriopax öneki)
        self.assertNotIn("Telefonla tara", metin)                       # QR sadece bilgisayardan açınca
        self.assertIn("Telefonla tara", self._al("")[2].decode())
        _, _, govde = self._al(f"k/{self.ozet['kimlik']}/")
        metin = govde.decode()
        self.assertIn('href="sahte-sinus/kitap.zip"', metin)
        self.assertIn('href="sahte-sinus/1.mp3?indir=1"', metin)
        self.assertIn('href="../../"', metin)

    def test_mp3_aralik_ve_indirme(self):
        yol = f"k/{self.ozet['kimlik']}/sahte-sinus/1.mp3"
        kod, b, govde = self._al(yol)
        self.assertEqual((kod, b["Content-Type"], b["Accept-Ranges"]), (200, "audio/mpeg", "bytes"))
        self.assertNotIn("Content-Disposition", b)
        kod, b, parca = self._al(yol, Range="bytes=10-19")
        self.assertEqual((kod, parca), (206, govde[10:20]))
        self.assertEqual(b["Content-Range"], f"bytes 10-19/{len(govde)}")
        _, b, _ = self._al(yol + "?indir=1")
        self.assertIn("filename*=UTF-8''001%20-%20B%C3%B6l%C3%BCm%201.mp3", b["Content-Disposition"])

    def test_zip(self):
        _, b, govde = self._al(f"k/{self.ozet['kimlik']}/sahte-sinus/kitap.zip")
        self.assertEqual(b["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(govde)) as z:
            self.assertEqual(z.namelist(), ["Deneme Kitabı/001 - Bölüm 1.mp3", "Deneme Kitabı/002 - Bölüm 2.mp3"])

    def test_yetki_ve_bulunamayan(self):
        with self.assertRaises(urllib.error.HTTPError) as h:
            self._al("", **{"Tailscale-User-Login": "baskasi@ornek.com"})
        self.assertEqual(h.exception.code, 403)
        for yol in ["k/../../etc", "k/zzz/", f"k/{self.ozet['kimlik']}/sahte-sinus/99.mp3",
                    f"k/{self.ozet['kimlik']}/../kitap.json", "k/000000000000/"]:
            with self.assertRaises(urllib.error.HTTPError, msg=yol) as h:
                self._al(yol)
            self.assertEqual(h.exception.code, 404, yol)

    def test_donustur_linki_yazar(self):
        self.assertEqual(sunucu.kitap_linki(self.ozet["kimlik"], self.veri),
                         f"https://pc.ts.net/libriopax/k/{self.ozet['kimlik']}/")


if __name__ == "__main__":
    unittest.main()
