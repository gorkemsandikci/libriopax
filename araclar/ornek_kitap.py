"""Telifsiz Ömer Seyfettin hikâyelerinden (Vikikaynak) gerçek boyutlu test kitapları üretir.

    python araclar/ornek_kitap.py            -> ornekler/omer-seyfettin.epub ve .pdf

PDF Edge ile basılır: A5, üst bilgi (kitap adı), alt bilgi (sayfa numarası), heceleme (satır sonu tireleri) ve
iki yana yaslama açık — temizleyicinin gerçek kitaplarda karşılaşacağı durumlar.
"""
import html
import json
import subprocess
import sys
import zipfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
KAYNAK = KOK / "ornekler" / "kaynak" / "omer_seyfettin.json"
CIKTI = KOK / "ornekler"
BASLIK, YAZAR = "Hikâyeler", "Ömer Seyfettin"
EDGE = [Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")]


def paragraflar(metin: str) -> list:
    metin = html.unescape(metin)  # Vikikaynak metninde &mdash; gibi varlıklar kalmış
    return [" ".join(p.split()) for p in metin.split("\n") if p.strip()]


def epub_yap(hikayeler: list, yol: Path) -> None:
    spine, manifest, nav = [], [], []
    with zipfile.ZipFile(yol, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile '
                   'full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        for i, h in enumerate(hikayeler, 1):
            ad = f"bolum{i:03}.xhtml"
            govde = "".join(f"<p>{html.escape(p)}</p>\n" for p in paragraflar(h["metin"]))
            z.writestr(f"OEBPS/{ad}", '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
                       f'lang="tr"><head><title>{html.escape(h["baslik"])}</title><style>p{{text-indent:1em}}</style>'
                       f'</head><body><h2>{html.escape(h["baslik"])}</h2>\n{govde}</body></html>')
            manifest.append(f'<item id="b{i}" href="{ad}" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="b{i}"/>')
            nav.append(f'<li><a href="{ad}">{html.escape(h["baslik"])}</a></li>')
        z.writestr("OEBPS/nav.xhtml", '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
                   'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>İçindekiler</title></head><body>'
                   f'<nav epub:type="toc"><ol>{"".join(nav)}</ol></nav></body></html>')
        z.writestr("OEBPS/content.opf", '<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" '
                   'version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f'<dc:identifier id="id">libriopax-ornek-omer-seyfettin</dc:identifier><dc:title>{BASLIK}</dc:title>'
                   f'<dc:creator>{YAZAR}</dc:creator><dc:language>tr</dc:language></metadata><manifest>'
                   '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
                   f'{"".join(manifest)}</manifest><spine>{"".join(spine)}</spine></package>')


def pdf_yap(hikayeler: list, yol: Path) -> None:
    govde = []
    for h in hikayeler:
        govde.append(f'<h2>{html.escape(h["baslik"])}</h2>')
        govde += [f"<p>{html.escape(p)}</p>" for p in paragraflar(h["metin"])]
    sayfa = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>{BASLIK}</title><style>
@page {{ size: A5; margin: 18mm 16mm 20mm;
  @top-center {{ content: "{YAZAR} — {BASLIK}"; font: italic 8pt Georgia; color: #555; }}
  @bottom-center {{ content: counter(page); font: 9pt Georgia; }} }}
body {{ font: 10.5pt/1.45 Georgia, serif; text-align: justify; hyphens: auto; }}
p {{ margin: 0; text-indent: 1.2em; }}
h2 {{ break-before: page; text-align: center; font-size: 14pt; margin: 3em 0 1.5em; }}
</style></head><body><h1 style="text-align:center;margin-top:30%">{YAZAR}<br>{BASLIK}</h1>{"".join(govde)}</body></html>"""
    gecici = yol.with_suffix(".html")
    gecici.write_text(sayfa, encoding="utf-8")
    edge = next(e for e in EDGE if e.exists())
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--generate-pdf-document-outline",
                    "--virtual-time-budget=20000",
                    f"--print-to-pdf={yol}", gecici.as_uri()], capture_output=True, timeout=600)
    gecici.unlink()


def main() -> int:
    hikayeler = json.loads(KAYNAK.read_text(encoding="utf-8"))
    epub_yap(hikayeler, CIKTI / "omer-seyfettin.epub")
    pdf_yap(hikayeler, CIKTI / "omer-seyfettin.pdf")
    for ad in ("omer-seyfettin.epub", "omer-seyfettin.pdf"):
        print(ad, (CIKTI / ad).stat().st_size // 1024, "KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
