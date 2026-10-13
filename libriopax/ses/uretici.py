"""Sayfa sesi üretimi: cümle cümle sentez + cümle zamanları (vurgulama için) + MP3 (ffmpeg)."""
import json
import os
import shutil
import subprocess
import wave
from pathlib import Path

from ..metin.okunus import okunus

ARALAR_SN = {"cumle": 0.25, "paragraf": 0.6, "baslik": 0.9}   # cümleden sonraki sessizlik
MP3_KBPS = 48


def sayfa_sesi(motor, sayfa) -> tuple:
    """(pcm, zamanlar) — zamanlar: her cümle için [bas_ms, son_ms]."""
    pcm, zamanlar, ornek = bytearray(), [], 0
    for c in sayfa.cumleler:
        metin = okunus(sayfa.metin[c["bas"]:c["son"]], baslik=c["ara"] == "baslik")
        parca = motor.sentezle(metin) if any(ch.isalnum() for ch in metin) else b""   # "— ......" sadece duraklama
        bas = ornek
        pcm += parca
        ornek += len(parca) // 2
        zamanlar.append([round(bas * 1000 / motor.ornekleme), round(ornek * 1000 / motor.ornekleme)])
        bosluk = int(ARALAR_SN[c["ara"]] * motor.ornekleme)
        pcm += b"\x00\x00" * bosluk
        ornek += bosluk
    return bytes(pcm), zamanlar


def ffmpeg_yolu():
    return shutil.which("ffmpeg")


def yaz(pcm: bytes, ornekleme: int, yol: Path) -> Path:
    """MP3 yazar (ffmpeg yoksa WAV). Önce geçici dosya, bitince yeniden adlandırma: yarım dosya kalmaz."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_yolu()
    if ffmpeg is None:
        yol = yol.with_suffix(".wav")
    gecici = yol.with_name(yol.name + ".tmp")
    if ffmpeg:
        sonuc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "s16le", "-ar",
                                str(ornekleme), "-ac", "1", "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a",
                                f"{MP3_KBPS}k", "-f", "mp3", str(gecici)], input=pcm, capture_output=True)
        if sonuc.returncode != 0:
            gecici.unlink(missing_ok=True)
            raise RuntimeError(f"ffmpeg: {sonuc.stderr.decode(errors='replace')[-300:]}")
    else:
        with wave.open(str(gecici), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(ornekleme)
            w.writeframes(pcm)
    os.replace(gecici, yol)
    return yol


def json_yaz(veri, yol: Path) -> None:
    gecici = yol.with_name(yol.name + ".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    os.replace(gecici, yol)
