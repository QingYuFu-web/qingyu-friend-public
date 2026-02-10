#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查看机器人记忆数据库内容
"""

import chromadb
from datetime import datetime

def view_memory_database(db_path="data/memory"):
    """查看记忆数据库中的所有内容"""

    print("=" * 60)
    print("  机器人记忆数据库查看工具")
    print("=" * 60)
    print()

    try:
        # 连接数据库
        client = chromadb.PersistentClient(path=db_path)

        # 获取两个集合
        try:
            facts = client.get_collection("important_facts")
            fact_count = facts.count()
        except:
            facts = None
            fact_count = 0

        try:
            conversations = client.get_collection("long_term_memory")
            conv_count = conversations.count()
        except:
            conversations = None
            conv_count = 0

        # 显示统计
        print(f"📊 记忆统计:")
        print(f"   重要事实: {fact_count} 条")
        print(f"   对话记忆: {conv_count} 条")
        print(f"   总计: {fact_count + conv_count} 条\n")

        if fact_count == 0 and conv_count == 0:
            print("⚠️  数据库为空，还没有任何记忆")
            return

        # 显示事实记忆
        if facts and fact_count > 0:
            print("=" * 60)
            print("🌟 重要事实记忆")
            print("=" * 60)
            all_facts = facts.get()
            for i, (doc_id, document, metadata) in enumerate(zip(
                all_facts['ids'],
                all_facts['documents'],
                all_facts['metadatas']
            ), 1):
                print(f"\n{'─' * 60}")
                print(f"📌 事实 #{i}")
                print(f"时间: {metadata.get('time', '未知')}")
                print(f"内容: {document}")

        # 显示对话记忆
        if conversations and conv_count > 0:
            print("\n" + "=" * 60)
            print("💬 对话记忆")
            print("=" * 60)
            all_convs = conversations.get()
            for i, (doc_id, document, metadata) in enumerate(zip(
                all_convs['ids'],
                all_convs['documents'],
                all_convs['metadatas']
            ), 1):
                print(f"\n{'─' * 60}")
                print(f"📝 对话 #{i}")
                print(f"时间: {metadata.get('time', '未知')}")
                print(f"内容:")
                print(f"  {document}")

        print("\n" + "=" * 60)
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        print("\n可能的原因:")
        print("  1. 数据库路径不正确")
        print("  2. 还没有运行过机器人程序")
        print("  3. ChromaDB 未正确安装")

if __name__ == "__main__":
    view_memory_database()
