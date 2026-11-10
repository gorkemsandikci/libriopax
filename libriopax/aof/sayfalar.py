"""AÖF sekmesinin HTML gövdeleri (sunucu.py sarar). Veri ünite klasörlerinden okunur (anlat.py düzeni)."""
import html
import json
import re
from pathlib import Path

DERS = re.compile(r"^[A-Za-z0-9-]{1,40}$")
UNITE = re.compile(r"^\d{2}$")
SES = ("anlatim", "ozet")

STIL = """
.sekmeler{display:flex;gap:6px;margin:0 0 14px;padding:4px;border-radius:999px;background:var(--krem);border:1px solid var(--bej)}
.sekmeler a,.sekmeler button{flex:1;min-height:40px;display:grid;place-items:center;border-radius:999px;border:0;background:none;
font:inherit;font-weight:600;font-size:15px;color:var(--yazi-2);text-decoration:none;cursor:pointer;padding:0 8px}
.sekmeler [aria-current],.sekmeler [aria-selected=true]{background:var(--zemin);color:var(--vurgu-yazi);box-shadow:var(--golge)}
.unite{display:flex;gap:12px;align-items:center;padding:12px 0;border-top:1px solid var(--bej);color:inherit;text-decoration:none}
.unite:first-of-type{border-top:0}.unite>div{flex:1;min-width:0}
.no{flex:none;width:40px;height:40px;border-radius:12px;display:grid;place-items:center;font-weight:700;
background:linear-gradient(160deg,var(--krem),var(--bej-orta));color:var(--vurgu-yazi)}
.etiket{display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;background:var(--krem);
color:var(--yazi-2);border:1px solid var(--bej)}.etiket.hazir{color:#2F6B3A;background:#EEF6EE;border-color:#CFE5D0}
.imler{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.imler button,.hiz button{min-height:36px;padding:0 12px;border-radius:999px;border:1px solid var(--bej-orta);
background:var(--zemin-sicak);font:inherit;font-size:14px;color:var(--vurgu-yazi);cursor:pointer}
.hiz{display:flex;gap:6px;margin-top:8px;align-items:center}.hiz [aria-pressed=true]{background:var(--vurgu);color:#fff;border-color:var(--vurgu)}
.icerik h2{font-size:17px;margin:20px 0 6px}.icerik h3{font-size:15px;margin:14px 0 4px;color:var(--vurgu-yazi)}
.icerik p{margin:0 0 10px}
.dikkat{border-left:3px solid var(--vurgu);background:var(--zemin-sicak);border-radius:0 12px 12px 0;padding:10px 14px;margin:10px 0 4px}
.dikkat ul{margin:6px 0 0;padding-left:18px}
dl.kavram dt{font-weight:650;margin-top:10px}dl.kavram dd{margin:2px 0 0;color:var(--yazi-2)}
.soru{padding:14px 0;border-top:1px solid var(--bej)}.soru:first-child{border-top:0}
.soru .kok{font-weight:600;margin-bottom:8px}
.secenek{display:flex;gap:10px;width:100%;text-align:left;align-items:flex-start;min-height:44px;margin:6px 0;padding:10px 12px;
border-radius:12px;border:1px solid var(--bej-orta);background:var(--zemin-sicak);font:inherit;color:inherit;cursor:pointer}
.secenek b{flex:none;width:20px}.secenek:disabled{cursor:default}
.secenek.dogru{background:#EEF6EE;border-color:#7FB487}.secenek.yanlis{background:#FBEDEA;border-color:#D99284}
.aciklama{display:none;font-size:14px;color:var(--yazi-2);margin-top:6px}.cevaplandi .aciklama{display:block}
.puan{position:sticky;top:62px;z-index:1;display:inline-block;font-weight:650;background:var(--zemin);padding:4px 14px;
border-radius:999px;border:1px solid var(--bej);box-shadow:var(--golge)}
details{margin:8px 0}summary{cursor:pointer;font-weight:600;min-height:32px}
[hidden]{display:none!important}
"""


def _oku(yol: Path, varsayilan=None):
    try:
        return json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return varsayilan


def _e(s) -> str:
    return html.escape(str(s or ""))


def _sure(ms: int) -> str:
    dk = round(ms / 60000)
    return f"{dk // 60} sa {dk % 60} dk" if dk >= 60 else f"{max(dk, 1)} dk"


def unite_oku(dizin: Path):
    u = _oku(dizin / "unite.json")
    if not u:
        return None
    anlatim = [_oku(dizin / "anlatim" / f"{i:02}.json") for i in range(1, len(u["bolumler"]) + 1)]
    return {"dizin": dizin, "ders": dizin.parent.name, "no": dizin.name, "u": u, "anlatim": anlatim,
            "hazirlik": _oku(dizin / "hazirlik.json"),
            "ses": {ad: _oku(dizin / "ses" / f"{ad}.json") for ad in SES}}


def dersler(aof: Path) -> list:
    """[{"kod", "ad", "uniteler": [unite_oku(...)]}] — ders koduna, ünite numarasına göre sıralı."""
    sonuc = {}
    for yol in sorted((aof / "dersler").glob("*/*/unite.json")):
        dizin = yol.parent
        if not (DERS.match(dizin.parent.name) and UNITE.match(dizin.name)):
            continue
        x = unite_oku(dizin)
        if x:
            d = sonuc.setdefault(x["ders"], {"kod": x["ders"], "ad": x["u"]["ders_adi"] or x["ders"], "uniteler": []})
            d["uniteler"].append(x)
    return list(sonuc.values())


def ses_dosyasi(aof: Path, ders: str, no: str, ad: str):
    if not (DERS.match(ders) and UNITE.match(no) and ad in SES):
        return None
    bilgi = _oku(aof / "dersler" / ders / no / "ses" / f"{ad}.json")
    yol = aof / "dersler" / ders / no / "ses" / (bilgi or {}).get("dosya", "")
    return yol if bilgi and yol.is_file() else None


def _durum(x: dict) -> tuple:
    """(hazır mı, kısa durum yazısı)"""
    hazir_bolum = sum(1 for a in x["anlatim"] if a)
    toplam = len(x["anlatim"])
    if x["ses"]["anlatim"] and x["hazirlik"]:
        return True, _sure(x["ses"]["anlatim"]["sure_ms"])
    if hazir_bolum < toplam:
        return False, f"anlatım {hazir_bolum}/{toplam}"
    if not x["hazirlik"]:
        return False, "sorular hazırlanıyor"
    return False, "ses hazırlanıyor"


def liste(aof: Path) -> str:
    parcalar = []
    for d in dersler(aof):
        satirlar = []
        for x in d["uniteler"]:
            hazir, yazi = _durum(x)
            satirlar.append(f'<a class="unite" href="{_e(d["kod"])}/{_e(x["no"])}/"><span class="no">{int(x["no"])}</span>'
                            f'<div><div class="baslik">{_e(x["u"]["unite_adi"])}</div></div>'
                            f'<span class="etiket{" hazir" if hazir else ""}">{"✓ " if hazir else "⏳ "}{_e(yazi)}</span></a>')
        parcalar.append(f'<div class="kart"><div class="baslik">{_e(d["ad"])}</div><div class="ikincil">{_e(d["kod"])} · '
                        f'{len(d["uniteler"])} ünite</div>{"".join(satirlar)}</div>')
    if not parcalar:
        parcalar.append('<div class="bos">Henüz ünite yok.<br>Ünite PDF\'lerini bilgisayarda <code>veri/aof/gelen/</code> '
                        'klasörüne koy; her saat işlenir.</div>')
    return "".join(parcalar)


def _oynatici(ad: str, baslik: str, bilgi: dict) -> str:
    imler = "".join(f'<button type="button" data-ms="{i["ms"]}">{_e(i["baslik"])}</button>' for i in bilgi.get("imler") or [])
    return (f'<div class="kart"><div class="baslik">{_e(baslik)}</div><div class="ikincil">{_sure(bilgi["sure_ms"])}</div>'
            f'<audio data-ad="{ad}" preload="metadata" controls src="{ad}.mp3"></audio>'
            f'<div class="hiz" role="group" aria-label="Hız">' +
            "".join(f'<button type="button" data-hiz="{h}" aria-pressed="{str(h == 1).lower()}">{h}×</button>'
                    for h in (1, 1.25, 1.5, 1.75)) +
            f'<a class="yuvarlak" href="{ad}.mp3?indir=1" download aria-label="İndir" style="margin-left:auto">⬇</a></div>'
            f'{f"<details><summary>Bölümler</summary><div class=imler>{imler}</div></details>" if imler else ""}</div>')


def _turkce_baslik(s: str) -> str:
    """"ANATOMİNİN TANIMI" → "Anatominin Tanımı" (str.title "Tanimi" yapar)."""
    kucuk = s.replace("İ", "i").replace("I", "ı").lower()
    return " ".join(k[:1].replace("i", "İ").upper() + k[1:] for k in kucuk.split(" "))


def _anlatim_html(x: dict) -> str:
    parcalar = []
    for b, a in zip(x["u"]["bolumler"], x["anlatim"]):
        parcalar.append(f'<h2>{_e(_turkce_baslik(b["baslik"]) if b["baslik"].isupper() else b["baslik"])}</h2>')
        if not a:
            parcalar.append('<p class="ikincil">⏳ Bu bölümün anlatımı hazırlanıyor.</p>')
            continue
        for k in a["kisimlar"]:
            parcalar.append(f'<h3>{_e(k["baslik"])}</h3>' + "".join(f"<p>{_e(p)}</p>" for p in k["paragraflar"]))
        if a.get("dikkat"):
            parcalar.append('<div class="dikkat"><b>Sınavda dikkat</b><ul>' +
                            "".join(f"<li>{_e(d)}</li>" for d in a["dikkat"]) + "</ul></div>")
    return "".join(parcalar)


def _ozet_html(u: dict) -> str:
    amac = "".join(f"<li>{_e(a)}</li>" for a in u["amaclar"])
    parcalar = [f'<h2>Amaçlar</h2><ul>{amac}</ul>' if amac else "",
                "<h2>Kitabın özeti</h2>" + "".join(f"<p>{_e(p)}</p>" for p in u["ozet"])]
    if u.get("okuma"):
        parcalar.append("<details><summary>Okuma parçası</summary>" + "".join(f"<p>{_e(p)}</p>" for p in u["okuma"]) +
                        "</details>")
    return "".join(parcalar)


def _kavram_html(u: dict, hazirlik) -> str:
    kavramlar = (hazirlik or {}).get("kavramlar") or []
    if kavramlar:
        return '<dl class="kavram">' + "".join(f'<dt>{_e(k["terim"])}</dt><dd>{_e(k["aciklama"])}</dd>' for k in kavramlar) + "</dl>"
    return ("<ul>" + "".join(f"<li>{_e(k)}</li>" for k in u["kavramlar"]) + "</ul>"
            '<p class="ikincil">⏳ Kavram açıklamaları hazırlanıyor.</p>')


def _soru_html(s: dict, kaynak: str) -> str:
    secenekler = "".join(f'<button type="button" class="secenek" data-i="{i}"><b>{"ABCDE"[i]})</b><span>{_e(m)}</span></button>'
                         for i, m in enumerate(s["secenekler"]))
    return (f'<div class="soru" data-dogru="{s["dogru"]}"><div class="kok"><span class="etiket">{_e(kaynak)}</span> '
            f'{_e(s["soru"])}</div>{secenekler}<div class="aciklama">{_e(s.get("aciklama"))}</div></div>')


def _test_html(u: dict, hazirlik) -> str:
    kitap = [s for s in u["sorular"] if isinstance(s.get("dogru"), int)]
    ek = (hazirlik or {}).get("sorular") or []
    parcalar = [f'<div class="puan" aria-live="polite">0 / {len(kitap) + len(ek)}</div>'] if kitap or ek else []
    if kitap:
        parcalar.append("<h2>Kendimizi Sınayalım</h2>" + "".join(_soru_html(s, "Kitap") for s in kitap))
    if ek:
        parcalar.append("<h2>Deneme soruları</h2>" + "".join(_soru_html(s, "Deneme") for s in ek))
    elif hazirlik is None:
        parcalar.append('<p class="ikincil">⏳ Deneme soruları hazırlanıyor.</p>')
    sorular = {x["no"]: x["soru"] for x in (hazirlik or {}).get("sira_sizde") or []}
    if u["sira_sizde"]:
        parcalar.append("<h2>Sıra Sizde</h2>" + "".join(
            f'<details><summary>Sıra Sizde {x["no"]}{": " + _e(sorular[x["no"]]) if x["no"] in sorular else ""}</summary>'
            f'<p>{_e(x["yanit"])}</p></details>' for x in u["sira_sizde"]))
    return "".join(parcalar) + '<p><button class="dugme" type="button" id="sifirla">Testi sıfırla</button></p>'


BETIK = """<script>
(function(){
const sek=document.querySelectorAll('.sekmeler [role=tab]');
function ac(ad){sek.forEach(b=>{const s=b.dataset.ad===ad;b.setAttribute('aria-selected',s);
 document.getElementById('p-'+b.dataset.ad).hidden=!s});try{localStorage.setItem(location.pathname+'#sekme',ad)}catch(e){}}
sek.forEach(b=>b.onclick=()=>ac(b.dataset.ad));
try{const s=localStorage.getItem(location.pathname+'#sekme');if(s&&document.getElementById('p-'+s))ac(s)}catch(e){}
document.querySelectorAll('audio').forEach(a=>{
 const k=location.pathname+'#'+a.dataset.ad,kart=a.closest('.kart');
 a.addEventListener('loadedmetadata',()=>{try{const t=+localStorage.getItem(k);if(t>5&&t<a.duration-5)a.currentTime=t}catch(e){}},{once:true});
 a.addEventListener('timeupdate',()=>{try{localStorage.setItem(k,Math.floor(a.currentTime))}catch(e){}});
 a.addEventListener('play',()=>document.querySelectorAll('audio').forEach(x=>{if(x!==a)x.pause()}));
 kart.querySelectorAll('[data-ms]').forEach(b=>b.onclick=()=>{a.currentTime=b.dataset.ms/1000;a.play()});
 kart.querySelectorAll('[data-hiz]').forEach(b=>b.onclick=()=>{a.playbackRate=+b.dataset.hiz;
  kart.querySelectorAll('[data-hiz]').forEach(x=>x.setAttribute('aria-pressed',x===b))});
});
const puan=document.querySelector('.puan');
function say(){if(!puan)return;const c=document.querySelectorAll('.soru.cevaplandi');
 puan.textContent=[...c].filter(s=>s.dataset.sonuc==='1').length+' doğru · '+c.length+' / '+document.querySelectorAll('.soru').length}
document.querySelectorAll('.soru').forEach(s=>s.querySelectorAll('.secenek').forEach(b=>b.onclick=()=>{
 if(s.classList.contains('cevaplandi'))return;const d=s.dataset.dogru;s.classList.add('cevaplandi');
 s.dataset.sonuc=b.dataset.i===d?'1':'0';
 s.querySelectorAll('.secenek').forEach(x=>{x.disabled=true;if(x.dataset.i===d)x.classList.add('dogru')});
 if(b.dataset.i!==d)b.classList.add('yanlis');say()}));
const sf=document.getElementById('sifirla');if(sf)sf.onclick=()=>{document.querySelectorAll('.soru').forEach(s=>{
 s.classList.remove('cevaplandi');delete s.dataset.sonuc;s.querySelectorAll('.secenek').forEach(x=>{x.disabled=false;
 x.classList.remove('dogru','yanlis')})});say()};
})();
</script>"""


def unite(x: dict) -> str:
    u = x["u"]
    _, yazi = _durum(x)
    ust = (f'<div class="kart"><div class="ikincil">{_e(u["ders_adi"])} · {int(x["no"])}. Ünite</div>'
           f'<div class="baslik">{_e(u["unite_adi"])}</div><div class="ikincil">{_e(yazi)} · '
           f'<a href="kaynak.pdf" style="color:var(--vurgu-yazi)">Kitap PDF</a></div></div>')
    sesler = ""
    if x["ses"]["anlatim"]:
        sesler += _oynatici("anlatim", "🎧 Anlatım", x["ses"]["anlatim"])
    if x["ses"]["ozet"]:
        sesler += _oynatici("ozet", "📝 Kitabın özeti (sesli)", x["ses"]["ozet"])
    paneller = [("anlatim", "Anlatım", _anlatim_html(x)), ("ozet", "Özet", _ozet_html(u)),
                ("kavram", "Kavramlar", _kavram_html(u, x["hazirlik"])), ("test", "Test", _test_html(u, x["hazirlik"]))]
    sekmeler = '<div class="sekmeler" role="tablist">' + "".join(
        f'<button type="button" role="tab" data-ad="{ad}" aria-selected="{str(i == 0).lower()}">{ad_yazi}</button>'
        for i, (ad, ad_yazi, _) in enumerate(paneller)) + "</div>"
    govde = "".join(f'<div class="kart icerik" id="p-{ad}"{" hidden" if i else ""}>{icerik}</div>'
                    for i, (ad, _, icerik) in enumerate(paneller))
    return ust + sesler + sekmeler + govde + BETIK
