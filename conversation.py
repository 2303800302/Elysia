import re
import os
import json
import time
import datetime
import requests
import traceback
import logging
from config import (DEEPSEEK_API_KEY,
                    MAX_HISTORY_ROUNDS,
                    TEMPERATYRE,MAX_TOKEN,
                    SUMMARY_ENTRIES_PER_FILE,
                    SUMMARY_UPDATE_INTERVAL,
                    LOG_DIR,
                    SUMMARY_FILE,
                    METADATA_FILE,
                    INDEX_DIALOG_THRESHOLD,
                    MIN_INDEX_INTERVAL,DEBUG)

# 全局变量，用于跟踪已添加到索引的会话ID和当前对话计数
_indexed_sessions = set()   #集合无序不重复（会自动去重，无序不支持索引），主要用于去重
_current_dialog_count = 0
_last_index_time = 0        #上次添加索引的时间
_last_index_topic = ''      #上次添加的索引主题
_MIN_INDEX_INTERVAL = MIN_INDEX_INTERVAL  #最小索引间隔时间（秒）

#设置日志
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('naga')

def reset_dialog_counter():
    """重置对话计数器"""
    global _current_dialog_count  #全局变量，函数作用将此变量清0
    _current_dialog_count = 0

def increment_dialog_counter():
    """增加对话计数器，并返回当前计数"""
    global _current_dialog_count
    _current_dialog_count += 1
    return _current_dialog_count

def get_dialog_count():
    """获取当前对话计数"""
    global _current_dialog_count
    return _current_dialog_count

def get_current_data():
    """获取当前日期字符串"""
    return datetime.datetime.now().strftime("%Y-%m-%d")

def get_current_time():
    """获取当前时间字符串"""
    return datetime.datetime.now().strftime("%H:%M:%S")

def get_current_datetime():
    """获取当前日期时间字符串"""
    return datetime.datetime.now().strftime("%y-%m-%d %H:%M:%S")

def is_session_indexed(user_input,ai_response,date=None):
    """检查特点对话是否已经添加到索引中"""
    global _indexed_sessions

    if date is None:
        date = get_current_data()  #会话时间年月天

    #创建会话的位置标识
    session_id = f"{date}_{user_input[:20]}_{ai_response[:20]}"

    #检查是否已经添加过
    # if session_id in
