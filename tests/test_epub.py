"""EPUB ayrıştırıcı (stdlib): küçük EPUB'lar geçici dizinde kurulur."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from libriopax.metin import epub
from libriopax.metin.model import KitapHatasi

CONTAINER = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
             '<rootfiles><rootfile full-path="OPS/paket.opf" media-type="application/oebps-package+xml"/></rootfiles>'
             '</container>')


def xhtml(govde):
    return f'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>x</title><style>p{{}}</style></head><body>{govde}</body></html>'


def epub_yap(yol, dosyalar, toc="nav", sifre=None):
    manifest = "".join(f'<item id="d{i}" href="{ad}" media-type="application/xhtml+xml"/>' for i, ad in enumerate(dosyalar))
    spine = "".join(f'<itemref idref="d{i}"/>' for i in range(len(dosyalar)))
    with zipfile.ZipFile(yol, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        for ad, govde in dosyalar.items():
            z.writestr(f"OPS/{ad}", xhtml(govde))
        if toc == "nav":
            manifest += '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            linkler = "".join(f'<li><a href="{ad}#bas">Bölüm {i + 1}</a></li>' for i, ad in enumerate(dosyalar))
            z.writestr("OPS/nav.xhtml", xhtml(f'<nav epub:type="toc"><ol>{linkler}</ol></nav>'))
        elif toc == "ncx":
            manifest += '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            noktalar = "".join(f'<navPoint id="n{i}"><navLabel><text>NCX {i + 1}</text></navLabel><content src="{ad}"/></navPoint>'
                               for i, ad in enumerate(dosyalar))
            z.writestr("OPS/toc.ncx", f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>{noktalar}</navMap></ncx>')
        if sifre:
            z.writestr("META-INF/encryption.xml",
                       '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
                       'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>'
                       f'<enc:EncryptionMethod Algorithm="{sifre}"/><enc:CipherData><enc:CipherReference URI="OPS/a.xhtml"/>'
                       '</enc:CipherData></enc:EncryptedData></encryption>')
        z.writestr("OPS/paket.opf",
                   '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   '<dc:title>Deneme Kitabı</dc:title><dc:creator>Ayşe Yazar</dc:creator><dc:language>tr</dc:language></metadata>'
                   f'<manifest>{manifest}</manifest>{"<spine toc=" + chr(34) + "ncx" + chr(34) + ">" if toc == "ncx" else "<spine>"}{spine}</spine></package>')


class Epub(unittest.TestCase):
    def setUp(self):
        self.dizin = Path(tempfile.mkdtemp())
        self.yol = self.dizin / "k.epub"

    def test_nav_bolumler_ve_metin(self):
        epub_yap(self.yol, {"a.xhtml": "<h1>Başlangıç</h1><p>İlk <b>paragraf</b> &amp; devamı.</p><p>İkinci.</p>",
                            "b.xhtml": "<h2>Son</h2><p>Şiir satırı<br/>ikinci satır</p><script>alert(1)</script>"})
        k = epub.oku(self.yol)
        self.assertEqual((k.baslik, k.yazar, k.dil, k.tur), ("Deneme Kitabı", "Ayşe Yazar", "tr", "epub"))
        self.assertEqual(k.bolumler, ["Bölüm 1", "Bölüm 2"])
        self.assertEqual([(b.metin, b.bolum, b.baslik) for b in k.bloklar], [
            ("Başlangıç", 0, True), ("İlk paragraf & devamı.", 0, False), ("İkinci.", 0, False),
            ("Son", 1, True), ("Şiir satırı", 1, False), ("ikinci satır", 1, False)])

    def test_ncx(self):
        epub_yap(self.yol, {"a.xhtml": "<p>Bir.</p>", "b.xhtml": "<p>İki.</p>"}, toc="ncx")
        self.assertEqual(epub.oku(self.yol).bolumler, ["NCX 1", "NCX 2"])

    def test_icindekiler_yoksa_ilk_baslik(self):
        epub_yap(self.yol, {"a.xhtml": "<h1>Bir</h1><p>x.</p>", "b.xhtml": "<p>devam.</p>", "c.xhtml": "<h1>Üç</h1><p>y.</p>"},
                 toc=None)
        k = epub.oku(self.yol)
        self.assertEqual(k.bolumler, ["Bir", "Üç"])
        self.assertEqual([b.bolum for b in k.bloklar], [0, 0, 0, 1, 1])

    def test_dipnot_gondermesi_atlanir(self):
        epub_yap(self.yol, {"a.xhtml": '<p>Metin<a epub:type="noteref" href="#n1">1</a> sürer.</p>'
                                       '<aside epub:type="footnote" id="n1"><p>Dipnot.</p></aside>'})
        self.assertEqual([b.metin for b in epub.oku(self.yol).bloklar], ["Metin sürer."])
        epub_yap(self.yol, {"a.xhtml": "<p>Dopamin<sup>2</sup> salgılanır; x<sup>2</sup>+1 değil<sup>a</sup>.</p>"})
        self.assertEqual([b.metin for b in epub.oku(self.yol).bloklar], ["Dopamin salgılanır; x+1 değila."])
        epub_yap(self.yol, {"a.xhtml": '<p>Küçük dopamin<a class="dipnot" href="notlar.xhtml#a2">2</a> patlaması, '
                                       '<a href="b.xhtml">Bölüm 3</a> ve <a href="#x">şurası</a>.</p>'})
        self.assertEqual([b.metin for b in epub.oku(self.yol).bloklar], ["Küçük dopamin patlaması, Bölüm 3 ve şurası."])

    def test_drm_reddedilir_font_gizleme_degil(self):
        epub_yap(self.yol, {"a.xhtml": "<p>x.</p>"}, sifre="http://www.w3.org/2001/04/xmlenc#aes128-cbc")
        with self.assertRaisesRegex(KitapHatasi, "DRM"):
            epub.oku(self.yol)
        epub_yap(self.yol, {"a.xhtml": "<p>x.</p>"}, sifre="http://www.idpf.org/2008/embedding")
        self.assertEqual(len(epub.oku(self.yol).bloklar), 1)

    def test_bozuk_dosya(self):
        self.yol.write_bytes(b"zip degil")
        with self.assertRaisesRegex(KitapHatasi, "geçerli bir EPUB"):
            epub.oku(self.yol)

    def test_zip_bombasi(self):
        self.addCleanup(setattr, epub, "AZAMI_ACIK_BOYUT", epub.AZAMI_ACIK_BOYUT)
        epub.AZAMI_ACIK_BOYUT = 10_000
        with zipfile.ZipFile(self.yol, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("dev.txt", b"0" * 20_000)       # sıkışınca küçük, açılınca sınırın üstünde
        with self.assertRaisesRegex(KitapHatasi, "çok büyük"):
            epub.oku(self.yol)


if __name__ == "__main__":
    unittest.main()
