"""
豆包语音合成模块 (TTS) - V3 双向流式接口
使用火山引擎WebSocket API实现文本转语音

参考文档：https://www.volcengine.com/docs/6561/1329505
"""

import asyncio
import json
import uuid
import gzip
import websockets
import ssl
from typing import Optional, AsyncGenerator


class VolcengineTTS:
    """火山引擎语音合成客户端 - V3 双向流式"""

    # V3 双向流式接口地址
    WSS_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

    # 消息类型
    MSG_FULL_CLIENT_REQUEST = 0x1
    MSG_AUDIO_RESPONSE = 0xB      # 音频响应
    MSG_ERROR_RESPONSE = 0xF

    def __init__(self, config: dict, audio_device=None):
        """
        初始化TTS客户端

        Args:
            config: TTS配置，包含：
                - app_id: 应用ID
                - access_token: 访问令牌
                - speaker: 音色ID
                - speed_ratio: 语速（0.5-2.0，默认1.0）
                - volume_ratio: 音量（0.1-2.0，默认1.0）
                - pitch_ratio: 音调（0.5-2.0，默认1.0）
            audio_device: AudioDevice实例，用于播放音频
        """
        self.app_id = config.get('app_id', '')
        self.access_token = config.get('access_token', '')
        self.speaker = config.get('speaker', 'BV002_streaming')
        self.speed_ratio = config.get('speed_ratio', 1.0)
        self.volume_ratio = config.get('volume_ratio', 1.0)
        self.pitch_ratio = config.get('pitch_ratio', 1.0)
        self.audio_device = audio_device

        # SSL配置（忽略证书验证）
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

        print(f"🔊 TTS客户端初始化:")
        print(f"   音色: {self.speaker}")
        print(f"   语速: {self.speed_ratio}x")

    def _build_header(self, msg_type: int = 1, msg_flags: int = 0, 
                      serialization: int = 1, compression: int = 0) -> bytes:
        """
        构建协议头 (V3格式)

        Args:
            msg_type: 消息类型 (1=full_request)
            msg_flags: 消息标志
            serialization: 序列化方式 (1=JSON)
            compression: 压缩方式 (0=none, 1=gzip)

        Returns:
            4字节协议头
        """
        return bytes([
            0x11,  # version=1, header_size=1
            (msg_type << 4) | msg_flags,
            (serialization << 4) | compression,
            0x00   # reserved
        ])

    def _build_start_connection_request(self) -> bytes:
        """
        构建开始连接请求
        """
        payload = {}
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        # 构建带 event=1 (StartConnection) 的完整帧
        header = self._build_header(msg_type=1, msg_flags=0x4, serialization=1, compression=0)
        event_num = (1).to_bytes(4, 'big')  # Event_StartConnection
        payload_size = len(payload_bytes).to_bytes(4, 'big')

        return header + event_num + payload_size + payload_bytes

    def _build_start_session_request(self, request_id: str) -> bytes:
        """
        构建开始会话请求
        """
        payload = {
            "user": {
                "uid": "robot_user"
            },
            "event": 100,  # ← 添加 event 字段
            "req_params": {
                "speaker": self.speaker,
                "audio_params": {
                    "format": "pcm",
                    "sample_rate": 16000,
                    "speech_rate": int((self.speed_ratio - 1.0) * 100),
                    "loudness_rate": int((self.volume_ratio - 1.0) * 100),
                    "pitch_rate": int((self.pitch_ratio - 1.0) * 100)
                }
            }
        }

        payload_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        # 构建带 event=100 (StartSession) 的完整帧
        header = self._build_header(msg_type=1, msg_flags=0x4, serialization=1, compression=0)
        event_num = (100).to_bytes(4, 'big')  # Event_StartSession
        session_id_bytes = request_id.encode('utf-8')
        session_id_len = len(session_id_bytes).to_bytes(4, 'big')
        payload_size = len(payload_bytes).to_bytes(4, 'big')

        return header + event_num + session_id_len + session_id_bytes + payload_size + payload_bytes

    def _build_text_request(self, text: str, request_id: str) -> bytes:
        """
        构建发送文本请求
        """
        payload = {
            "req_params": {
                "text": text
            }
        }

        payload_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        # 构建带 event=200 (TaskRequest) 的完整帧
        header = self._build_header(msg_type=1, msg_flags=0x4, serialization=1, compression=0)
        event_num = (200).to_bytes(4, 'big')  # Event_TaskRequest
        session_id_bytes = request_id.encode('utf-8')
        session_id_len = len(session_id_bytes).to_bytes(4, 'big')
        payload_size = len(payload_bytes).to_bytes(4, 'big')

        return header + event_num + session_id_len + session_id_bytes + payload_size + payload_bytes

    def _build_finish_request(self, request_id: str) -> bytes:
        """
        构建结束会话请求
        """
        payload = {}

        payload_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        # 构建带 event=102 (FinishSession) 的完整帧
        header = self._build_header(msg_type=1, msg_flags=0x4, serialization=1, compression=0)
        event_num = (102).to_bytes(4, 'big')  # Event_FinishSession
        session_id_bytes = request_id.encode('utf-8')
        session_id_len = len(session_id_bytes).to_bytes(4, 'big')
        payload_size = len(payload_bytes).to_bytes(4, 'big')

        return header + event_num + session_id_len + session_id_bytes + payload_size + payload_bytes

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        V3 双向流式合成语音

        Args:
            text: 要合成的文本

        Yields:
            音频数据块（PCM格式）
        """
        request_id = str(uuid.uuid4())

        # V3 使用 HTTP Header 鉴权
        headers = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": "seed-tts-1.0",  # TTS 1.0
            "X-Api-Connect-Id": request_id
        }

        try:
            async with websockets.connect(
                self.WSS_URL,
                additional_headers=headers,
                ssl=self.ssl_context,
                ping_interval=None,
                max_size=10 * 1024 * 1024
            ) as ws:
                # 0. 发送 StartConnection
                start_conn_request = self._build_start_connection_request()
                await ws.send(start_conn_request)

                # 等待 ConnectionStarted (event=50)
                response = await asyncio.wait_for(ws.recv(), timeout=10)
                print(f"✅ 连接已建立")

                # 1. 发送 StartSession
                start_session_request = self._build_start_session_request(request_id)
                await ws.send(start_session_request)

                # 等待 SessionStarted (event=150)
                response = await asyncio.wait_for(ws.recv(), timeout=10)
                print(f"✅ 会话已开始")

                # 2. 发送 TaskRequest (文本)
                text_request = self._build_text_request(text, request_id)
                await ws.send(text_request)

                # 3. 发送 FinishSession (告诉服务器没有更多文本了)
                finish_request = self._build_finish_request(request_id)
                await ws.send(finish_request)

                # 4. 接收音频数据
                total_audio_bytes = 0
                while True:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=30)

                        if len(response) < 4:
                            continue

                        # 正确解析 msg_type（高4位）和 msg_flags（低4位）
                        msg_type = (response[1] >> 4) & 0x0F
                        msg_flags = response[1] & 0x0F
                        header_size = 4  # 固定4字节

                        # 音频响应 (msg_type=0xB)
                        if msg_type == self.MSG_AUDIO_RESPONSE:
                            # 音频帧格式: header(4) + event(4) + session_id_len(4) + session_id + payload_size(4) + audio
                            offset = 4  # 跳过 header

                            # 跳过 event (4 bytes)
                            offset += 4

                            # 读取 session_id_len
                            if len(response) < offset + 4:
                                continue
                            session_id_len = int.from_bytes(response[offset:offset+4], 'big')
                            offset += 4

                            # 跳过 session_id
                            offset += session_id_len

                            # 读取 payload_size
                            if len(response) < offset + 4:
                                continue
                            payload_size = int.from_bytes(response[offset:offset+4], 'big')
                            offset += 4

                            # 读取音频数据
                            audio_data = response[offset:offset+payload_size]
                            if audio_data:
                                total_audio_bytes += len(audio_data)
                                yield audio_data

                            # 不再根据 msg_flags 判断结束
                            # 长文本会分多句，每句最后的音频帧都带结束标志
                            # 只通过 event=152 (SessionFinished) 判断真正结束

                        # 错误响应 (msg_type=0xF)
                        elif msg_type == self.MSG_ERROR_RESPONSE:
                            try:
                                # 错误帧格式: header(4) + error_code(4) + payload_size(4) + error_message
                                offset = 4  # 跳过 header

                                # 读取 error_code
                                error_code = int.from_bytes(response[offset:offset+4], 'big')
                                offset += 4

                                # 读取 payload_size
                                payload_size = int.from_bytes(response[offset:offset+4], 'big')
                                offset += 4

                                # 读取错误消息
                                error_data = response[offset:offset+payload_size]
                                error_msg = json.loads(error_data.decode('utf-8'))
                                print(f"❌ TTS错误 [code={error_code}]: {error_msg}")
                            except Exception as e:
                                print(f"❌ TTS错误响应解析失败: {e}")
                            break

                        # JSON 响应（Full-server response, msg_type=0x9）
                        elif msg_type == 0x9:
                            try:
                                # JSON帧格式: header(4) + event(4) + session_id_len(4) + session_id + payload_size(4) + json
                                offset = 4  # 跳过 header

                                # 读取 event
                                event = int.from_bytes(response[offset:offset+4], 'big')
                                offset += 4

                                # 读取 session_id_len
                                if len(response) < offset + 4:
                                    continue
                                session_id_len = int.from_bytes(response[offset:offset+4], 'big')
                                offset += 4

                                # 跳过 session_id
                                offset += session_id_len

                                # 读取 payload_size
                                if len(response) < offset + 4:
                                    continue
                                payload_size = int.from_bytes(response[offset:offset+4], 'big')
                                offset += 4

                                # 读取 JSON 数据
                                json_data = response[offset:offset+payload_size]
                                resp_json = json.loads(json_data.decode('utf-8'))

                                # 检查事件类型
                                # event=350: TTSSentenceStart（句子开始）
                                # event=351: TTSSentenceEnd（句子结束）- 但可能还有后续句子
                                # event=152: SessionFinished（会话结束）- 所有句子都完成
                                if event == 350:
                                    # 句子开始，显示文本
                                    text = resp_json.get('text', '')
                                    if text:
                                        print(f"📝 合成中: {text[:50]}...")
                                elif event == 152:
                                    # 会话结束，退出循环
                                    print(f"✅ 合成完成")
                                    break
                                # event=351 不退出，继续接收下一句
                            except Exception as e:
                                print(f"⚠️ JSON解析失败: {e}")

                    except asyncio.TimeoutError:
                        print("⚠️ TTS响应超时")
                        break
                    except websockets.ConnectionClosed:
                        break

                # 4. 发送结束会话请求
                try:
                    finish_request = self._build_finish_request(request_id)
                    await ws.send(finish_request)
                except:
                    pass

        except Exception as e:
            import traceback
            print(f"❌ TTS连接失败: {e}")
            print(f"详细错误:\n{traceback.format_exc()}")

    async def synthesize(self, text: str) -> Optional[bytes]:
        """
        一次性合成语音

        Args:
            text: 要合成的文本

        Returns:
            完整的音频数据（PCM格式）
        """
        audio_chunks = []

        async for chunk in self.synthesize_stream(text):
            audio_chunks.append(chunk)

        if audio_chunks:
            return b''.join(audio_chunks)
        return None

    async def speak(self, text: str):
        """
        合成并播放语音

        Args:
            text: 要播放的文本
        """
        if not self.audio_device:
            print("❌ 未配置AudioDevice，无法播放")
            return

        print(f"🗣️ 正在合成: {text[:30]}...")

        audio_data = await self.synthesize(text)

        if audio_data:
            print(f"🔊 播放中... ({len(audio_data)} bytes)")
            self.audio_device.play_audio(audio_data)
            print("✅ 播放完成")
        else:
            print("❌ 合成失败，无音频数据")

    async def speak_stream(self, text: str):
        """
        流式合成并播放语音（边合成边播放，延迟更低）

        Args:
            text: 要播放的文本
        """
        if not self.audio_device:
            print("❌ 未配置AudioDevice，无法播放")
            return

        print(f"🗣️ 流式播放: {text[:30]}...")

        # 收集一定量的数据后开始播放
        buffer = b''
        buffer_threshold = 3200  # 200ms @ 16kHz

        async for chunk in self.synthesize_stream(text):
            buffer += chunk

            if len(buffer) >= buffer_threshold:
                self.audio_device.play_audio(buffer)
                buffer = b''

        # 播放剩余数据
        if buffer:
            self.audio_device.play_audio(buffer)

        print("✅ 播放完成")


# 同步包装器（用于非异步环境）
class VolcengineTTSSync:
    """TTS同步包装器"""

    def __init__(self, config: dict, audio_device=None):
        self.tts = VolcengineTTS(config, audio_device)
        self._loop = None

    def _get_loop(self):
        """获取或创建事件循环"""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop

    def synthesize(self, text: str) -> Optional[bytes]:
        """同步合成语音"""
        loop = self._get_loop()
        return loop.run_until_complete(self.tts.synthesize(text))

    def speak(self, text: str):
        """同步播放语音"""
        loop = self._get_loop()
        loop.run_until_complete(self.tts.speak(text))


# 测试代码
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__file__).replace('\\', '/').rsplit('/', 3)[0])

    from src.voice.audio_device import AudioDevice

    # 测试配置（需要替换为真实的凭证）
    test_config = {
        "app_id": "YOUR_APP_ID",
        "access_token": "YOUR_ACCESS_TOKEN",
        "speaker": "BV002_streaming"
    }

    audio_config = {
        "sample_rate": 16000,
        "channels": 1
    }

    async def test():
        audio_dev = AudioDevice(audio_config)
        tts = VolcengineTTS(test_config, audio_dev)

        # 测试合成
        text = "你好，我是小可爱，很高兴认识你！"
        await tts.speak(text)

    asyncio.run(test())
