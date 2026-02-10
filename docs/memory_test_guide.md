# 记忆系统测试指南 🧠

如何验证机器人的记忆功能是否正常工作。

## 1. 测试短期记忆 (Context)
验证机器人在单次对话中是否记得上下文。

**测试步骤**：
```
你：我今天早餐吃了包子。
小可爱：好的，包子很好吃！
你：我刚才说早饭吃了什么？
```
**期望回答**：能提到"包子"。

---

## 2. 测试长期记忆 (ChromaDB)
验证机器人是否记得过去的对话（即使重启程序后）。

**测试步骤**：

**第一步：告诉它一个信息**
```
你：请记住，我最喜欢的颜色是蓝色。
小可爱：好的，我记住了，你最喜欢的颜色是蓝色。
```

**第二步：退出程序**
输入 `quit` 退出，甚至可以重启树莓派。

**第三步：重新启动并提问**
```bash
python src/brain/brain.py
```
```
你：我最喜欢的颜色是什么？
```

**期望回答**：能回答出"蓝色"。

---

## 3. 查看记忆数据 (进阶)

如果你想直接看它存了什么，可以编写一个查看脚本：

```python
# view_memory.py
import chromadb

client = chromadb.PersistentClient(path="data/memory")
collection = client.get_collection("long_term_memory")

# 显示所有记忆
print(f"总计记忆条数: {collection.count()}")
print(collection.peek())
```
