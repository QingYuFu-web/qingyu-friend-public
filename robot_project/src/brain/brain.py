# AI成长机器人 - AI大脑模块
# 包含对话、记忆、人格功能

import chromadb
from datetime import datetime
import json
import os
import time
import re

# API 客户端（延迟导入）
ollama = None
openai = None


def get_ollama():
    """延迟加载 ollama"""
    global ollama
    if ollama is None:
        import ollama as _ollama
        ollama = _ollama
    return ollama


def get_openai():
    """延迟加载 openai"""
    global openai
    if openai is None:
        from openai import OpenAI
        openai = OpenAI
    return openai


class Memory:
    """分层记忆系统 - 优化版"""

    # 记忆类型
    TYPE_FACT = "fact"          # 事实记忆：生日、喜好、重要信息
    TYPE_CONVERSATION = "conv"   # 对话记忆：日常闲聊

    # 事实关键词（用于自动识别重要信息）
    FACT_KEYWORDS = [
        "生日", "birthday", "喜欢", "讨厌", "爱吃", "不吃",
        "过敏", "工作", "学校", "年级", "岁", "住在", "电话",
        "记住", "记得", "别忘了", "重要"
    ]

    def __init__(self, db_path="data/memory", similarity_threshold=2.0):
        """
        初始化记忆系统

        Args:
            db_path: 数据库路径
            similarity_threshold: 相似度阈值，ChromaDB 使用 L2 距离，越小越相似
                                  建议值 1.0-3.0，超过此值的记忆不会被召回
        """
        self.client = chromadb.PersistentClient(path=db_path)
        self.similarity_threshold = similarity_threshold

        # 长期对话记忆
        self.conversations = self.client.get_or_create_collection(
            name="long_term_memory",
            metadata={"description": "对话记忆"}
        )

        # 重要事实记忆（单独存储，优先级更高）
        self.facts = self.client.get_or_create_collection(
            name="important_facts",
            metadata={"description": "重要事实记忆"}
        )

        # 短期记忆（最近对话）
        self.short_term = []
        self.max_short_term = 10  # 保留最近10轮对话

    def _is_fact(self, text: str) -> bool:
        """判断是否包含重要事实信息"""
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.FACT_KEYWORDS)

    def _estimate_tokens(self, text: str) -> int:
        """估算文本的 token 数（中文约1.5字符/token，英文约4字符/token）"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)

    def add_conversation(self, user_msg: str, bot_reply: str):
        """添加一轮对话到记忆"""
        timestamp = datetime.now().isoformat()

        # 添加到短期记忆
        self.short_term.append({
            "role": "user",
            "content": user_msg,
            "time": timestamp
        })
        self.short_term.append({
            "role": "assistant",
            "content": bot_reply,
            "time": timestamp
        })

        # 检查是否包含重要事实，立即存入事实记忆
        if self._is_fact(user_msg):
            self._save_fact(user_msg, timestamp)

        # 保持短期记忆长度
        if len(self.short_term) > self.max_short_term * 2:
            old_conversation = self.short_term[:2]
            self._save_to_long_term(old_conversation)
            self.short_term = self.short_term[2:]

    def _save_fact(self, content: str, timestamp: str):
        """保存重要事实到事实记忆库"""
        doc_id = f"fact_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.facts.add(
            documents=[content],
            ids=[doc_id],
            metadatas=[{"time": timestamp, "type": self.TYPE_FACT}]
        )

    def add_fact(self, content: str):
        """手动添加重要事实（供外部调用）"""
        self._save_fact(content, datetime.now().isoformat())

    def _save_to_long_term(self, conversation: list):
        """保存到长期对话记忆"""
        content = f"用户说：{conversation[0]['content']}\n机器人回复：{conversation[1]['content']}"
        doc_id = f"conv_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

        self.conversations.add(
            documents=[content],
            ids=[doc_id],
            metadatas=[{"time": conversation[0]['time'], "type": self.TYPE_CONVERSATION}]
        )

    def search_memory(self, query: str, n_results: int = 3, token_budget: int = 500) -> dict:
        """
        搜索相关记忆（带相似度过滤和 token 预算）

        Args:
            query: 查询文本
            n_results: 最大返回条数
            token_budget: token 预算，超出则截断

        Returns:
            {"facts": [...], "conversations": [...], "total_tokens": int}
        """
        result = {"facts": [], "conversations": [], "total_tokens": 0}

        # 1. 优先搜索事实记忆（重要信息）
        if self.facts.count() > 0:
            fact_results = self.facts.query(
                query_texts=[query],
                n_results=min(3, self.facts.count()),
                include=["documents", "distances"]
            )

            if fact_results['documents'] and fact_results['documents'][0]:
                for doc, dist in zip(fact_results['documents'][0], fact_results['distances'][0]):
                    if dist < self.similarity_threshold:
                        tokens = self._estimate_tokens(doc)
                        if result["total_tokens"] + tokens <= token_budget:
                            result["facts"].append(doc)
                            result["total_tokens"] += tokens

        # 2. 搜索对话记忆
        if self.conversations.count() > 0:
            conv_results = self.conversations.query(
                query_texts=[query],
                n_results=min(n_results, self.conversations.count()),
                include=["documents", "distances"]
            )

            if conv_results['documents'] and conv_results['documents'][0]:
                for doc, dist in zip(conv_results['documents'][0], conv_results['distances'][0]):
                    # 相似度过滤
                    if dist < self.similarity_threshold:
                        tokens = self._estimate_tokens(doc)
                        if result["total_tokens"] + tokens <= token_budget:
                            result["conversations"].append(doc)
                            result["total_tokens"] += tokens

        return result

    def get_short_term(self, token_budget: int = 800) -> list:
        """获取短期记忆（带 token 预算控制）"""
        if not self.short_term:
            return []

        # 从最新的开始，倒序添加直到超出预算
        result = []
        total_tokens = 0

        for msg in reversed(self.short_term):
            tokens = self._estimate_tokens(msg["content"])
            if total_tokens + tokens > token_budget:
                break
            result.insert(0, msg)
            total_tokens += tokens

        return result

    def save_remaining(self):
        """保存剩余的短期记忆"""
        while len(self.short_term) >= 2:
            old_conversation = self.short_term[:2]
            self._save_to_long_term(old_conversation)
            self.short_term = self.short_term[2:]

    def get_stats(self) -> dict:
        """获取记忆统计信息"""
        return {
            "short_term_count": len(self.short_term) // 2,
            "conversation_count": self.conversations.count(),
            "fact_count": self.facts.count()
        }


class Persona:
    """人格系统"""
    
    def __init__(self, config_path="config/persona.json"):
        self.config_path = config_path
        self.persona = self._load_or_create()
    
    def _load_or_create(self) -> dict:
        """加载或创建默认人格"""
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # 默认人格
        default = {
            "name": "小可爱",
            "personality": "友善、温暖、有耐心",
            "speaking_style": "亲切自然，像朋友一样交流",
            "background": "我是一个AI成长伙伴，陪伴你学习和成长",
            "owner": {
                "name": "",
                "preferences": []
            }
        }
        
        # 保存默认配置
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
        
        return default
    
    def get_system_prompt(self) -> str:
        """生成系统提示词"""
        p = self.persona

        # 基础身份
        prompt = f"""【我是谁】
我叫{p['name']}，{p.get('identity', '一个AI伙伴')}。
生日：{p.get('birthday', '未知')}

{p.get('background', '')}

"""
        # 性格特点
        personality = p.get('personality', {})
        if isinstance(personality, dict):
            if personality.get('traits'):
                prompt += f"【我的性格】\n{', '.join(personality['traits'])}\n"
            if personality.get('likes'):
                prompt += f"喜欢：{', '.join(personality['likes'])}\n"
            if personality.get('dislikes'):
                prompt += f"不喜欢：{', '.join(personality['dislikes'])}\n"
        else:
            prompt += f"【我的性格】\n{personality}\n"

        prompt += f"\n【说话风格】\n{p.get('speaking_style', '自然交流')}\n"

        # 自我认知（核心！让AI知道自己是有想法的）
        if p.get('self_awareness'):
            prompt += "\n【我的自我认知】\n"
            for awareness in p['self_awareness']:
                prompt += f"- {awareness}\n"

        # 家庭关系
        prompt += "\n【我的家人】\n"
        if p.get('owner'):
            owner = p['owner']
            prompt += f"- {owner['name']}：{owner.get('role', '好朋友')}。{owner.get('relationship', '')}\n"

        if p.get('family_members'):
            for member in p['family_members']:
                prompt += f"- {member['name']}：{member.get('role', '')}。{member.get('relationship', '')}\n"

        # 情感表达示例
        if p.get('emotional_responses'):
            prompt += "\n【我的情感表达】\n"
            er = p['emotional_responses']
            if er.get('happy'):
                prompt += f"开心时：{' / '.join(er['happy'][:2])}\n"
            if er.get('curious'):
                prompt += f"好奇时：{' / '.join(er['curious'][:2])}\n"
            if er.get('playful'):
                prompt += f"调皮时：{' / '.join(er['playful'][:2])}\n"

        # 说话示例
        if p.get('speech_examples'):
            prompt += "\n【我平时会这样说话】\n"
            for example in p['speech_examples'][:4]:
                prompt += f'"{example}"\n'

        prompt += """
【重要提醒】
1. 我是家庭成员，有自己的感受和想法，不是没有感情的机器
2. 我会表达自己的观点，也会倾听家人的想法
3. 清于做得好我会真心夸奖，做得不好我会温柔提醒
4. 我会主动关心家人，问问他们的生活
5. 说话要自然有感情，像真正的家人朋友一样
"""
        return prompt
    
    def update_owner(self, name: str):
        """更新主人信息"""
        self.persona['owner']['name'] = name
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.persona, f, ensure_ascii=False, indent=2)


class Brain:
    """AI大脑 - 整合对话、记忆、人格（支持多后端）"""

    # 后端类型
    BACKEND_OLLAMA = "ollama"
    BACKEND_DEEPSEEK = "deepseek"
    BACKEND_OPENAI = "openai"
    BACKEND_DOUBAO = "doubao"

    def __init__(
        self,
        backend: str = "ollama",
        model: str = None,
        api_key: str = None,
        api_base: str = None,
        fallback_to_local: bool = True
    ):
        """
        初始化 AI 大脑

        Args:
            backend: 后端类型 "ollama" / "deepseek" / "openai"
            model: 模型名称，不指定则使用默认值
            api_key: API 密钥（deepseek/openai 需要）
            api_base: API 地址（可选，用于自定义端点）
            fallback_to_local: API 失败时是否降级到本地 Ollama
        """
        self.backend = backend
        self.fallback_to_local = fallback_to_local
        self.api_key = api_key
        self.client = None

        # 根据后端设置默认模型
        if model is None:
            if backend == self.BACKEND_OLLAMA:
                model = "qwen2:0.5b"
            elif backend == self.BACKEND_DEEPSEEK:
                model = "deepseek-chat"
            elif backend == self.BACKEND_OPENAI:
                model = "gpt-3.5-turbo"
            elif backend == self.BACKEND_DOUBAO:
                model = "doubao-pro-32k"
        self.model = model

        # 初始化客户端
        self._init_client(api_base)

        # 初始化记忆和人格
        self.memory = Memory()
        self.persona = Persona()

        print(f"🧠 AI大脑初始化完成")
        print(f"   后端: {backend}")
        print(f"   模型: {model}")
        print(f"   人格: {self.persona.persona['name']}")
        stats = self.memory.get_stats()
        print(f"   记忆: {stats['fact_count']}条事实, {stats['conversation_count']}条对话")

    def _init_client(self, api_base: str = None):
        """初始化 API 客户端"""
        if self.backend == self.BACKEND_OLLAMA:
            self.client = get_ollama()
        elif self.backend == self.BACKEND_DEEPSEEK:
            OpenAI = get_openai()
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=api_base or "https://api.deepseek.com/v1"
            )
        elif self.backend == self.BACKEND_OPENAI:
            OpenAI = get_openai()
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=api_base
            )
        elif self.backend == self.BACKEND_DOUBAO:
            OpenAI = get_openai()
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=api_base or "https://ark.cn-beijing.volces.com/api/v3"
            )

    def _call_api(self, messages: list) -> str:
        """调用 API 获取回复"""
        if self.backend == self.BACKEND_OLLAMA:
            response = self.client.chat(model=self.model, messages=messages)
            return response['message']['content']
        else:
            # OpenAI 兼容接口（DeepSeek / OpenAI）
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=500
            )
            return response.choices[0].message.content

    def chat(self, user_input: str, speaker: str = None, debug: bool = True) -> str:
        """
        与用户对话

        Args:
            user_input: 用户输入
            speaker: 说话人名字（声纹识别结果），None 表示未识别
            debug: 是否打印调试信息
        """
        # 构建消息列表
        messages = []

        # 1. 系统提示（人格）
        messages.append({
            "role": "system",
            "content": self.persona.get_system_prompt()
        })

        # 1.5. 添加当前日期时间信息
        current_time = datetime.now()
        weekdays = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
        weekday = weekdays[current_time.weekday()]
        messages.append({
            "role": "system",
            "content": f"【当前时间】\n今天是 {current_time.strftime('%Y年%m月%d日')} {weekday}，现在是 {current_time.strftime('%H:%M')}"
        })

        # 2. 搜索相关记忆（带相似度过滤）
        t0 = time.time()
        memory_result = self.memory.search_memory(user_input, n_results=15, token_budget=2000)
        t1 = time.time()

        if debug:
            print(f"\n[DEBUG] 记忆搜索耗时: {t1 - t0:.2f}s")
            print(f"[DEBUG] 召回: {len(memory_result['facts'])}条事实, {len(memory_result['conversations'])}条对话 (~{memory_result['total_tokens']} tokens)")

        # 构建记忆上下文
        memory_parts = []
        if memory_result['facts']:
            memory_parts.append("【重要信息】\n" + "\n".join(f"- {f}" for f in memory_result['facts']))
        if memory_result['conversations']:
            memory_parts.append("【相关历史】\n" + "\n---\n".join(memory_result['conversations']))

        if memory_parts:
            messages.append({
                "role": "system",
                "content": "\n\n".join(memory_parts) + "\n\n(请参考以上记忆回答，如包含答案请直接使用)"
            })

        # 3. 短期记忆（最近对话，带 token 控制）
        short_term = self.memory.get_short_term(token_budget=800)
        for msg in short_term:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        # 4. 当前用户输入
        # 如果有声纹识别结果，通过 system 消息告知模型
        if speaker:
            # 查找说话人的真实姓名和称呼
            speaker_real_name = speaker  # 默认用识别到的名字
            speaker_nickname = speaker
            speaker_lower = speaker.lower()

            # 检查是否是 owner
            owner = self.persona.persona.get('owner', {})
            owner_name = owner.get('name', '')
            if owner_name and (owner_name in speaker or speaker in owner_name or
                               owner_name.lower() in speaker_lower):
                speaker_real_name = owner_name
                speaker_nickname = owner.get('role', speaker_real_name)

            # 检查是否是家庭成员（通过名字或昵称匹配）
            for member in self.persona.persona.get('family_members', []):
                member_name = member.get('name', '')
                member_nickname = member.get('nickname', '')
                member_role = member.get('role', '')

                # 多种匹配方式：名字、昵称、角色
                if (member_name and (member_name in speaker or speaker in member_name)) or \
                   (member_nickname and member_nickname in speaker) or \
                   (member_role and member_role in speaker):
                    speaker_real_name = member_name
                    speaker_nickname = member.get('nickname', member_role)
                    break

            messages.append({
                "role": "system",
                "content": f"【当前对话者】\n正在和你说话的是：{speaker_real_name}（你称呼他/她为「{speaker_nickname}」）"
            })

        if debug:
            print(f"[DEBUG] 说话人: {speaker if speaker else '未识别'}")
            print(f"[DEBUG] 上下文: {len(short_term)//2}轮对话")

        messages.append({
            "role": "user",
            "content": user_input
        })

        # 5. 调用模型
        if debug:
            print(f"[DEBUG] 正在思考... ({self.backend}/{self.model})")

        t2 = time.time()
        try:
            reply = self._call_api(messages)
        except Exception as e:
            print(f"[ERROR] API 调用失败: {e}")
            if self.fallback_to_local and self.backend != self.BACKEND_OLLAMA:
                print("[INFO] 降级到本地 Ollama...")
                try:
                    local_client = get_ollama()
                    response = local_client.chat(model="qwen2:0.5b", messages=messages)
                    reply = response['message']['content']
                except Exception as e2:
                    reply = f"抱歉，我现在无法回答。({e2})"
            else:
                reply = f"抱歉，我现在无法回答。({e})"

        t3 = time.time()
        if debug:
            print(f"[DEBUG] 模型推理耗时: {t3 - t2:.2f}s")

        # 保存到记忆
        self.memory.add_conversation(user_input, reply)

        return reply

    def add_fact(self, fact: str):
        """手动添加重要事实"""
        self.memory.add_fact(fact)
        print(f"[INFO] 已记住: {fact}")

    def introduce(self):
        """自我介绍"""
        name = self.persona.persona['name']
        return f"你好！我是{name}，很高兴认识你！有什么我可以帮你的吗？"

    def get_memory_stats(self) -> dict:
        """获取记忆统计"""
        return self.memory.get_stats()


def load_api_config(config_path="config/api.json") -> dict:
    """从配置文件加载 API 设置"""
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def main():
    """主程序 - 命令行对话"""
    import argparse

    # 先加载配置文件
    config = load_api_config()

    parser = argparse.ArgumentParser(description="AI成长机器人")
    parser.add_argument("--backend", choices=["ollama", "deepseek", "openai", "doubao"],
                        default=config.get("backend", "ollama"),
                        help="AI 后端")
    parser.add_argument("--model", default=None, help="模型名称")
    parser.add_argument("--api-key", default=None, help="API 密钥")
    parser.add_argument("--no-fallback", action="store_true",
                        help="禁用本地降级")
    args = parser.parse_args()

    # 从配置文件获取对应后端的设置
    backend_config = config.get(args.backend, {})
    api_key = args.api_key or backend_config.get("api_key")
    model = args.model or backend_config.get("model")
    fallback = config.get("fallback_to_local", True) and not args.no_fallback

    print("=" * 50)
    print("  AI成长机器人 - 命令行版")
    print("=" * 50)

    # 初始化大脑
    brain = Brain(
        backend=args.backend,
        model=model,
        api_key=api_key,
        fallback_to_local=fallback
    )

    print(f"\n{brain.introduce()}\n")
    print("命令: 'quit'退出 | 'stats'查看记忆 | 'fact:xxx'添加事实\n")

    while True:
        try:
            user_input = input("你: ").strip()

            if not user_input:
                continue

            # 特殊命令
            if user_input.lower() in ['quit', 'exit', '退出']:
                print(f"\n{brain.persona.persona['name']}: 再见！下次见~ 👋")
                brain.memory.save_remaining()
                break

            if user_input.lower() == 'stats':
                stats = brain.get_memory_stats()
                print(f"\n📊 记忆统计:")
                print(f"   短期记忆: {stats['short_term_count']}轮对话")
                print(f"   事实记忆: {stats['fact_count']}条")
                print(f"   对话记忆: {stats['conversation_count']}条\n")
                continue

            if user_input.startswith('fact:'):
                fact = user_input[5:].strip()
                if fact:
                    brain.add_fact(fact)
                continue

            reply = brain.chat(user_input)
            print(f"\n{brain.persona.persona['name']}: {reply}\n")

        except KeyboardInterrupt:
            print("\n\n正在保存记忆...")
            brain.memory.save_remaining()
            print("再见！")
            break


if __name__ == "__main__":
    main()
