"""
豆包语音识别模块 (ASR)
使用火山引擎WebSocket API实现语音转文本

支持两种模式：
1. 批量识别：录完整段后识别
2. 实时流式：边说边识别（推荐）

参考文档：https://www.volcengine.com/docs/6561/1354869
"""

import asyncio
import json
import uuid
import gzip
import websockets
import ssl
from typing import Optional, AsyncGenerator, Callable
from dataclasses import dataclass


@dataclass
class ASRResult:
    """ASR 识别结果"""
    text: str           # 识别文本
    is_final: bool      # 是否为最终结果（definite）
    is_end: bool        # 是否结束（用户停止说话）


class VolcengineASR:
    """火山引擎语音识别客户端"""

    # WebSocket API地址 (优化版，性能更优)
    WSS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"

    # 消息类型常量
    FULL_CLIENT_REQUEST = 0b0001   # 完整客户端请求 (msg_type=1)
    AUDIO_ONLY_REQUEST = 0b0010    # 仅音频请求 (msg_type=2)
    FULL_SERVER_RESPONSE = 0b1001  # 完整服务器响应
    SERVER_ACK = 0b1011            # 服务器确认

    # 序列化方式
    NO_SERIALIZATION = 0b0000
    JSON_SERIALIZATION = 0b0001

    # 压缩方式
    NO_COMPRESSION = 0b0000
    GZIP_COMPRESSION = 0b0001

    def __init__(self, config: dict):
        """
        初始化ASR客户端

        Args:
            config: ASR配置，包含：
                - app_id: 应用ID (X-Api-App-Key)
                - access_token: 访问令牌 (X-Api-Access-Key)
                - language: 语言（默认 zh-CN）
                - format: 音频格式（默认 pcm）
                - sample_rate: 采样率（默认 16000）
                - bits: 位深（默认 16）
                - channels: 声道数（默认 1）
                - hotwords: 热词列表（可选）
        """
        self.app_id = config.get('app_id', '')
        self.access_token = config.get('access_token', '')
        self.language = config.get('language', 'zh-CN')
        self.format = config.get('format', 'pcm')
        self.sample_rate = config.get('sample_rate', 16000)
        self.bits = config.get('bits', 16)
        self.channels = config.get('channels', 1)

        # 热词配置（提高专有名词识别准确率）
        self.hotwords = config.get('hotwords', [
            "清于", "付清于", "付晨辉", "冯桂荣",
            "小可爱", "爸爸", "妈妈"
        ])

        # 后处理纠错映射（ASR 常见误识别）
        self.corrections = config.get('corrections', {
            # 清于的各种误识别
            "青鱼": "清于",
            "生鱼": "清于",
            "清鱼": "清于",
            "晴雨": "清于",
            "清雨": "清于",
            "诗雨": "清于",
            # 付清于的各种误识别
            "傅清宇": "付清于",
            "付青鱼": "付清于",
            "付清鱼": "付清于",
            "付清雨": "付清于",
        })

        # SSL配置
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

        print(f"🎤 ASR客户端初始化:")
        print(f"   语言: {self.language}")
        print(f"   采样率: {self.sample_rate} Hz")
        print(f"   热词: {', '.join(self.hotwords[:5])}...")

    def _post_correct(self, text: str) -> str:
        """后处理纠错"""
        if not text:
            return text

        # 词汇替换
        for wrong, correct in self.corrections.items():
            text = text.replace(wrong, correct)

        return text

    def _build_header(self, msg_type: int, msg_flags: int = 0,
                      serialization: int = None, compression: int = None) -> bytes:
        """构建协议头"""
        if serialization is None:
            serialization = self.JSON_SERIALIZATION if msg_type == self.FULL_CLIENT_REQUEST else self.NO_SERIALIZATION
        if compression is None:
            compression = self.GZIP_COMPRESSION

        header = bytes([
            0x11,
            (msg_type << 4) | msg_flags,
            (serialization << 4) | compression,
            0x00
        ])
        return header

    def _build_full_request(self, request_id: str, end_window_size: int = 500) -> bytes:
        """构建完整请求（首包）"""
        # 构建热词 context（正确格式）
        hotwords_list = [{"word": w} for w in self.hotwords]
        context_str = json.dumps({"hotwords": hotwords_list})

        payload = {
            "user": {
                "uid": request_id
            },
            "audio": {
                "format": self.format,
                "rate": self.sample_rate,
                "bits": self.bits,
                "channel": self.channels,
                "codec": "raw"
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True,
                "enable_itn": True,
                "enable_ddc": True,  # 语义顺滑，删除口语重复
                "result_type": "single",
                "end_window_size": end_window_size,  # 静音判停时间(ms)，降低延迟
                "show_utterances": True,
                "context": context_str  # 热词配置（正确格式）
            }
        }

        payload_bytes = json.dumps(payload).encode('utf-8')
        compressed = gzip.compress(payload_bytes)

        header = self._build_header(
            msg_type=self.FULL_CLIENT_REQUEST,
            msg_flags=0,
            serialization=self.JSON_SERIALIZATION,
            compression=self.GZIP_COMPRESSION
        )
        payload_size = len(compressed).to_bytes(4, 'big')

        return header + payload_size + compressed

    def _build_audio_request(self, audio_data: bytes, is_last: bool = False) -> bytes:
        """构建音频请求"""
        compressed_audio = gzip.compress(audio_data)

        msg_flags = 0x02 if is_last else 0x00
        header = self._build_header(
            msg_type=self.AUDIO_ONLY_REQUEST,
            msg_flags=msg_flags,
            serialization=self.NO_SERIALIZATION,
            compression=self.GZIP_COMPRESSION
        )

        payload_size = len(compressed_audio).to_bytes(4, 'big')

        return header + payload_size + compressed_audio

    def _parse_response(self, data: bytes) -> dict:
        """解析响应数据"""
        if len(data) < 4:
            return {"error": "响应数据太短"}

        msg_type = data[1] & 0x0F
        header_size = ((data[1] >> 4) & 0x0F) * 4

        # 尝试直接找到 JSON 数据
        json_start = data.find(b'{')
        if json_start != -1:
            try:
                json_data = data[json_start:].decode('utf-8', errors='ignore')
                brace_count = 0
                json_end = json_start
                for i, char in enumerate(json_data):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break
                return json.loads(json_data[:json_end])
            except:
                pass

        # 尝试找到 GZIP 数据并解压
        gzip_magic = bytes([0x1f, 0x8b, 0x08])
        gzip_pos = data.find(gzip_magic)
        if gzip_pos != -1:
            try:
                decompressed = gzip.decompress(data[gzip_pos:])
                return json.loads(decompressed.decode('utf-8'))
            except:
                pass

        # 标准解析方式（备用）
        if len(data) > header_size + 4:
            payload_size = int.from_bytes(data[header_size:header_size + 4], 'big')
            if payload_size < len(data) and payload_size > 0:
                payload = data[header_size + 4:header_size + 4 + payload_size]
                try:
                    decompressed = gzip.decompress(payload)
                    return json.loads(decompressed.decode('utf-8'))
                except:
                    try:
                        return json.loads(payload.decode('utf-8'))
                    except:
                        pass

        return {"msg_type": msg_type, "raw": data[header_size:]}

    def _extract_result(self, resp_data: dict) -> Optional[ASRResult]:
        """从响应中提取识别结果"""
        if not isinstance(resp_data, dict):
            return None

        text = ""
        is_final = False

        if "result" in resp_data:
            result = resp_data["result"]

            # 提取文本
            if isinstance(result, dict):
                text = result.get("text", "")

                # 检查 utterances
                utterances = result.get("utterances", [])
                for utt in utterances:
                    if isinstance(utt, dict) and "text" in utt:
                        text = utt["text"]
                        if utt.get("definite", False):
                            is_final = True

            elif isinstance(result, list):
                for item in result:
                    if isinstance(item, dict) and "text" in item:
                        text = item["text"]
                        if item.get("definite", False):
                            is_final = True

        if text:
            # 后处理纠错
            text = self._post_correct(text)
            return ASRResult(text=text, is_final=is_final, is_end=is_final)
        return None

    async def recognize_realtime(
        self,
        audio_queue: asyncio.Queue,
        on_result: Callable[[ASRResult], None],
        stop_event: asyncio.Event,
        end_window_size: int = 500
    ) -> Optional[str]:
        """
        实时流式识别（边说边识别）

        Args:
            audio_queue: 音频数据队列，持续放入音频块
            on_result: 识别结果回调（实时调用）
            stop_event: 停止事件，设置后结束识别
            end_window_size: 静音判停时间(ms)，默认500ms（更快响应）

        Returns:
            最终识别结果文本
        """
        request_id = str(uuid.uuid4())

        headers = {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Access-Key": self.access_token,
            "X-Api-App-Key": self.app_id,
            "X-Api-Request-Id": request_id
        }

        final_text = ""
        ws = None

        try:
            ws = await websockets.connect(
                self.WSS_URL,
                additional_headers=headers,
                ssl=self.ssl_context,
                max_size=1000000000,
                ping_interval=None
            )

            # 发送首包
            full_request = self._build_full_request(request_id, end_window_size)
            await ws.send(full_request)

            # 等待确认
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            resp_data = self._parse_response(response)
            if "error" in resp_data:
                print(f"❌ ASR初始化失败: {resp_data}")
                return None

            # 发送音频的任务
            async def send_audio():
                while not stop_event.is_set():
                    try:
                        # 非阻塞获取音频
                        audio_chunk = await asyncio.wait_for(
                            audio_queue.get(),
                            timeout=0.1
                        )
                        if audio_chunk:
                            audio_request = self._build_audio_request(audio_chunk, False)
                            await ws.send(audio_request)
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        break

                # 发送结束标志
                try:
                    end_request = self._build_audio_request(b'', True)
                    await ws.send(end_request)
                except:
                    pass

            # 接收结果的任务
            async def receive_results():
                nonlocal final_text
                while True:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=15)
                        resp_data = self._parse_response(response)

                        result = self._extract_result(resp_data)
                        if result:
                            final_text = result.text
                            on_result(result)

                            if result.is_final:
                                stop_event.set()
                                return

                    except asyncio.TimeoutError:
                        # 超时，可能用户没说话
                        stop_event.set()
                        return
                    except websockets.ConnectionClosed:
                        return
                    except Exception as e:
                        print(f"⚠️ 接收结果错误: {e}")
                        return

            # 并行执行发送和接收
            send_task = asyncio.create_task(send_audio())
            recv_task = asyncio.create_task(receive_results())

            # 等待接收任务完成（它会在收到最终结果时结束）
            await recv_task

            # 取消发送任务
            send_task.cancel()
            try:
                await send_task
            except asyncio.CancelledError:
                pass

        except Exception as e:
            print(f"❌ ASR实时识别失败: {e}")
            return None

        finally:
            if ws:
                await ws.close()

        return final_text

    async def recognize(self, audio_data: bytes) -> str:
        """
        批量识别音频数据（兼容旧接口）

        Args:
            audio_data: PCM音频数据

        Returns:
            识别结果文本
        """
        request_id = str(uuid.uuid4())

        headers = {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Access-Key": self.access_token,
            "X-Api-App-Key": self.app_id,
            "X-Api-Request-Id": request_id
        }

        result_text = ""

        try:
            async with websockets.connect(
                self.WSS_URL,
                additional_headers=headers,
                ssl=self.ssl_context,
                max_size=1000000000,
                ping_interval=None
            ) as ws:
                # 发送首包
                full_request = self._build_full_request(request_id)
                await ws.send(full_request)

                # 等待确认
                response = await asyncio.wait_for(ws.recv(), timeout=10)
                resp_data = self._parse_response(response)

                if "error" in resp_data:
                    print(f"❌ ASR初始化失败: {resp_data}")
                    return ""

                # 分块发送音频
                chunk_size = 3200
                for i in range(0, len(audio_data), chunk_size):
                    chunk = audio_data[i:i + chunk_size]
                    is_last = (i + chunk_size >= len(audio_data))
                    audio_request = self._build_audio_request(chunk, is_last)
                    await ws.send(audio_request)
                    await asyncio.sleep(0.02)

                # 接收结果
                while True:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=30)
                        resp_data = self._parse_response(response)

                        result = self._extract_result(resp_data)
                        if result:
                            result_text = result.text
                            if result.is_final:
                                break

                    except asyncio.TimeoutError:
                        break
                    except websockets.ConnectionClosed:
                        break

        except Exception as e:
            print(f"❌ ASR连接失败: {e}")
            return ""

        return result_text.strip()


# 同步包装器
class VolcengineASRSync:
    """ASR同步包装器"""

    def __init__(self, config: dict):
        self.asr = VolcengineASR(config)
        self._loop = None

    def _get_loop(self):
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop

    def recognize(self, audio_data: bytes) -> str:
        loop = self._get_loop()
        return loop.run_until_complete(self.asr.recognize(audio_data))
