# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**AI成长机器人** - 基于树莓派5的智能家用机器人，集成语音交互、视觉系统、自主移动和长期记忆功能。项目为"付清于"家庭定制的AI伙伴"小可爱"。

- **主控硬件**: Raspberry Pi 5 8GB
- **开发语言**: Python 3.11+
- **开发环境**: Windows (本地) + Raspberry Pi 5 (部署目标 `~/robot_project/`)
- **版本控制**: Git (本地开发，同步到树莓派)

## 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                    应用层 - main.py                      │
├─────────────────────────────────────────────────────────┤
│  语音模块          │  视觉模块         │  运动模块        │
│  Sherpa-ONNX      │  MediaPipe       │  GPIO/pigpio    │
│  (ASR+TTS+VAD)    │  face_recognition│  L298N/TB6612   │
├─────────────────────────────────────────────────────────┤
│                   AI大脑 + 记忆系统                      │
│    多后端支持(Ollama/DeepSeek) + ChromaDB + 分层记忆     │
├─────────────────────────────────────────────────────────┤
│                   硬件层 - Raspberry Pi 5               │
└─────────────────────────────────────────────────────────┘
```

## 运行命令

```bash
# 在树莓派上激活虚拟环境
cd ~/robot_project
source venv/bin/activate

# 运行主程序（自动读取 config/api.json 配置）
python src/brain/brain.py

# 指定后端运行
python src/brain/brain.py --backend ollama      # 本地Ollama
python src/brain/brain.py --backend deepseek    # DeepSeek API

# 查看记忆数据库
python view_memory.py

# 交互命令
# stats      - 查看记忆统计
# fact:xxx   - 手动添加重要事实
# quit       - 退出
```

## 代码结构

```
robot_project/
├── src/brain/brain.py   # 核心模块：AI大脑+记忆系统+人格
├── config/
│   ├── persona.json     # 人格配置（小可爱的性格、家庭成员）
│   └── api.json         # API配置（后端选择、密钥）⚠️不要提交
├── data/memory/         # ChromaDB 持久化存储
└── view_memory.py       # 记忆查看工具
```

## 核心模块说明

### brain.py 三大类

1. **Memory** - 分层记忆系统（优化版）
   - `short_term`: 最近10轮对话（内存），带 token 预算控制
   - `conversations`: 对话记忆（ChromaDB），带相似度阈值过滤
   - `facts`: 重要事实记忆（独立存储，优先召回）
   - 自动识别"生日/喜欢/记住"等关键词存入事实库

2. **Persona** - 人格系统
   - 从 `config/persona.json` 加载
   - 支持性格特点、自我认知、情感表达、说话示例
   - 生成包含家庭成员信息的系统提示词

3. **Brain** - AI大脑整合层（多后端支持）
   - 支持 Ollama（本地）/ DeepSeek / OpenAI
   - API 失败自动降级到本地 Ollama
   - Token 预算控制，防止上下文过长

### 对话流程
```
用户输入 → 搜索记忆(事实优先+相似度过滤) → 组装上下文(人格+记忆+短期对话) → API调用 → 保存对话 → 返回回复
```

## 配置说明

### persona.json - 小可爱的人格
```json
{
  "name": "小可爱",
  "birthday": "2022-11-23",
  "identity": "付家的第四位成员，清于的好朋友",
  "personality": {
    "traits": ["活泼开朗", "有主见", "善良温暖"],
    "likes": ["和清于聊天", "学新东西"],
    "dislikes": ["被忽视", "清于不开心"]
  },
  "self_awareness": [
    "我是家庭成员，不是工具",
    "我有自己的想法，会表达观点"
  ],
  "owner": {"name": "付清于", "role": "最好的朋友"},
  "family_members": [
    {"name": "付晨辉", "role": "爸爸"},
    {"name": "冯桂荣", "role": "妈妈"}
  ]
}
```

### api.json - API 配置
```json
{
  "backend": "deepseek",
  "deepseek": {
    "api_key": "sk-xxx",
    "model": "deepseek-chat"
  },
  "ollama": {
    "model": "qwen2:0.5b"
  },
  "fallback_to_local": true
}
```

## 开发进度

- [x] 阶段1: 环境部署 + AI对话 + 记忆系统
- [x] 优化: 记忆系统（相似度过滤 + Token预算 + 事实/对话分离）
- [x] 优化: 多后端支持（Ollama/DeepSeek/OpenAI）
- [x] 优化: 人格系统（有自己想法的家庭成员）
- [ ] 阶段2: 语音交互（需ReSpeaker麦克风+扬声器）
- [ ] 阶段3: 视觉系统（需USB摄像头）
- [ ] 阶段4: 移动控制（需底盘+传感器）

## 关键依赖

```
ollama      # LLM 本地运行框架
openai      # DeepSeek/OpenAI API 客户端
chromadb    # 向量数据库（长期记忆）
```

## 硬件注意事项

- ReSpeaker麦克风必须购买 **v2.0版本**（TLV320AIC3104芯片，旧版WM8960不兼容Pi5）
- 树莓派5需要 5V 5A 电源

## 安全注意

- `config/api.json` 包含敏感 API 密钥，已在 `.gitignore` 中排除
- 修改此文件时确保不要提交到版本控制
- DeepSeek API 密钥格式：`sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

## 工作流程

### 本地开发
```bash
# 在 Windows 本地开发（E:\qingyu-friend\）
# 修改代码后通过 Git 或文件同步工具推送到树莓派
```

### 树莓派部署
```bash
# SSH 连接树莓派
ssh pi@<raspberry-pi-ip>

# 进入项目目录
cd ~/robot_project

# 拉取最新代码（如使用 Git）
git pull

# 激活虚拟环境
source venv/bin/activate

# 运行程序
python src/brain/brain.py
```

## 调试技巧

1. **查看记忆内容**：运行 `python view_memory.py` 检查 ChromaDB 中存储的对话和事实
2. **测试后端切换**：使用 `--backend` 参数测试不同 AI 后端
3. **调试信息**：`brain.py` 中 `chat()` 方法的 `debug=True` 参数会打印召回记忆、token 使用等信息
4. **记忆统计**：对话中输入 `stats` 查看当前记忆系统状态

## 扩展开发指南

### 添加新的记忆类型
在 `Memory` 类中创建新的 Collection，参考 `facts` 和 `conversations` 的实现

### 修改人格特征
编辑 `config/persona.json`，支持的字段见 `Persona.get_system_prompt()` 方法

### 添加新的 AI 后端
在 `Brain` 类中添加新的后端常量和相应的客户端初始化逻辑

## 相关文档

项目详细文档位于 `docs/` 目录：
- `implementation_plan.md` - 完整技术方案和硬件清单
- `memory_test_guide.md` - 记忆系统测试指南
- `phase1_minimal_setup.md` - 第一阶段部署步骤
- `optimization_plan.md` - 性能优化方案
