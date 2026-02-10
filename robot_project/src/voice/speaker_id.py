"""
声纹识别模块
实现说话人识别、注册和管理

特性：
1. 自动识别已注册说话人
2. 检测陌生声纹并触发询问
3. 声纹渐进式更新（适应声音变化）
"""

import os
import json
import numpy as np
from typing import Optional, Tuple, Dict, List
from pathlib import Path

# 尝试导入 resemblyzer
try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    RESEMBLYZER_AVAILABLE = True
except ImportError:
    RESEMBLYZER_AVAILABLE = False
    print("⚠️ resemblyzer 未安装，声纹识别功能不可用")
    print("   安装命令: pip install resemblyzer")


class SpeakerIdentifier:
    """声纹识别器"""

    def __init__(self, data_dir: str = "data/speakers"):
        """
        初始化声纹识别器

        Args:
            data_dir: 声纹数据存储目录
        """
        self.data_dir = Path(data_dir)
        self.embeddings_dir = self.data_dir / "embeddings"
        self.config_file = self.data_dir / "speakers.json"

        # 创建目录
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.embeddings_dir.mkdir(parents=True, exist_ok=True)

        # 加载声纹编码器
        self.encoder = None
        if RESEMBLYZER_AVAILABLE:
            print("🔊 加载声纹识别模型...")
            self.encoder = VoiceEncoder()
            print("✅ 声纹识别模型加载完成")

        # 加载已注册的说话人
        self.speakers: Dict[str, dict] = {}
        self.embeddings: Dict[str, np.ndarray] = {}
        self._load_speakers()

        # 识别阈值
        self.similarity_threshold = 0.90  # 相似度阈值，低于此值认为是陌生人
        self.update_weight = 0.1  # 声纹更新权重（渐进式更新）

        # 当前说话人（用于多轮对话）
        self.current_speaker: Optional[str] = None
        self.pending_registration: Optional[np.ndarray] = None  # 待注册的声纹

    def _load_speakers(self):
        """加载已注册的说话人"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.speakers = json.load(f)

                # 加载声纹向量
                for speaker_id in self.speakers:
                    emb_file = self.embeddings_dir / f"{speaker_id}.npy"
                    if emb_file.exists():
                        self.embeddings[speaker_id] = np.load(emb_file)

                print(f"📋 已加载 {len(self.speakers)} 个声纹")
                for sid, info in self.speakers.items():
                    print(f"   - {info.get('name', sid)}")

            except Exception as e:
                print(f"⚠️ 加载声纹数据失败: {e}")
                self.speakers = {}
                self.embeddings = {}
        else:
            print("📋 暂无已注册声纹")

    def _save_speakers(self):
        """保存说话人信息"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.speakers, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存声纹数据失败: {e}")

    def _save_embedding(self, speaker_id: str, embedding: np.ndarray):
        """保存声纹向量"""
        emb_file = self.embeddings_dir / f"{speaker_id}.npy"
        np.save(emb_file, embedding)

    def extract_embedding(self, audio_data: bytes, sample_rate: int = 16000) -> Optional[np.ndarray]:
        """
        从音频数据提取声纹特征

        Args:
            audio_data: PCM 音频数据 (16-bit)
            sample_rate: 采样率

        Returns:
            256维声纹向量，失败返回 None
        """
        if not RESEMBLYZER_AVAILABLE or self.encoder is None:
            return None

        try:
            # 将 bytes 转换为 numpy 数组
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
            audio_np = audio_np / 32768.0  # 归一化到 [-1, 1]

            # 检查音频长度（至少需要 1 秒）
            min_samples = sample_rate * 1
            if len(audio_np) < min_samples:
                print("⚠️ 音频太短，无法提取声纹")
                return None

            # 预处理并提取声纹
            # resemblyzer 期望采样率为 16000
            if sample_rate != 16000:
                # 简单的重采样（实际项目中应使用 librosa）
                ratio = 16000 / sample_rate
                audio_np = np.interp(
                    np.arange(0, len(audio_np) * ratio) / ratio,
                    np.arange(len(audio_np)),
                    audio_np
                ).astype(np.float32)

            # 提取声纹嵌入
            embedding = self.encoder.embed_utterance(audio_np)
            return embedding

        except Exception as e:
            print(f"⚠️ 声纹提取失败: {e}")
            return None

    def identify(self, audio_data: bytes, sample_rate: int = 16000) -> Tuple[Optional[str], float, Optional[np.ndarray]]:
        """
        识别说话人

        Args:
            audio_data: PCM 音频数据
            sample_rate: 采样率

        Returns:
            (speaker_id, similarity, embedding)
            - speaker_id: 说话人ID，陌生人返回 None
            - similarity: 相似度分数
            - embedding: 提取的声纹向量
        """
        # 提取声纹
        embedding = self.extract_embedding(audio_data, sample_rate)
        if embedding is None:
            return None, 0.0, None

        # 如果没有已注册声纹，直接返回陌生人
        if not self.embeddings:
            return None, 0.0, embedding

        # 与所有已注册声纹比对
        best_match = None
        best_similarity = 0.0

        for speaker_id, registered_emb in self.embeddings.items():
            # 余弦相似度
            similarity = np.dot(embedding, registered_emb) / (
                np.linalg.norm(embedding) * np.linalg.norm(registered_emb)
            )

            if similarity > best_similarity:
                best_similarity = similarity
                best_match = speaker_id

        # 判断是否为已知说话人
        if best_similarity >= self.similarity_threshold:
            self.current_speaker = best_match
            return best_match, best_similarity, embedding
        else:
            return None, best_similarity, embedding

    def register(self, name: str, embedding: np.ndarray, extra_info: dict = None) -> str:
        """
        注册新说话人

        Args:
            name: 说话人名字
            embedding: 声纹向量
            extra_info: 额外信息（如关系、备注等）

        Returns:
            speaker_id
        """
        # 生成唯一ID
        speaker_id = name.lower().replace(" ", "_")
        base_id = speaker_id
        counter = 1
        while speaker_id in self.speakers:
            speaker_id = f"{base_id}_{counter}"
            counter += 1

        # 保存信息
        speaker_info = {
            "name": name,
            "registered_at": self._get_timestamp(),
            "updated_at": self._get_timestamp(),
            "interaction_count": 1
        }
        if extra_info:
            speaker_info.update(extra_info)

        self.speakers[speaker_id] = speaker_info
        self.embeddings[speaker_id] = embedding

        # 持久化
        self._save_speakers()
        self._save_embedding(speaker_id, embedding)

        self.current_speaker = speaker_id
        self.pending_registration = None

        print(f"✅ 已注册新声纹: {name} (ID: {speaker_id})")
        return speaker_id

    def update_embedding(self, speaker_id: str, new_embedding: np.ndarray):
        """
        渐进式更新声纹（适应声音变化）

        Args:
            speaker_id: 说话人ID
            new_embedding: 新的声纹向量
        """
        if speaker_id not in self.embeddings:
            return

        # 加权平均更新
        old_embedding = self.embeddings[speaker_id]
        updated = (1 - self.update_weight) * old_embedding + self.update_weight * new_embedding
        # 归一化
        updated = updated / np.linalg.norm(updated)

        self.embeddings[speaker_id] = updated
        self._save_embedding(speaker_id, updated)

        # 更新交互信息
        if speaker_id in self.speakers:
            self.speakers[speaker_id]["updated_at"] = self._get_timestamp()
            self.speakers[speaker_id]["interaction_count"] = \
                self.speakers[speaker_id].get("interaction_count", 0) + 1
            self._save_speakers()

    def get_speaker_name(self, speaker_id: str) -> Optional[str]:
        """获取说话人名字"""
        if speaker_id in self.speakers:
            return self.speakers[speaker_id].get("name")
        return None

    def get_speaker_info(self, speaker_id: str) -> Optional[dict]:
        """获取说话人完整信息"""
        return self.speakers.get(speaker_id)

    def list_speakers(self) -> List[dict]:
        """列出所有已注册说话人"""
        result = []
        for speaker_id, info in self.speakers.items():
            result.append({
                "id": speaker_id,
                "name": info.get("name", speaker_id),
                "interaction_count": info.get("interaction_count", 0)
            })
        return result

    def delete_speaker(self, speaker_id: str) -> bool:
        """删除说话人"""
        if speaker_id not in self.speakers:
            return False

        del self.speakers[speaker_id]
        if speaker_id in self.embeddings:
            del self.embeddings[speaker_id]

        # 删除文件
        emb_file = self.embeddings_dir / f"{speaker_id}.npy"
        if emb_file.exists():
            emb_file.unlink()

        self._save_speakers()
        print(f"🗑️ 已删除声纹: {speaker_id}")
        return True

    def set_pending_registration(self, embedding: np.ndarray):
        """设置待注册的声纹（等待用户告知名字）"""
        self.pending_registration = embedding

    def has_pending_registration(self) -> bool:
        """是否有待注册的声纹"""
        return self.pending_registration is not None

    def complete_registration(self, name: str, extra_info: dict = None) -> Optional[str]:
        """
        完成待注册声纹的注册

        Args:
            name: 说话人名字
            extra_info: 额外信息

        Returns:
            speaker_id，失败返回 None
        """
        if self.pending_registration is None:
            return None

        speaker_id = self.register(name, self.pending_registration, extra_info)
        return speaker_id

    def cancel_registration(self):
        """取消待注册"""
        self.pending_registration = None

    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# 测试代码
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from src.voice.audio_device import AudioDevice

    # 初始化
    speaker_id = SpeakerIdentifier()
    audio_config = {"sample_rate": 16000, "channels": 1}
    audio_dev = AudioDevice(audio_config)

    print("\n=== 声纹识别测试 ===\n")

    # 列出已注册声纹
    speakers = speaker_id.list_speakers()
    if speakers:
        print("已注册声纹:")
        for s in speakers:
            print(f"  - {s['name']} (交互次数: {s['interaction_count']})")
    else:
        print("暂无已注册声纹")

    print("\n请说话 (3秒)...")
    audio_data = audio_dev.record_audio(duration=3)

    # 识别
    sid, similarity, embedding = speaker_id.identify(audio_data)
    if sid:
        name = speaker_id.get_speaker_name(sid)
        print(f"\n✅ 识别结果: {name} (相似度: {similarity:.2f})")
        # 更新声纹
        speaker_id.update_embedding(sid, embedding)
    else:
        print(f"\n❓ 未识别出已知说话人 (最高相似度: {similarity:.2f})")
        if embedding is not None:
            name = input("请输入你的名字进行注册: ").strip()
            if name:
                speaker_id.register(name, embedding)
