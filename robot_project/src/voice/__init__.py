"""
语音模块 - 集成豆包ASR和TTS服务

包含：
- audio_device: 音频设备管理（录音/播放）
- vad: 语音活动检测
- asr: 语音识别（豆包ASR）
- tts: 语音合成（豆包TTS）
"""

from .audio_device import AudioDevice
from .vad import VADDetector
from .asr import VolcengineASR
from .tts import VolcengineTTS

__all__ = ['AudioDevice', 'VADDetector', 'VolcengineASR', 'VolcengineTTS']
