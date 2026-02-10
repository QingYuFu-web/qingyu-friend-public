"""
语音活动检测模块
使用 webrtcvad 实现实时语音检测（持续监听核心）
"""

import webrtcvad
import collections
from typing import Iterator, Optional


class VADDetector:
    """语音活动检测器"""

    def __init__(self, aggressiveness: int = 3, sample_rate: int = 16000):
        """
        初始化VAD检测器

        Args:
            aggressiveness: 检测严格程度 (0-3)
                           0: 最宽松（容易触发）
                           1: 一般宽松
                           2: 一般严格
                           3: 最严格（推荐，减少误触发）
            sample_rate: 采样率（必须是 8000, 16000, 32000, 48000 之一）
        """
        self.vad = webrtcvad.Vad(aggressiveness)
        self.sample_rate = sample_rate

        # 验证采样率
        if sample_rate not in [8000, 16000, 32000, 48000]:
            raise ValueError(f"采样率必须是 8000, 16000, 32000, 48000 之一，当前: {sample_rate}")

        # VAD 只能处理 10ms, 20ms, 30ms 的帧
        # 对于 16kHz，10ms = 160 samples = 320 bytes (16bit)
        self.frame_duration_ms = 30  # 使用 30ms 帧
        self.frame_size = int(sample_rate * self.frame_duration_ms / 1000) * 2  # bytes

        # 语音检测参数
        self.padding_duration_ms = 300  # 静音填充时长（检测到静音后继续录音的时间）
        self.speech_start_frames = 10   # 连续多少帧检测到语音才开始录音
        self.speech_end_frames = 20     # 连续多少帧静音才结束录音

        print(f"🔊 VAD检测器初始化:")
        print(f"   严格度: {aggressiveness}/3")
        print(f"   采样率: {sample_rate} Hz")
        print(f"   帧大小: {self.frame_size} bytes ({self.frame_duration_ms}ms)")

    def is_speech(self, audio_chunk: bytes) -> bool:
        """
        判断音频块是否包含语音

        Args:
            audio_chunk: 音频数据（必须是 10/20/30ms 的帧）

        Returns:
            True if 包含语音, False otherwise
        """
        # 确保音频块大小正确
        if len(audio_chunk) != self.frame_size:
            # 填充或截断到正确大小
            if len(audio_chunk) < self.frame_size:
                audio_chunk += b'\x00' * (self.frame_size - len(audio_chunk))
            else:
                audio_chunk = audio_chunk[:self.frame_size]

        try:
            return self.vad.is_speech(audio_chunk, self.sample_rate)
        except:
            return False

    def detect_speech_segments(self, audio_stream: Iterator[bytes]) -> Optional[bytes]:
        """
        从音频流中检测语音片段（持续监听核心）

        工作原理：
        1. 持续监听音频流
        2. 检测到连续的语音帧时开始录音
        3. 检测到连续的静音帧时结束录音并返回

        Args:
            audio_stream: 音频流迭代器（来自 AudioDevice.start_stream()）

        Returns:
            检测到的语音片段（PCM数据），如果没有检测到返回 None
        """
        # 使用环形缓冲区
        ring_buffer = collections.deque(maxlen=self.speech_end_frames)
        triggered = False  # 是否已触发录音
        voiced_frames = []  # 录音缓冲

        speech_count = 0  # 连续语音帧计数
        silence_count = 0  # 连续静音帧计数

        for audio_chunk in audio_stream:
            # 分割为多个VAD帧
            num_frames = len(audio_chunk) // self.frame_size

            for i in range(num_frames):
                frame = audio_chunk[i * self.frame_size:(i + 1) * self.frame_size]

                if len(frame) < self.frame_size:
                    continue

                is_speech = self.is_speech(frame)

                if not triggered:
                    # 等待触发状态
                    ring_buffer.append((frame, is_speech))

                    if is_speech:
                        speech_count += 1
                        silence_count = 0
                    else:
                        speech_count = 0
                        silence_count += 1

                    # 检测到足够的语音帧，开始录音
                    if speech_count >= self.speech_start_frames:
                        triggered = True
                        print("🎤 检测到说话，开始录音...")

                        # 将环形缓冲区中的数据加入录音
                        for f, s in ring_buffer:
                            voiced_frames.append(f)

                        ring_buffer.clear()
                        speech_count = 0
                        silence_count = 0

                else:
                    # 录音状态
                    voiced_frames.append(frame)
                    ring_buffer.append((frame, is_speech))

                    if not is_speech:
                        silence_count += 1
                        speech_count = 0
                    else:
                        silence_count = 0
                        speech_count += 1

                    # 检测到足够的静音帧，结束录音
                    if silence_count >= self.speech_end_frames:
                        print("🔇 检测到静音，录音结束")

                        # 返回录音数据（去掉末尾的静音）
                        voiced_audio = b''.join(voiced_frames[:-self.speech_end_frames])
                        return voiced_audio if voiced_audio else None

        # 音频流结束
        if triggered and voiced_frames:
            return b''.join(voiced_frames)

        return None

    def filter_silence(self, audio_data: bytes) -> list:
        """
        过滤音频中的静音部分

        Args:
            audio_data: 完整音频数据

        Returns:
            包含语音的音频片段列表
        """
        segments = []
        current_segment = []
        is_speaking = False

        # 分割为VAD帧
        for i in range(0, len(audio_data), self.frame_size):
            frame = audio_data[i:i + self.frame_size]

            if len(frame) < self.frame_size:
                break

            if self.is_speech(frame):
                current_segment.append(frame)
                is_speaking = True
            else:
                if is_speaking and current_segment:
                    # 结束一个语音片段
                    segments.append(b''.join(current_segment))
                    current_segment = []
                    is_speaking = False

        # 添加最后一个片段
        if current_segment:
            segments.append(b''.join(current_segment))

        return segments
