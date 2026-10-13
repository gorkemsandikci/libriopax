"""Metin katmanı (stdlib): cümle bölme, okunuş, temizlik, sayfalama. Ek paket gerektirmez."""
import unittest

from libriopax.metin import bol, okunus, temizle
from libriopax.metin.model import Blok, Kitap


def cumleler(metin):
    return [metin[b:s] for b, s in bol.cumlelere_bol(metin)]


class CumleBolme(unittest.TestCase):
    def test_temel(self):
        self.assertEqual(cumleler("Geldi. Gitti! Ne oldu? Bilmem."), ["Geldi.", "Gitti!", "Ne oldu?", "Bilmem."])

    def test_kisaltmalar_bolmez(self):
        for metin in ["Dr. Selim geldi.", "Prof. Ayşe Hanım derse girdi.", "Elma, armut vb. meyveler aldı.",
                      "Şirket A.Ş. adına imzaladı.", "M.Ö. 500 yılında oldu.", "A. Haluk Bey geldi.",
                      "Bkz. Ek 3 ve sonrası.", "3. Bölüm başladı.", "19. yüzyılda yaşadı."]:
            self.assertEqual(cumleler(metin), [metin], metin)

    def test_sayilar_bolmez(self):
        self.assertEqual(cumleler("Konakta 3.500 cilt vardı. Hepsi eskiydi."),
                         ["Konakta 3.500 cilt vardı.", "Hepsi eskiydi."])
        self.assertEqual(cumleler("Fiyat 2,5 liraydı."), ["Fiyat 2,5 liraydı."])

    def test_kucuk_harfle_devam(self):
        self.assertEqual(cumleler("Ne? dedi adam. Sonra sustu."), ["Ne? dedi adam.", "Sonra sustu."])

    def test_uc_nokta_ve_tirnak(self):
        self.assertEqual(cumleler('Ama... Hayır, gitmedi. "Gel!" Sonra döndü.'),
                         ["Ama...", "Hayır, gitmedi.", '"Gel!"', "Sonra döndü."])
        self.assertEqual(cumleler("— Hoş geldiniz, dedi. — Sağ olun."), ["— Hoş geldiniz, dedi.", "— Sağ olun."])

    def test_uzun_cumle_parcalanir(self):
        metin = ", ".join(["uzun bir yan cümle daha"] * 80) + "."
        parcalar = cumleler(metin)
        self.assertGreater(len(parcalar), 1)
        self.assertTrue(all(len(p) <= bol.AZAMI_CUMLE for p in parcalar))
        self.assertEqual(" ".join(parcalar), metin)


class Okunus(unittest.TestCase):
    def test_sayi_yazi(self):
        for n, yazi in [(0, "sıfır"), (7, "yedi"), (10, "on"), (100, "yüz"), (101, "yüz bir"), (1000, "bin"),
                        (1923, "bin dokuz yüz yirmi üç"), (2000, "iki bin"), (3500, "üç bin beş yüz"),
                        (1_000_000, "bir milyon"), (21_450_007, "yirmi bir milyon dört yüz elli bin yedi")]:
            self.assertEqual(okunus.sayi_yazi(n), yazi)

    def test_sira_yazi(self):
        for n, yazi in [(1, "birinci"), (3, "üçüncü"), (4, "dördüncü"), (6, "altıncı"), (19, "on dokuzuncu"),
                        (40, "kırkıncı"), (100, "yüzüncü"), (1000, "bininci")]:
            self.assertEqual(okunus.sira_yazi(n), yazi)

    def test_roma(self):
        self.assertEqual([okunus.roma_coz(s) for s in ["IV", "XIV", "MCMXXIII", "IIII", "MIX", "VX", "ABC"]],
                         [4, 14, 1923, None, 1009, None, None])

    def test_okunus(self):
        for metin, beklenen in [
            ("Dr. Selim geldi.", "Doktor Selim geldi."),
            ("19. yüzyılda", "on dokuzuncu yüzyılda"),
            ("1923'te kuruldu", "bin dokuz yüz yirmi üçte kuruldu"),
            ("3.500'den fazla", "üç bin beş yüzden fazla"),
            ("II. Abdülhamit", "ikinci Abdülhamit"),
            ("Elma vb. şeyler", "Elma ve benzeri şeyler"),
            ("bkz. s. 45", "bakınız sayfa 45"),
            ("Ali * Veli", "Ali Veli"),
            ("söz konusudur, [ed.n.]", "söz konusudur, editörün notu"),
            ("bir deyimdir. [ç.n.]", "bir deyimdir. çevirmenin notu"),
            ("Ali & Veli 🙝🙟", "Ali ve Veli"),
            ("Bilgi için https://ornek.com adresine", "Bilgi için adresine"),
        ]:
            self.assertEqual(okunus.okunus(metin), beklenen, metin)

    def test_baslik(self):
        self.assertEqual(okunus.okunus("BÖLÜM IV", baslik=True), "BÖLÜM dört.")
        self.assertEqual(okunus.okunus("Aleko", baslik=True), "Aleko.")
        self.assertEqual(okunus.okunus("I. Kısım", baslik=True), "birinci Kısım.")


class Temizlik(unittest.TestCase):
    def test_satir(self):
        self.assertEqual(temizle.satir("ﬁkir\u00a0ve\u200b  ﬂüt\x02"), "fikir ve flüt-")

    def test_birlestir(self):
        self.assertEqual(temizle.birlestir("kitap okuyan kel-", "sinin evi"), "kitap okuyan kelsinin evi")
        self.assertEqual(temizle.birlestir("Ankara-", "İstanbul yolu"), "Ankara-İstanbul yolu")
        self.assertEqual(temizle.birlestir("bir", "iki"), "bir iki")
        self.assertEqual(temizle.birlestir("", "iki"), "iki")

    def test_dipnot(self):
        self.assertEqual(temizle.dipnot_isaretleri("konağın3 kapısı, 1923 yılında"), "konağın kapısı, 1923 yılında")

    def test_ust_alt_bilgi(self):
        govde = lambda i: [f"Gövde {chr(65 + i)} bir", f"Gövde {chr(65 + i)} iki", f"Gövde {chr(65 + i)} üç"]
        sayfalar = [["Kitabın Adı", *govde(i), str(i + 1)] for i in range(10)]
        sayfalar[4] = ["Kitabın Adı", *govde(4), "- 5 -"]
        sayfalar[6] = ["KİTABIN ADI", "Bölüm 3", *govde(6), "Sayfa 7"]
        temiz = temizle.ust_alt_bilgi_ayikla(sayfalar)
        self.assertEqual(temiz[0], govde(0))
        self.assertEqual(temiz[4], govde(4))
        self.assertEqual(temiz[6], ["Bölüm 3", *govde(6)])

    def test_kenardaki_siradan_satir_korunur(self):
        # Her sayfada geçen "— Evet." farklı konumlarda: üst/alt bilgi sayılmaz
        sayfalar = [[f"Satır {chr(65 + i)}{j}" for j in range(i % 7)] + ["— Evet."] + [f"Son {chr(65 + i)}{j}" for j in range(3)]
                    for i in range(20)]
        self.assertEqual(temizle.ust_alt_bilgi_ayikla(sayfalar), sayfalar)

    def test_kisa_sayfaya_dokunulmaz(self):
        sayfalar = [["Benzersiz başlık", "gövde"] for _ in range(10)]
        self.assertEqual(temizle.ust_alt_bilgi_ayikla(sayfalar), sayfalar)


class Sayfalama(unittest.TestCase):
    def _kitap(self, tur="epub"):
        cumle = "Bu, sayfalamayı sınamak için yazılmış orta uzunlukta bir cümledir."
        bloklar = [Blok("Birinci Bölüm", 0, True)] + [Blok(" ".join([cumle] * 5), 0) for _ in range(12)]
        bloklar += [Blok("İkinci Bölüm", 1, True), Blok(cumle, 1)]
        return Kitap("Deneme", "Yazar", "tr", tur, ["Birinci Bölüm", "İkinci Bölüm"], bloklar)

    def test_epub_sayfa_boyutu_ve_bolum_siniri(self):
        sayfalar = bol.sayfala(self._kitap(), hedef=1500)
        self.assertGreater(len(sayfalar), 2)
        for s in sayfalar[:-2]:
            self.assertLessEqual(len(s.metin), 1500 + 5)
            self.assertGreater(len(s.metin), 800)
        self.assertEqual([s.sira for s in sayfalar], list(range(1, len(sayfalar) + 1)))
        son = sayfalar[-1]
        self.assertEqual(son.bolum, 1)
        self.assertTrue(son.metin.startswith("İkinci Bölüm"))
        self.assertEqual(son.cumleler[0]["ara"], "baslik")

    def test_cumle_konumlari_metinle_uyumlu(self):
        for s in bol.sayfala(self._kitap()):
            for c in s.cumleler:
                parca = s.metin[c["bas"]:c["son"]]
                self.assertEqual(parca, parca.strip())
                self.assertTrue(parca)

    def test_pdf_cumle_basladigi_sayfada(self):
        metin = "Birinci cümle burada. İkinci cümle sayfa sınırını aşıyor ve devam ediyor. Üçüncü cümle."
        sinir = metin.index("sınırını")                 # ikinci cümlenin ortasında sayfa 8 başlıyor
        kitap = Kitap("D", "Y", "tr", "pdf", ["B"], [Blok(metin, 0, False, [(0, 7), (sinir, 8)])])
        sayfalar = bol.sayfala(kitap)
        self.assertEqual([s.kaynak_sayfa for s in sayfalar], [7, 8])
        self.assertIn("İkinci cümle sayfa sınırını", sayfalar[0].metin)
        self.assertEqual(sayfalar[1].metin, "Üçüncü cümle.")


if __name__ == "__main__":
    unittest.main()
