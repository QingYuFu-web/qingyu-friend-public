"""
双向语音对话管理器
实现持续监听 + 实时流式识别 + 声纹识别

核心特性：
1. 边说边识别 - 实时显示识别结果
2. 低延迟 - 边合成边播放
3. 声纹识别 - 自动识别说话人，陌生人主动询问
"""

import asyncio
import threading
import struct
import re
import sys
from typing import Optional
from queue import Queue, Empty

# 导入 ASR 结果类型
from src.voice.asr import ASRResult


class VoiceDialogManager:
    """双向语音对话管理器"""

    def __init__(self, brain, audio_device, vad, asr, tts, speaker_id=None):
        """
        初始化对话管理器

        Args:
            brain: AI大脑实例
            audio_device: 音频设备实例
            vad: VAD检测器实例
            asr: ASR识别器实例
            tts: TTS合成器实例
            speaker_id: 声纹识别器实例（可选）
        """
        self.brain = brain
        self.audio_device = audio_device
        self.vad = vad
        self.asr = asr
        self.tts = tts
        self.speaker_id = speaker_id

        # 状态控制
        self.is_speaking = False  # TTS是否在播放
        self.is_listening = False  # 是否正在识别用户语音
        self.running = True  # 是否继续运行
        self.wait_after_speak = 0  # 播放结束后等待时间（秒）
        self._aec_enabled = bool(getattr(self.audio_device, "aec", None) and self.audio_device.aec.enabled)

        # 声纹识别状态
        self.current_speaker_name = None  # 当前说话人名字
        self.awaiting_name = False  # 是否在等待用户告知名字

        # 实时识别相关
        self.audio_queue = None  # 音频数据队列（用于实时 ASR）
        self.stop_asr_event = None  # ASR 停止事件
        self.current_text = ""  # 当前识别的文本
        self.last_displayed_text = ""  # 上次显示的文本

        # 音频缓存（用于声纹识别）
        self.audio_buffer = []

        # 音频流
        self.audio_stream = None

        # 退出关键词
        self.exit_keywords = ['退出', '再见', '拜拜', '结束']

    async def run(self):
        """主运行入口"""
        print("=" * 50)
        print("  小可爱 - 双向语音对话模式（实时识别）")
        print("=" * 50)
        print()

        # 自我介绍
        intro = self.brain.introduce()
        print(f"🤖 {self.brain.persona.persona['name']}: {intro}")
        print()

        # 播放自我介绍
        await self._speak(intro, interruptible=False)

        print("=" * 50)
        print("  边说边识别模式已启动")
        print("  说\"退出\"或\"再见\"结束对话")
        print("=" * 50)
        print()

        # 启动音频流
        self.audio_stream = self.audio_device.start_stream()

        # 主循环
        try:
            await self._main_loop()
        except KeyboardInterrupt:
            print("\n\n正在退出...")
        finally:
            self.running = False
            self.audio_device.stop_stream()
            self.brain.memory.save_remaining()
            print("💾 记忆已保存")
            print("👋 再见！")

    async def _main_loop(self):
        """主循环：检测说话 → 实时识别 → 处理对话"""
        print("[DEBUG] 进入主循环")
        while self.running:
            try:
                # 没有 AEC 时，用“暂停监听 + 等待消散”规避回声；
                # 启用 AEC(ec) 后，允许外放同时监听（并在播报阶段做插话检测）。
                if not self._aec_enabled:
                    # TTS 播放时暂停
                    if self.is_speaking:
                        await asyncio.sleep(0.1)
                        continue

                    # 播放结束后等待回声消散
                    if self.wait_after_speak > 0:
                        await asyncio.sleep(0.1)
                        self.wait_after_speak -= 0.1
                        continue

                # 等待用户开始说话（使用 VAD 检测）
                print("🎤 等待说话...", flush=True)
                speech_started, pre_buffer = await self._wait_for_speech_start()

                if not speech_started or not self.running:
                    continue

                # 没有 AEC 时，播放期间不处理；AEC 启用时允许“边播边听”
                if self.is_speaking and not self._aec_enabled:
                    continue

                # 开始实时识别（传入预缓冲音频）
                print("🔊 开始实时识别...")
                final_text, audio_data = await self._realtime_recognize(pre_buffer)

                if not final_text:
                    print("⚠️ 未识别到有效内容")
                    continue

                # 处理识别结果
                await self._handle_speech(final_text, audio_data)

            except Exception as e:
                print(f"⚠️ 处理错误: {e}")
                import traceback
                traceback.print_exc()

    async def _wait_for_speech_start(self) -> tuple:
        """
        等待用户开始说话（使用 VAD 检测）

        Returns:
            (speech_started, pre_buffer) - 是否检测到语音，预缓冲的音频帧列表
        """
        # 预缓冲：保存最近的音频帧，防止丢失开头
        pre_buffer = []
        pre_buffer_max = 15  # 保留最近 15 帧（约 300ms）

        def read_and_check():
            """在线程中读取音频并检测语音（支持非整帧长度的 chunk）"""
            try:
                chunk = self.audio_stream.read()
                # AudioDevice.read() 返回的是任意长度 PCM bytes；
                # webrtcvad 只能处理 10/20/30ms 帧，因此这里按 VAD 的 frame_size 切分后做聚合判定。
                frame_size = getattr(self.vad, "frame_size", None)
                if not frame_size or frame_size <= 0:
                    is_speech = self.vad.is_speech(chunk)
                else:
                    frames = [chunk[i:i + frame_size] for i in range(0, len(chunk), frame_size)]
                    speech_votes = 0
                    total_votes = 0
                    for f in frames:
                        if len(f) < frame_size:
                            continue
                        total_votes += 1
                        if self.vad.is_speech(f):
                            speech_votes += 1
                    # 超过一半帧判为语音，降低误触发/漏检（尤其是外放环境）
                    is_speech = total_votes > 0 and (speech_votes / total_votes) >= 0.5
                return chunk, is_speech
            except:
                return None, False

        loop = asyncio.get_event_loop()
        consecutive_speech = 0
        # chunk_size 调整到 30ms 左右后，3 帧约 90ms；如果你觉得仍然慢，可降为 2。
        speech_threshold = 3  # 连续 N 帧检测到语音才认为开始说话

        while self.running and not self.is_speaking:
            try:
                chunk, is_speech = await loop.run_in_executor(None, read_and_check)

                if chunk:
                    # 添加到预缓冲
                    pre_buffer.append(chunk)
                    if len(pre_buffer) > pre_buffer_max:
                        pre_buffer.pop(0)

                if is_speech:
                    consecutive_speech += 1
                    if consecutive_speech >= speech_threshold:
                        return True, pre_buffer
                else:
                    consecutive_speech = 0

                await asyncio.sleep(0.02)
            except:
                return False, []

        return False, []

    async def _realtime_recognize(self, pre_buffer: list = None) -> tuple:
        """
        实时流式识别

        Args:
            pre_buffer: 预缓冲的音频帧列表（VAD检测期间收集的）

        Returns:
            (final_text, audio_data) - 最终文本和音频数据
        """
        # 初始化
        self.audio_queue = asyncio.Queue()
        self.stop_asr_event = asyncio.Event()
        self.current_text = ""
        self.last_displayed_text = ""
        self.audio_buffer = []
        self.is_listening = True

        # 先把预缓冲的音频加入队列和缓冲区
        if pre_buffer:
            for chunk in pre_buffer:
                self.audio_buffer.append(chunk)
                await self.audio_queue.put(chunk)

        final_text = ""

        def on_result(result: ASRResult):
            """识别结果回调"""
            nonlocal final_text
            self.current_text = result.text

            # 实时显示（覆盖上一行）
            if result.text != self.last_displayed_text:
                # 清除当前行并显示新文本
                display_text = result.text[:50] + "..." if len(result.text) > 50 else result.text
                prefix = "✅" if result.is_final else "📝"
                sys.stdout.write(f"\r{prefix} {display_text}                    ")
                sys.stdout.flush()
                self.last_displayed_text = result.text

            if result.is_final:
                final_text = result.text
                print()  # 换行

        # 启动音频发送任务
        audio_task = asyncio.create_task(self._send_audio_to_asr())

        # 启动 ASR 识别
        try:
            result = await self.asr.recognize_realtime(
                audio_queue=self.audio_queue,
                on_result=on_result,
                stop_event=self.stop_asr_event,
                end_window_size=800  # 800ms 静音判停
            )
            if result:
                final_text = result
        except Exception as e:
            print(f"\n⚠️ 识别错误: {e}")

        # 停止音频发送
        self.stop_asr_event.set()
        audio_task.cancel()
        try:
            await audio_task
        except asyncio.CancelledError:
            pass

        self.is_listening = False

        # 合并音频数据（用于声纹识别）
        audio_data = b''.join(self.audio_buffer) if self.audio_buffer else b''

        return final_text, audio_data

    async def _send_audio_to_asr(self):
        """持续从麦克风读取音频并发送给 ASR"""
        loop = asyncio.get_event_loop()

        def read_audio():
            try:
                return self.audio_stream.read()
            except:
                return None

        while not self.stop_asr_event.is_set() and self.running:
            try:
                # 在线程池中读取音频（阻塞操作）
                chunk = await loop.run_in_executor(None, read_audio)

                if chunk and not self.is_speaking:
                    # 保存到缓冲区（用于声纹识别）
                    self.audio_buffer.append(chunk)
                    # 发送给 ASR
                    await self.audio_queue.put(chunk)

                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                break
            except Exception as e:
                break

    async def _handle_speech(self, user_text: str, audio_data: bytes):
        """处理识别完成的语音"""
        print(f"\n📝 最终结果: {user_text}")

        # 如果在等待名字，直接处理注册流程
        if self.awaiting_name:
            await self._handle_name_response(user_text, audio_data)
            return

        # 声纹识别
        speaker_name = await self._identify_speaker(audio_data, user_text)

        # 如果触发了询问名字，直接返回
        if self.awaiting_name:
            return

        # 显示说话人
        if speaker_name:
            print(f"\n👤 {speaker_name}: {user_text}")
        else:
            print(f"\n👤 你: {user_text}")

        # 退出检测
        if any(kw in user_text for kw in self.exit_keywords):
            farewell = self.brain.chat("再见", speaker=speaker_name, debug=False)
            print(f"\n🤖 {self.brain.persona.persona['name']}: {farewell}")
            await self._speak(farewell, interruptible=False)
            self.running = False
            return

        # 对话
        reply = self.brain.chat(user_text, speaker=speaker_name, debug=False)
        print(f"\n🤖 {self.brain.persona.persona['name']}: {reply}")

        # 播放
        await self._speak(reply, interruptible=True)

        print("\n" + "-" * 30)

    async def _identify_speaker(self, audio_data: bytes, user_text: str) -> Optional[str]:
        """识别说话人"""
        if self.speaker_id is None or not audio_data:
            return self.current_speaker_name

        # 声纹识别
        speaker_id_result, similarity, embedding = self.speaker_id.identify(audio_data)

        if speaker_id_result:
            name = self.speaker_id.get_speaker_name(speaker_id_result)
            self.current_speaker_name = name
            print(f"🎯 声纹识别: {name} (相似度: {similarity:.2f})")

            if embedding is not None:
                self.speaker_id.update_embedding(speaker_id_result, embedding)

            return name
        else:
            if embedding is not None:
                print(f"❓ 未识别的声纹 (最高相似度: {similarity:.2f})")
                self.speaker_id.set_pending_registration(embedding)
                await self._ask_for_name()
                return None

        return self.current_speaker_name

    async def _ask_for_name(self):
        """询问陌生人的名字"""
        self.awaiting_name = True
        ask_text = "你好呀~我好像还不认识你呢，你叫什么名字呀？"
        print(f"\n🤖 {self.brain.persona.persona['name']}: {ask_text}")
        await self._speak(ask_text, interruptible=False)

    async def _handle_name_response(self, user_text: str, audio_data: bytes):
        """处理用户告知名字的回复"""
        print(f"\n👤 你: {user_text}")

        # 先尝试正则提取
        name = self._extract_name(user_text)

        # 如果正则失败，用AI理解意图
        if not name:
            result = await self._ai_understand_name(user_text)
            if result.get('is_name'):
                name = result.get('name')
            elif result.get('skip'):
                # 用户不想说名字，跳过注册
                print(f"📝 用户跳过注册")
                self.awaiting_name = False
                if self.speaker_id:
                    self.speaker_id.cancel_registration()
                reply = result.get('reply', "好的，那我们先聊别的吧~")
                print(f"\n🤖 {self.brain.persona.persona['name']}: {reply}")
                await self._speak(reply, interruptible=False)
                return
            elif result.get('other_intent'):
                # 用户在说别的事情，先回应再继续问名字
                print(f"📝 用户在说其他事情")
                reply = result.get('reply', "")
                if reply:
                    print(f"\n🤖 {self.brain.persona.persona['name']}: {reply}")
                    await self._speak(reply, interruptible=False)
                # 继续问名字
                ask_text = "对了，你还没告诉我你叫什么名字呢~"
                print(f"\n🤖 {self.brain.persona.persona['name']}: {ask_text}")
                await self._speak(ask_text, interruptible=False)
                return

        print(f"📝 提取名字: {name if name else '未识别到'}")

        if name:
            if self.speaker_id and self.speaker_id.has_pending_registration():
                self.speaker_id.complete_registration(name)
                self.current_speaker_name = name
                self.awaiting_name = False

                welcome = f"原来是{name}呀！很高兴认识你~我是小可爱，以后我就能认出你的声音啦！"
                print(f"\n🤖 {self.brain.persona.persona['name']}: {welcome}")
                await self._speak(welcome, interruptible=False)

                self.brain.memory.add_fact(f"认识了新朋友{name}，已记住ta的声纹")
            else:
                self.awaiting_name = False
        else:
            retry_text = "抱歉，我没听清楚你的名字，能再说一次吗？你也可以说'算了'跳过~"
            print(f"\n🤖 {self.brain.persona.persona['name']}: {retry_text}")
            await self._speak(retry_text, interruptible=False)

    async def _ai_understand_name(self, user_text: str) -> dict:
        """用AI理解用户是否在说名字"""
        prompt = f"""用户刚才被问"你叫什么名字"，回答了："{user_text}"

请判断：
1. 用户是否在告诉自己的名字？
2. 如果是，名字是什么？
3. 如果不是，用户是想跳过（如"算了""不说了"），还是在说其他事情？

请用JSON格式回答（不要有其他内容）：
{{"is_name": true/false, "name": "名字或null", "skip": true/false, "other_intent": true/false, "reply": "如果用户在说其他事情，简短回应"}}"""

        try:
            # 调用AI（使用较短的max_tokens加快响应）
            from openai import OpenAI
            import json

            # 复用brain的客户端配置
            if hasattr(self.brain, 'client') and self.brain.client:
                response = self.brain.client.chat.completions.create(
                    model=self.brain.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=150
                )
                result_text = response.choices[0].message.content.strip()

                # 解析JSON
                # 处理可能的markdown代码块
                if result_text.startswith('```'):
                    result_text = result_text.split('```')[1]
                    if result_text.startswith('json'):
                        result_text = result_text[4:]
                    result_text = result_text.strip()

                return json.loads(result_text)
        except Exception as e:
            print(f"⚠️ AI理解失败: {e}")

        return {"is_name": False, "name": None, "skip": False, "other_intent": False}

    def _extract_name(self, text: str) -> Optional[str]:
        """从文本中提取名字"""
        text = text.strip()
        text = re.sub(r'(我是|我叫){2,}', r'\1', text)

        patterns = [
            r"我(?:是|叫|的名字是|名叫)[\s]*([^\s,，。！!？?我是叫]{2,4})",
            r"叫我[\s]*([^\s,，。！!？?]{2,4})",
            r"^([^\s,，。！!？?我是叫]{2,4})$",
        ]

        # 无效词列表
        skip_words = [
            '什么', '谁', '你好', '嗯', '啊', '哦', '呃', '那个', '这个',
            '干嘛', '怎么', '好的', '知道', '可以', '不是', '没有',
            '退出', '再见', '拜拜', '结束', '停止', '关闭'
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip()
                # 去掉标点后检查
                clean_name = re.sub(r'[？?！!。，,、]', '', name)
                if 1 < len(clean_name) <= 4:
                    if clean_name not in skip_words and not clean_name.endswith('吗'):
                        return clean_name

        clean_text = re.sub(r'^(我是|我叫|叫我|我的名字是)+', '', text).strip()
        clean_text = re.sub(r'[？?！!。，,、]', '', clean_text)
        if 2 <= len(clean_text) <= 4:
            if clean_text not in skip_words and not clean_text.endswith('吗'):
                return clean_text

        return None

    async def _speak(self, text: str, interruptible: bool = True):
        """语音播放"""
        self.is_speaking = True

        try:
            print(f"🗣️ 播放: {text[:30]}...")

            buffer = b''
            buffer_threshold = 3200

            async for chunk in self.tts.synthesize_stream(text):
                buffer += chunk

                if len(buffer) >= buffer_threshold:
                    self.audio_device.play_audio(buffer)
                    buffer = b''

                    # AEC 启用时尝试“可插话”：播报期间快速做 VAD 检测
                    if interruptible and self._aec_enabled and self.audio_stream:
                        if await self._barge_in_check():
                            print("\n⚡ 检测到插话，停止播报")
                            break

            if buffer:
                self.audio_device.play_audio(buffer)

            print("✅ 播放完成")

        except Exception as e:
            print(f"⚠️ TTS播放失败: {e}")

        finally:
            self.is_speaking = False
            # 无 AEC 时等待回声消散；启用 AEC 则不再依赖等待策略
            if self._aec_enabled:
                self.wait_after_speak = 0
            else:
                self.wait_after_speak = 0.5

    async def _barge_in_check(self) -> bool:
        """
        播放期间快速检测是否有人插话。

        说明：
        - AEC 启用时，AudioStream 读取的是 /tmp/ec.output（已消回声），更适合做插话检测。
        - 这里只做轻量投票：读取少量帧，超过阈值认为在说话。
        """
        if not self.audio_stream:
            return False

        loop = asyncio.get_event_loop()

        def read_chunk():
            try:
                return self.audio_stream.read()
            except Exception:
                return b""

        votes = 0
        total = 0

        # 读取两次，通常约 2 * chunk_size（chunk_size 默认 30ms）
        for _ in range(2):
            chunk = await loop.run_in_executor(None, read_chunk)
            if not chunk:
                continue

            frame_size = getattr(self.vad, "frame_size", None)
            if not frame_size:
                total += 1
                if self.vad.is_speech(chunk):
                    votes += 1
                continue

            for i in range(0, len(chunk), frame_size):
                frame = chunk[i:i + frame_size]
                if len(frame) < frame_size:
                    continue
                total += 1
                if self.vad.is_speech(frame):
                    votes += 1

        if total == 0:
            return False

        return (votes / total) >= 0.6
