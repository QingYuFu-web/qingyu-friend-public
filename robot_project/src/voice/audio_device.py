"""
音频设备管理模块
使用 PyAudio 管理麦克风录音和扬声器播放
"""

import pyaudio
import wave
import time
from typing import Generator, Optional
import io

from src.voice.aec import EcAecConfig, EcEchoCanceller


class AudioDevice:
    """音频设备管理器"""

    def __init__(self, config: dict, aec_config: Optional[dict] = None):
        """
        初始化音频设备

        Args:
            config: 音频配置字典，包含：
                - sample_rate: 采样率（默认16000，豆包要求）
                - channels: 声道数（默认1，单声道）
                - chunk_size: 每次读取的帧数
                - input_device: 输入设备索引（None为默认）
                - output_device: 输出设备索引（None为默认）
        """
        self.sample_rate = config.get('sample_rate', 16000)
        self.channels = config.get('channels', 1)
        # PyAudio 的 frames_per_buffer / read() 参数单位是“帧”(frame)，不是字节：
        # 单声道 16kHz 下，480 帧 ≈ 30ms（VAD 典型帧长），3200 帧 ≈ 200ms。
        self.chunk_size = config.get('chunk_size', 480)
        self.input_device = config.get('input_device')
        self.output_device = config.get('output_device')

        # AEC（外放回声消除）：可选，用 voice-engine/ec 实现
        self.aec: Optional[EcEchoCanceller] = None
        if aec_config and aec_config.get("enabled"):
            self.aec = EcEchoCanceller(
                EcAecConfig(
                    enabled=True,
                    ec_binary=aec_config.get("ec_binary", "/usr/local/bin/ec"),
                    capture_device=aec_config.get("capture_device", "default"),
                    playback_device=aec_config.get("playback_device", "default"),
                    sample_rate=self.sample_rate,
                    capture_channels=int(aec_config.get("capture_channels", 2)),
                    delay_ms=int(aec_config.get("delay_ms", 200)),
                    filter_length=int(aec_config.get("filter_length", 4096)),
                    playback_fifo=aec_config.get("playback_fifo", "/tmp/ec.input"),
                    output_fifo=aec_config.get("output_fifo", "/tmp/ec.output"),
                    output_downmix_to_mono=bool(aec_config.get("output_downmix_to_mono", True)),
                )
            )

        # PyAudio 实例
        self.pyaudio = pyaudio.PyAudio()
        self.stream = None

        print(f"📢 音频设备初始化:")
        print(f"   采样率: {self.sample_rate} Hz")
        print(f"   声道: {self.channels}")
        print(f"   帧大小: {self.chunk_size}")
        if self.aec and self.aec.enabled:
            print("   ✅ AEC: 已启用（voice-engine/ec）")
        else:
            print("   ℹ️  AEC: 未启用")

    def __del__(self):
        """清理资源"""
        self.stop_stream()
        if self.aec:
            try:
                self.aec.stop()
            except Exception:
                pass
        if self.pyaudio:
            self.pyaudio.terminate()

    def list_devices(self):
        """列出所有音频设备"""
        print("\n可用音频设备:")
        for i in range(self.pyaudio.get_device_count()):
            info = self.pyaudio.get_device_info_by_index(i)
            print(f"  [{i}] {info['name']}")
            print(f"      输入通道: {info['maxInputChannels']}")
            print(f"      输出通道: {info['maxOutputChannels']}")

    def record_audio(self, duration: Optional[float] = None) -> bytes:
        """
        录音（阻塞）

        Args:
            duration: 录音时长（秒），None表示持续录音直到手动停止

        Returns:
            录音的音频数据（PCM格式）
        """
        if self.aec and self.aec.enabled:
            raise RuntimeError("AEC 启用时不支持 record_audio() 直连录音，请使用 start_stream()。")

        frames = []

        stream = self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.input_device,
            frames_per_buffer=self.chunk_size
        )

        print("🎤 录音中...")

        if duration:
            # 固定时长录音
            num_chunks = int(self.sample_rate / self.chunk_size * duration)
            for _ in range(num_chunks):
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                frames.append(data)
        else:
            # 持续录音（需外部控制停止）
            try:
                while True:
                    data = stream.read(self.chunk_size, exception_on_overflow=False)
                    frames.append(data)
            except KeyboardInterrupt:
                pass

        stream.stop_stream()
        stream.close()

        print("⏹️  录音结束")
        return b''.join(frames)

    def play_audio(self, audio_data: bytes):
        """
        播放音频

        Args:
            audio_data: PCM格式音频数据
        """
        if self.aec and self.aec.enabled:
            # AEC 模式：把“播放参考信号”写入 /tmp/ec.input，由 ec 负责真正播放，并用于消回声。
            self.aec.write_playback(audio_data)
            return

        stream = self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            output=True,
            output_device_index=self.output_device
        )

        # 分块播放
        chunk_size = 1024
        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i+chunk_size]
            stream.write(chunk)

        stream.stop_stream()
        stream.close()

    def start_stream(self) -> 'AudioStream':
        """
        启动音频流（用于持续监听）

        Returns:
            AudioStream对象，可迭代获取音频块
        """
        if self.aec and self.aec.enabled:
            # AEC 模式：从 /tmp/ec.output 读取“消回声后的录音”，并按配置下混为单声道给上层 VAD/ASR。
            self.aec.start()
            return AecAudioStream(self.aec, chunk_frames=self.chunk_size)

        if self.stream:
            self.stop_stream()

        self.stream = self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.input_device,
            frames_per_buffer=self.chunk_size,
            stream_callback=None
        )

        print("🎤 开始持续监听...")
        return AudioStream(self.stream, self.chunk_size)

    def stop_stream(self):
        """停止音频流"""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
            print("⏹️  停止监听")
        if self.aec:
            try:
                self.aec.stop()
            except Exception:
                pass

    def save_wav(self, audio_data: bytes, filename: str):
        """
        保存为WAV文件

        Args:
            audio_data: PCM音频数据
            filename: 输出文件名
        """
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.pyaudio.get_sample_size(pyaudio.paInt16))
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data)
        print(f"💾 已保存: {filename}")

    def load_wav(self, filename: str) -> bytes:
        """
        从WAV文件加载

        Args:
            filename: WAV文件路径

        Returns:
            PCM音频数据
        """
        with wave.open(filename, 'rb') as wf:
            return wf.readframes(wf.getnframes())


class AudioStream:
    """音频流迭代器（用于持续监听）"""

    def __init__(self, stream, chunk_size: int):
        self.stream = stream
        self.chunk_size = chunk_size

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        """获取下一块音频数据"""
        if not self.stream.is_active():
            raise StopIteration

        try:
            data = self.stream.read(self.chunk_size, exception_on_overflow=False)
            return data
        except Exception as e:
            raise StopIteration

    def read(self) -> bytes:
        """读取一块音频数据（非迭代方式）"""
        return self.stream.read(self.chunk_size, exception_on_overflow=False)


class AecAudioStream:
    """AEC 输出流（来自 /tmp/ec.output），提供与 AudioStream 类似的 read() 接口。"""

    def __init__(self, aec: EcEchoCanceller, chunk_frames: int):
        self.aec = aec
        self.chunk_frames = chunk_frames

    def read(self) -> bytes:
        return self.aec.read_capture_mono(frames=self.chunk_frames, timeout_s=0.2)
