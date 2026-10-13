"""D0.3 Chatterbox Multilingual ölçümü (GPU, .venv-gpu ile çalışır):

    .venv-gpu\\Scripts\\python araclar\\chatterbox_olc.py [--sayfa veri/kitaplar/<kimlik>/kitap.json:2] [--referans ses.wav]

Bir kitap sayfasını cümle cümle üretir; yükleme süresi, sayfa süresi, gerçek zaman çarpanı ve en yüksek VRAM'i yazar,
sesi olcum/chatterbox_<ses>.wav olarak kaydeder (Piper örnekleriyle karşılaştırmak için).
"""
import argparse
import json
import sys
import time
import wave
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from libriopax.metin.okunus import okunus  # noqa: E402

YEDEK = ("Bir sonbahar sabahı, Ahmet Bey eski konağın kapısını açtı. Bahçedeki çınar ağacının yaprakları sararmış, "
         "rüzgârla birlikte yere dökülüyordu. — Hoş geldiniz, dedi. Selim pencerenin önüne oturdu, çayını yudumladı "
         "ve uzun süre sustu.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sayfa", help="kitap.json:sayfa_no")
    ap.add_argument("--referans", help="izinli referans ses (wav, 10-20 sn)")
    ap.add_argument("--ad", default="varsayilan")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if a.sayfa:
        yol, _, no = a.sayfa.rpartition(":")
        kitap = json.loads(Path(yol).read_text(encoding="utf-8"))
        s = kitap["sayfalar"][int(no) - 1]
        cumleler = [okunus(s["metin"][c["bas"]:c["son"]], c["ara"] == "baslik") for c in s["cumleler"]]
    else:
        cumleler = [c.strip() + "." for c in YEDEK.split(".") if c.strip()]
    cumleler = [c for c in cumleler if any(ch.isalnum() for ch in c)]

    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    t0 = time.time()
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
    yukleme = time.time() - t0
    torch.cuda.reset_peak_memory_stats()

    parcalar, t0 = [], time.time()
    for c in cumleler:
        ek = {"audio_prompt_path": a.referans} if a.referans else {}
        wav = model.generate(c, language_id="tr", **ek)
        parcalar.append(wav.squeeze(0).cpu())
        parcalar.append(torch.zeros(int(model.sr * 0.25)))
    sure = time.time() - t0
    ses = torch.cat(parcalar)
    ses_sn = len(ses) / model.sr

    cikti = KOK / "olcum" / f"chatterbox_{a.ad}.wav"
    cikti.parent.mkdir(exist_ok=True)
    with wave.open(str(cikti), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(model.sr)
        w.writeframes((ses.clamp(-1, 1) * 32767).short().numpy().tobytes())
    print(json.dumps({"cumle": len(cumleler), "karakter": sum(map(len, cumleler)), "yukleme_sn": round(yukleme, 1),
                      "uretim_sn": round(sure, 1), "ses_sn": round(ses_sn, 1), "rtf": round(ses_sn / sure, 2),
                      "vram_gb": round(torch.cuda.max_memory_allocated() / 2 ** 30, 2), "dosya": cikti.name},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
