"""Kitabın ayrıştırılmış hâli: ayrıştırıcılar (epub, pdf) Kitap üretir, bölücü onu Sayfa'lara çevirir."""
from dataclasses import dataclass, field


class KitapHatasi(Exception):
    """Kullanıcıya olduğu gibi gösterilebilecek, sade Türkçe hata."""


@dataclass
class Blok:
    """Bir paragraf ya da başlık."""
    metin: str
    bolum: int                      # Kitap.bolumler indeksi
    baslik: bool = False
    # PDF: [(karakter_konumu, kaynak_sayfa)] artan sırada; konumdan itibaren metin o sayfadadır
    sayfa_sinirlari: list = field(default_factory=list)


@dataclass
class Kitap:
    baslik: str
    yazar: str
    dil: str
    tur: str                        # "epub" | "pdf"
    bolumler: list                  # bölüm başlıkları
    bloklar: list                   # Blok
    kaynak_sayfa_sayisi: int = 0    # PDF'in fiziksel sayfa sayısı


@dataclass
class Sayfa:
    sira: int                       # 1'den başlar
    bolum: int
    metin: str                      # gösterilen metin (değiştirilmez)
    cumleler: list                  # [{"bas", "son", "ara"}]; ara: cumle | paragraf | baslik
    kaynak_sayfa: int = None        # PDF'te fiziksel sayfa numarası
