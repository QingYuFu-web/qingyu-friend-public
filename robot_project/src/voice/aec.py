"""
外放回声消除（AEC）适配层：对接 voice-engine/ec 的 FIFO 模式。

设计目标：
1) 不修改 voice-engine/ec 源码（按官方仓库直接构建/运行）。
2) Python 侧通过 /tmp/ec.input 写入播放参考信号（mono, 16k, s16le）。
3) Python 侧通过 /tmp/ec.output 读取消回声后的录音（通常为 2ch, 16k, s16le）。
4) 支持将 2ch 下混为 1ch，以适配当前火山 ASR 的单声道输入。
"""

from __future__ import annotations

import errno
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class EcAecConfig:
    enabled: bool = False
    ec_binary: str = "/usr/local/bin/ec"
    capture_device: str = "plughw:CARD=seeed2micvoicec,DEV=0"
    playback_device: str = "plughw:CARD=seeed2micvoicec,DEV=0"
    sample_rate: int = 16000
    capture_channels: int = 2
    delay_ms: int = 200
    filter_length: int = 4096
    playback_fifo: str = "/tmp/ec.input"
    output_fifo: str = "/tmp/ec.output"
    output_downmix_to_mono: bool = True


class EcEchoCanceller:
    """
    管理 voice-engine/ec 进程，以及 FIFO 的读写。

    注意：
    - ec 的 /tmp/ec.input（播放参考）只支持 mono（官方 README/源码均如此）。
    - ec 的 /tmp/ec.output 输出通道数通常等于录音通道数（例如 2ch）。
    """

    def __init__(self, config: EcAecConfig):
        self.config = config
        self._proc: Optional[subprocess.Popen] = None
        self._playback_fd: Optional[int] = None  # write -> /tmp/ec.input
        self._capture_fd: Optional[int] = None   # read  <- /tmp/ec.output

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled)

    def start(self) -> None:
        if not self.enabled:
            return

        if os.name != "posix":
            raise RuntimeError("AEC(ec) 仅支持在 Linux(POSIX) 环境运行。")

        if self._proc and self._proc.poll() is None:
            return

        # 启动 ec 进程：按源码含义，-i 设置录音设备(rec_pcm)，-o 设置播放设备(out_pcm)
        cmd = [
            self.config.ec_binary,
            "-i",
            self.config.capture_device,
            "-o",
            self.config.playback_device,
            "-r",
            str(self.config.sample_rate),
            "-c",
            str(self.config.capture_channels),
            "-d",
            str(self.config.delay_ms),
            "-f",
            str(self.config.filter_length),
        ]

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        self._wait_for_fifo(self.config.playback_fifo, timeout_s=5.0)
        self._wait_for_fifo(self.config.output_fifo, timeout_s=5.0)

        # 打开 FIFO：
        # - playback_fifo：ec 侧会 O_RDONLY|O_NONBLOCK 打开，因此我们这里 O_WRONLY 不会阻塞。
        # - output_fifo：ec 侧 writer 线程会 O_WRONLY 打开并可能阻塞到 reader 出现，因此我们这里用非阻塞读打开。
        self._playback_fd = os.open(self.config.playback_fifo, os.O_WRONLY)
        self._capture_fd = os.open(self.config.output_fifo, os.O_RDONLY | os.O_NONBLOCK)

    def stop(self) -> None:
        for fd in (self._playback_fd, self._capture_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._playback_fd = None
        self._capture_fd = None

        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def _wait_for_fifo(self, path: str, timeout_s: float) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            try:
                st = os.stat(path)
                if stat_is_fifo(st.st_mode):
                    return
            except FileNotFoundError:
                pass
            time.sleep(0.05)
        raise RuntimeError(f"AEC FIFO 未就绪: {path}")

    def write_playback(self, pcm_mono_s16le: bytes) -> None:
        if not self.enabled:
            return
        if self._playback_fd is None:
            raise RuntimeError("AEC 尚未启动：playback FIFO 未打开。")

        # ec 侧 playback 线程用非阻塞读；这里写入可能在管道满时阻塞。
        view = memoryview(pcm_mono_s16le)
        offset = 0
        while offset < len(view):
            try:
                written = os.write(self._playback_fd, view[offset:])
                if written <= 0:
                    break
                offset += written
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    time.sleep(0.001)
                    continue
                raise

    def read_capture(self, min_bytes: int, timeout_s: float = 0.2) -> bytes:
        if not self.enabled:
            return b""
        if self._capture_fd is None:
            raise RuntimeError("AEC 尚未启动：capture FIFO 未打开。")

        t0 = time.time()
        chunks = []
        total = 0
        while total < min_bytes and (time.time() - t0) < timeout_s:
            try:
                data = os.read(self._capture_fd, min_bytes - total)
                if not data:
                    time.sleep(0.002)
                    continue
                chunks.append(data)
                total += len(data)
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    time.sleep(0.002)
                    continue
                raise

        return b"".join(chunks)

    def read_capture_mono(self, frames: int, timeout_s: float = 0.2) -> bytes:
        """
        读取 AEC 输出并（可选）下混为单声道。
        假设格式为 s16le interleaved。
        """
        channels = self.config.capture_channels
        bytes_per_frame = channels * 2
        raw = self.read_capture(frames * bytes_per_frame, timeout_s=timeout_s)

        if not raw:
            return b""

        if not self.config.output_downmix_to_mono or channels == 1:
            return raw

        return downmix_s16le_interleaved_to_mono(raw, channels=channels)


def stat_is_fifo(mode: int) -> bool:
    return (mode & 0o170000) == 0o010000


def downmix_s16le_interleaved_to_mono(pcm: bytes, channels: int) -> bytes:
    if channels <= 1:
        return pcm
    if len(pcm) % 2 != 0:
        pcm = pcm[: len(pcm) - 1]

    # 以 int16 读取，按帧平均
    import array

    samples = array.array("h")
    samples.frombytes(pcm)

    frame_count = len(samples) // channels
    out = array.array("h", [0] * frame_count)

    for i in range(frame_count):
        acc = 0
        base = i * channels
        for c in range(channels):
            acc += samples[base + c]
        out[i] = int(acc / channels)

    return out.tobytes()

