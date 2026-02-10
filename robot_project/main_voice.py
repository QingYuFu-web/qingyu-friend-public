"""
语音对话主程序 - 双向对话版
支持持续监听 + 可打断 + 声纹识别

使用方法：
    python main_voice.py

命令：
    说"退出"或"再见" - 结束对话
    Ctrl+C - 强制退出

特性：
    - 持续监听：TTS播放时也在监听
    - 可打断：检测到你说话会立即停止TTS
    - 低延迟：边合成边播放
    - 声纹识别：自动识别说话人，陌生人主动询问
"""

import asyncio
import json
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.brain.brain import Brain, load_api_config
from src.voice.audio_device import AudioDevice
from src.voice.vad import VADDetector
from src.voice.asr import VolcengineASR
from src.voice.tts import VolcengineTTS
from src.voice.dialog_manager import VoiceDialogManager

# 声纹识别（可选）
try:
    from src.voice.speaker_id import SpeakerIdentifier, RESEMBLYZER_AVAILABLE
except ImportError:
    SpeakerIdentifier = None
    RESEMBLYZER_AVAILABLE = False


def load_speech_config(config_path: str = "config/speech.json") -> dict:
    """加载语音配置"""
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


async def main():
    """主程序"""
    print("🔧 初始化中...\n")

    # 加载配置
    api_config = load_api_config()
    speech_config = load_speech_config()

    if not speech_config:
        print("❌ 未找到语音配置文件 config/speech.json")
        print("   请先配置ASR和TTS的凭证")
        return

    # 检查凭证
    asr_config = speech_config.get('asr', {})
    tts_config = speech_config.get('tts', {})

    if 'YOUR_' in asr_config.get('app_id', 'YOUR_'):
        print("⚠️  请在 config/speech.json 中配置ASR凭证")
        print("   app_id: 火山引擎语音识别应用ID")
        print("   access_token: 访问令牌")
        print()

    if 'YOUR_' in tts_config.get('app_id', 'YOUR_'):
        print("⚠️  请在 config/speech.json 中配置TTS凭证")
        print("   app_id: 火山引擎语音合成应用ID")
        print("   access_token: 访问令牌")
        print()

    # 初始化模块
    # 1. AI大脑
    backend_config = api_config.get(api_config.get('backend', 'doubao'), {})
    brain = Brain(
        backend=api_config.get('backend', 'doubao'),
        model=backend_config.get('model'),
        api_key=backend_config.get('api_key'),
        fallback_to_local=api_config.get('fallback_to_local', True)
    )

    # 2. 音频设备（可选 AEC：voice-engine/ec）
    audio_config = speech_config.get('audio', {})
    aec_config = speech_config.get('aec', {})
    audio_device = AudioDevice(audio_config, aec_config=aec_config)

    # 3. VAD检测器
    vad_config = speech_config.get('vad', {})
    vad = VADDetector(
        aggressiveness=vad_config.get('aggressiveness', 3),
        sample_rate=audio_config.get('sample_rate', 16000)
    )
    # 应用配置的参数
    vad.speech_start_frames = vad_config.get('speech_start_frames', 10)
    vad.speech_end_frames = vad_config.get('speech_end_frames', 40)

    # 4. ASR识别
    asr = VolcengineASR(asr_config)

    # 5. TTS合成
    tts = VolcengineTTS(tts_config, audio_device)

    # 6. 声纹识别（可选）
    speaker_id = None
    if SpeakerIdentifier and RESEMBLYZER_AVAILABLE:
        print()
        speaker_id = SpeakerIdentifier(data_dir="data/speakers")
    else:
        print("⚠️ 声纹识别未启用（需安装 resemblyzer: pip install resemblyzer）")

    print()

    # 创建双向对话管理器
    dialog_manager = VoiceDialogManager(
        brain=brain,
        audio_device=audio_device,
        vad=vad,
        asr=asr,
        tts=tts,
        speaker_id=speaker_id
    )

    # 运行
    await dialog_manager.run()


def run_sync():
    """同步运行入口"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    run_sync()
