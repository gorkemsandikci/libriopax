"""Yükle / İşlerim, Ayarlar, Yönetim ve "onay bekliyor" sayfalarının HTML gövdeleri (sunucu.py sarar).

Yazma istekleri fetch ile JSON/ham gövde olarak gider ve "X-Libriopax: 1" başlığı taşır (başka siteden gelen form
gönderimleri bu başlığı koyamaz; sunucu başlıksız POST'u reddeder).
"""
import html

from . import hesap, isler

STIL = """
.form label{display:block;font-weight:600;margin:12px 0 6px}
.form select,.form input[type=text],.form input[type=password],.form input[type=number]{width:100%;min-height:44px;
border-radius:12px;border:1px solid var(--bej-orta);background:var(--zemin-sicak);padding:0 12px;font:inherit;color:inherit}
.secim{display:flex;gap:8px}.secim label{flex:1;margin:0}.secim input{position:absolute;opacity:0}
.secim span{display:grid;place-items:center;min-height:48px;border-radius:14px;border:1px solid var(--bej-orta);
background:var(--zemin-sicak);font-weight:600;cursor:pointer;text-align:center;padding:4px}
.secim input:checked+span{background:var(--vurgu);color:#fff;border-color:var(--vurgu)}
.secim input:focus-visible+span{outline:2px solid var(--vurgu-yazi);outline-offset:2px}
.dosya{display:grid;place-items:center;min-height:96px;border:2px dashed var(--bej-koyu);border-radius:16px;text-align:center;
padding:12px;cursor:pointer;color:var(--yazi-2);margin-top:12px}.dosya.dolu{border-style:solid;color:var(--yazi)}
.dosya input{position:absolute;opacity:0;width:1px;height:1px}
button.dugme{border:0;font:inherit;cursor:pointer;width:100%;margin-top:14px}button.dugme:disabled{opacity:.5;cursor:default}
.cubuk{height:8px;border-radius:99px;background:var(--bej);overflow:hidden;margin-top:8px}
.cubuk>div{height:100%;background:var(--vurgu);width:0;transition:width .3s}
.is{padding:12px 0;border-top:1px solid var(--bej)}.is:first-child{border-top:0}
.ust-satir{display:flex;gap:8px;align-items:center;justify-content:space-between}
.is .ad{font-weight:600;overflow-wrap:anywhere;min-width:0}
.mesaj{margin-top:10px;font-size:14px}.mesaj.hata{color:#A23B2A}.mesaj.tamam{color:#2F6B3A}
.etiket.hata{color:#A23B2A;background:#FBEDEA;border-color:#EBC3BA}.etiket.bekle{color:#7C5B39;background:#FFF6E8}
.kucuk-dugme{min-height:36px;padding:0 12px;border-radius:999px;border:1px solid var(--bej-orta);background:var(--zemin-sicak);
font:inherit;font-size:14px;color:var(--vurgu-yazi);cursor:pointer}
.kullanici{padding:12px 0}.kullanici+.kullanici{border-top:1px solid var(--bej)}.kullanici .ad{font-weight:600;overflow-wrap:anywhere;min-width:0}
.kutular{display:flex;flex-wrap:wrap;gap:8px 14px;margin:8px 0}.kutular label{display:flex;gap:6px;align-items:center;font-weight:400;margin:0}
.satir{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
"""

DURUM = {"onay": ("⏳ Onay bekliyor", "bekle"), "sirada": ("🕒 Sırada", "bekle"), "isleniyor": ("⚙️ İşleniyor", "bekle"),
         "tamam": ("✓ Hazır", "hazir"), "hata": ("✗ Hata", "hata"), "red": ("✗ Reddedildi", "hata"),
         "iptal": ("İptal", "")}
SES_ADLARI = {"fahrettin": "Fahrettin", "fettah": "Fettah", "dfki": "DFKI"}


def _e(s) -> str:
    return html.escape(str(s or ""))


def is_satiri(is_: dict, kok: str = "../") -> str:
    yazi, sinif = DURUM.get(is_["durum"], (is_["durum"], ""))
    tur = "📚 Kitap" if is_["tur"] == "kitap" else "🎓 AÖF"
    alt = []
    if is_["durum"] in ("isleniyor", "sirada") and (is_.get("ilerleme") or {}).get("yazi"):
        alt.append(f'<div class="ikincil">{_e(is_["ilerleme"]["yazi"])}</div>')
    if is_["durum"] == "isleniyor":
        alt.append(f'<div class="cubuk"><div style="width:{int((is_.get("ilerleme") or {}).get("yuzde") or 0)}%"></div></div>')
    if is_["durum"] in ("hata", "red") and is_.get("hata"):
        alt.append(f'<div class="mesaj hata">{_e(is_["hata"])}</div>')
    eylem = ""
    if is_["durum"] == "tamam" and (is_.get("sonuc") or {}).get("yol"):
        eylem = f'<a class="kucuk-dugme" style="display:inline-grid;place-items:center;text-decoration:none" href="{kok}{_e(is_["sonuc"]["yol"])}">Aç</a>'
    elif is_["durum"] in ("onay", "sirada"):
        eylem = f'<button class="kucuk-dugme" type="button" data-iptal="{_e(is_["id"])}">İptal</button>'
    return (f'<div class="is" data-id="{_e(is_["id"])}" data-durum="{_e(is_["durum"])}"><div class="ust-satir">'
            f'<div class="ad">{_e(is_["dosya_adi"])}</div><span class="etiket {sinif}">{yazi}</span></div>'
            f'<div class="ikincil">{tur} · {_e(is_["olusturma"][:16].replace("T", " "))}</div>{"".join(alt)}'
            f'<div class="satir">{eylem}</div></div>')


def isler_listesi(liste: list, kok: str = "../") -> str:
    if not liste:
        return '<div class="ikincil">Henüz iş yok.</div>'
    return "".join(is_satiri(x, kok) for x in liste[:30])


ORTAK_BETIK = """<script>
async function istek(yol,secenek){secenek=secenek||{};secenek.headers=Object.assign({'X-Libriopax':'1'},secenek.headers||{});
 const r=await fetch(yol,secenek);let v={};try{v=await r.json()}catch(e){}
 if(!r.ok)throw new Error(v.hata||('Hata '+r.status));return v}
</script>"""


def yukle(k: dict, liste: list, gemini_bugun: int, kendi_anahtar: bool) -> str:
    motorlar = [m for m in k.get("motorlar", []) if m in hesap.MOTORLAR]
    motor_html = "".join(
        f'<label><input type="radio" name="motor" value="{m}"{" checked" if i == 0 else ""}'
        f'{"" if m in hesap.HAZIR_MOTORLAR else " disabled"}><span>{_e(hesap.MOTORLAR[m].split(" (")[0])}'
        f'{"" if m in hesap.HAZIR_MOTORLAR else "<br><small>yakında</small>"}</span></label>' for i, m in enumerate(motorlar))
    ses_html = "".join(f'<option value="{s}">{SES_ADLARI[s]}</option>' for s in isler.SESLER)
    sinir = k.get("gemini_gunluk")
    if kendi_anahtar:
        kota = "Kendi Gemini anahtarın kullanılıyor (senin kotan)."
    elif sinir is None or k.get("yonetici"):
        kota = "AÖF için günlük sınır yok."
    else:
        kota = f"Bugün {gemini_bugun}/{sinir} AÖF ünitesi. Sınırsız için Ayarlar'dan kendi Gemini anahtarını ekle."
    onay = "" if k.get("otomatik_onay") else ('<div class="ikincil" style="margin-top:8px">Yüklediğin dosya yönetici '
                                              'onayından sonra sıraya girer.</div>')
    return f"""
<div class="kart form" id="form">
 <div class="baslik">Ne yükleyeceksin?</div>
 <div class="secim" role="radiogroup" style="margin-top:10px">
  <label><input type="radio" name="tur" value="kitap" checked><span>📚 Kitap<br><small>EPUB / PDF → sesli kitap</small></span></label>
  <label><input type="radio" name="tur" value="aof"><span>🎓 AÖF ünitesi<br><small>PDF → anlatım + test</small></span></label>
 </div>
 <label class="dosya" id="dosya-alan"><input type="file" id="dosya" accept=".epub,.pdf,application/pdf,application/epub+zip">
  <span id="dosya-yazi">📄 Dosya seç<br><small>en fazla {isler.AZAMI_BOYUT // 1024 // 1024} MB</small></span></label>
 <label>Ses motoru</label><div class="secim">{motor_html}</div>
 <label for="ses">Ses</label><select id="ses">{ses_html}</select>
 <div class="ikincil" id="kota" hidden style="margin-top:10px">🎓 {_e(kota)}</div>
 {onay}
 <button class="dugme" id="gonder" type="button" disabled>Yükle</button>
 <div class="cubuk" id="yukleme" hidden><div></div></div>
 <div class="mesaj" id="mesaj" role="status"></div>
</div>
<div class="kart"><div class="baslik">İşlerim</div><div id="isler">{isler_listesi(liste)}</div></div>
{ORTAK_BETIK}
<script>
(function(){{
const d=document.getElementById('dosya'),g=document.getElementById('gonder'),m=document.getElementById('mesaj'),
 c=document.getElementById('yukleme'),k=document.getElementById('kota');
const tur=()=>document.querySelector('[name=tur]:checked').value;
function guncelle(){{k.hidden=tur()!=='aof';d.accept=tur()==='aof'?'.pdf,application/pdf':'.epub,.pdf,application/pdf,application/epub+zip';
 g.disabled=!d.files.length}}
document.querySelectorAll('[name=tur]').forEach(r=>r.onchange=guncelle);
d.onchange=()=>{{const f=d.files[0];document.getElementById('dosya-alan').classList.toggle('dolu',!!f);
 document.getElementById('dosya-yazi').textContent=f?('📄 '+f.name+' · '+(f.size/1048576).toFixed(1)+' MB'):'📄 Dosya seç';guncelle()}};
g.onclick=()=>{{const f=d.files[0];if(!f)return;g.disabled=true;m.className='mesaj';m.textContent='Yükleniyor…';c.hidden=false;
 const q=new URLSearchParams({{tur:tur(),motor:(document.querySelector('[name=motor]:checked')||{{}}).value||'piper',
  ses:document.getElementById('ses').value}});
 const x=new XMLHttpRequest();x.open('POST','../api/yukle?'+q);x.setRequestHeader('X-Libriopax','1');
 x.setRequestHeader('X-Dosya-Adi',encodeURIComponent(f.name));x.setRequestHeader('Content-Type','application/octet-stream');
 x.upload.onprogress=e=>{{if(e.lengthComputable)c.firstElementChild.style.width=(100*e.loaded/e.total)+'%'}};
 x.onload=()=>{{let v={{}};try{{v=JSON.parse(x.responseText)}}catch(e){{}}c.hidden=true;
  if(x.status===200){{m.className='mesaj tamam';m.textContent=v.durum==='onay'?'✓ Yüklendi, onay bekliyor.':'✓ Yüklendi, sıraya girdi.';
   d.value='';d.onchange();yenile()}}else{{m.className='mesaj hata';m.textContent=v.hata||('Hata '+x.status);g.disabled=false}}}};
 x.onerror=()=>{{c.hidden=true;m.className='mesaj hata';m.textContent='Bağlantı koptu.';g.disabled=false}};x.send(f)}};
async function yenile(){{try{{const v=await istek('../api/isler');document.getElementById('isler').innerHTML=v.html;bagla()}}catch(e){{}}}}
function bagla(){{document.querySelectorAll('[data-iptal]').forEach(b=>b.onclick=async()=>{{b.disabled=true;
 try{{await istek('../api/is/'+b.dataset.iptal+'/iptal',{{method:'POST'}});yenile()}}catch(e){{alert(e.message)}}}})}}
bagla();setInterval(()=>{{if(document.querySelector('[data-durum=isleniyor],[data-durum=sirada],[data-durum=onay]'))yenile()}},5000);
guncelle();
}})();
</script>"""


def ayarlar(eposta: str, k: dict, kendi_anahtar: bool) -> str:
    motorlar = ", ".join(hesap.MOTORLAR[m].split(" (")[0] for m in k.get("motorlar", []) if m in hesap.MOTORLAR)
    sinir = "sınırsız" if k.get("gemini_gunluk") is None else f"günde {k['gemini_gunluk']} ünite"
    durum = ("✓ Kayıtlı. Bu anahtar sadece senin AÖF işlerinde kullanılır; kimse göremez."
             if kendi_anahtar else "Kayıtlı değil. Paylaşılan anahtarla " + sinir + ".")
    return f"""
<div class="kart"><div class="baslik">Hesap</div><div class="ikincil">{_e(eposta)}</div>
 <div class="ikincil" style="margin-top:6px">Ses motorların: {_e(motorlar)} · AÖF sınırı: {_e(sinir)}</div></div>
<div class="kart form"><div class="baslik">Kendi Gemini anahtarın</div>
 <div class="ikincil" style="margin-top:6px">Günlük AÖF sınırına takılmamak için Google AI Studio'dan ücretsiz anahtar
 alıp buraya ekleyebilirsin (aistudio.google.com → Get API key). Anahtar bu bilgisayarda Windows şifrelemesiyle
 saklanır; sayfada ya da kayıtlarda hiçbir zaman gösterilmez.</div>
 <div class="mesaj" id="anahtar-durum">{_e(durum)}</div>
 <label for="anahtar">Anahtar</label><input type="password" id="anahtar" autocomplete="off" spellcheck="false">
 <button class="dugme" id="kaydet" type="button">Kaydet</button>
 {'<button class="kucuk-dugme" id="sil" type="button" style="margin-top:10px">Anahtarımı sil</button>' if kendi_anahtar else ''}
 <div class="mesaj" id="mesaj" role="status"></div></div>
{ORTAK_BETIK}
<script>
(function(){{const m=document.getElementById('mesaj'),a=document.getElementById('anahtar');
document.getElementById('kaydet').onclick=async()=>{{m.className='mesaj';try{{await istek('../api/anahtar',{{method:'POST',
 headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{anahtar:a.value}})}});a.value='';location.reload()}}
 catch(e){{m.className='mesaj hata';m.textContent=e.message}}}};
const s=document.getElementById('sil');if(s)s.onclick=async()=>{{try{{await istek('../api/anahtar/sil',{{method:'POST'}});location.reload()}}
 catch(e){{m.className='mesaj hata';m.textContent=e.message}}}};}})();
</script>"""


def yonetim(kayit: dict, liste: list) -> str:
    bekleyen = [x for x in liste if x["durum"] == "onay"]
    is_html = "".join(
        f'<div class="is"><div class="ust-satir"><div class="ad">{_e(x["dosya_adi"])}</div>'
        f'<span class="etiket bekle">{"📚" if x["tur"] == "kitap" else "🎓"} {_e(x["secenek"]["motor"])}</span></div>'
        f'<div class="ikincil">{_e(x["eposta"])} · {_e(x["olusturma"][:16].replace("T", " "))} · '
        f'{x.get("boyut", 0) / 1048576:.1f} MB</div><div class="satir">'
        f'<button class="kucuk-dugme" data-is="{_e(x["id"])}" data-karar="onayla">✅ Onayla</button>'
        f'<button class="kucuk-dugme" data-is="{_e(x["id"])}" data-karar="reddet">❌ Reddet</button></div></div>'
        for x in bekleyen) or '<div class="ikincil">Onay bekleyen iş yok.</div>'
    kisiler = []
    for e, k in sorted(kayit["kullanicilar"].items(), key=lambda x: (x[1]["durum"] != "bekliyor", x[0])):
        yazi, sinif = {"bekliyor": ("⏳ Bekliyor", "bekle"), "onayli": ("✓ Onaylı", "hazir"),
                       "reddedildi": ("✗ Reddedildi", "hata")}.get(k["durum"], (k["durum"], ""))
        kutular = "".join(
            f'<label><input type="checkbox" name="motor" value="{m}"{" checked" if m in k.get("motorlar", []) else ""}'
            f'{" disabled" if k.get("yonetici") else ""}> {_e(ad.split(" (")[0])}</label>' for m, ad in hesap.MOTORLAR.items())
        if k.get("yonetici"):
            kisiler.append(f'<div class="kullanici"><div class="ust-satir"><div class="ad">{_e(e)}</div>'
                           f'<span class="etiket hazir">🛡️ Yönetici</span></div></div>')
            continue
        durum_dugme = "".join(
            f'<button class="kucuk-dugme" data-durum="{d}">{y}</button>'
            for d, y in (("onayli", "✅ Onayla"), ("reddedildi", "❌ Reddet")) if d != k["durum"])
        kisiler.append(
            f'<div class="kullanici form" data-eposta="{_e(e)}"><div class="ust-satir"><div class="ad">{_e(e)}</div>'
            f'<span class="etiket {sinif}">{yazi}</span></div><div class="kutular">{kutular}</div>'
            f'<div class="kutular"><label><input type="checkbox" name="otomatik"{" checked" if k.get("otomatik_onay") else ""}>'
            f' İşleri onaysız sıraya girsin</label></div>'
            f'<div class="satir"><label style="margin:0">AÖF/gün</label><input type="number" name="gunluk" min="0" max="50" '
            f'style="width:90px" value="{"" if k.get("gemini_gunluk") is None else k["gemini_gunluk"]}" placeholder="sınırsız">'
            f'<button class="kucuk-dugme" data-kaydet>Kaydet</button>{durum_dugme}</div></div>')
    return f"""
<div class="kart"><div class="baslik">Onay bekleyen işler</div>{is_html}</div>
<div class="kart"><div class="baslik">Kullanıcılar</div>{"".join(kisiler)}</div>
<div class="mesaj" id="mesaj" role="status"></div>
{ORTAK_BETIK}
<script>
(function(){{const m=document.getElementById('mesaj');
async function yap(yol,govde){{try{{await istek(yol,{{method:'POST',headers:{{'Content-Type':'application/json'}},
 body:JSON.stringify(govde||{{}})}});location.reload()}}catch(e){{m.className='mesaj hata';m.textContent=e.message}}}}
document.querySelectorAll('[data-karar]').forEach(b=>b.onclick=()=>yap('../api/yonetim/is/'+b.dataset.is+'/'+b.dataset.karar));
document.querySelectorAll('.kullanici[data-eposta]').forEach(k=>{{const g=()=>({{eposta:k.dataset.eposta,
 motorlar:[...k.querySelectorAll('[name=motor]:checked')].map(x=>x.value),otomatik_onay:k.querySelector('[name=otomatik]').checked,
 gemini_gunluk:k.querySelector('[name=gunluk]').value}});
 k.querySelector('[data-kaydet]').onclick=()=>yap('../api/yonetim/kullanici',g());
 k.querySelectorAll('[data-durum]').forEach(b=>b.onclick=()=>yap('../api/yonetim/kullanici',Object.assign(g(),{{durum:b.dataset.durum}})));}});
}})();
</script>"""


def bekliyor(eposta: str, durum: str) -> str:
    if durum == "reddedildi":
        return (f'<div class="kart"><div class="baslik">Erişim verilmedi</div><div class="ikincil">{_e(eposta)} için '
                'erişim isteği reddedildi.</div></div>')
    return (f'<div class="kart"><div class="baslik">Onay bekleniyor</div><div class="ikincil" style="margin-top:6px">'
            f'Merhaba! {_e(eposta)} hesabın için erişim isteği yöneticiye iletildi. Onaylanınca bu sayfayı yenilemen '
            'yeterli.</div></div>')
