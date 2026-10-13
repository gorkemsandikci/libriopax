"""Ses motorları. Her motor: ornekleme (Hz) ve sentezle(metin) -> 16 bit mono PCM bytes."""
import math
import struct
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent.parent
PIPER_DIZINI = KOK / "modeller" / "piper"


def piper_sesleri() -> list:
    return sorted(p.name.removeprefix("tr_TR-").removesuffix("-medium.onnx")
                  for p in PIPER_DIZINI.glob("tr_TR-*-medium.onnx"))


class PiperMotor:
    """Yerel Piper (CPU). Türkçe sesler: dfki (CC BY-NC-SA, ticari değil), fahrettin ve fettah (CC0)."""
    ad = "piper"

    def __init__(self, ses: str = "dfki", hiz: float = 1.0):
        from piper import PiperVoice
        from piper.config import SynthesisConfig
        yol = PIPER_DIZINI / f"tr_TR-{ses}-medium.onnx"
        if not yol.exists():
            raise FileNotFoundError(f"Piper sesi yok: {yol.name} (mevcut: {', '.join(piper_sesleri()) or '-'})")
        self.ses = ses
        self._ses = PiperVoice.load(str(yol))
        self._ayar = SynthesisConfig(length_scale=1.0 / hiz)
        self.ornekleme = self._ses.config.sample_rate

    def sentezle(self, metin: str) -> bytes:
        return b"".join(p.audio_int16_bytes for p in self._ses.synthesize(metin, syn_config=self._ayar))


class SahteMotor:
    """Testler için: karakter başına 10 ms'lik sinüs (gerçek motor yüklenmeden üretim hattı sınanır)."""
    ad = "sahte"
    ses = "sinus"
    ornekleme = 8000

    def __init__(self, *_, **__):
        self.metinler = []

    def sentezle(self, metin: str) -> bytes:
        self.metinler.append(metin)
        n = len(metin) * self.ornekleme // 100
        return struct.pack(f"<{n}h", *(int(8000 * math.sin(i / 8)) for i in range(n)))
