import os
import time
import datetime
import logging

from astropy.logger import level
from debugpy.common.log import log_dir
from torchvision import message

from config import LOG_DIR, DEBUG, SUMMARY_FILE, INDEX_DIALOG_THRESHOLD
from conversation import (interact_with_deepseek, reset_dialog_counter,
                         get_current_data, get_current_time, get_chatlog_dir,
                         update_chat_summary_index)

# 设置日志
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
) # 配置

logger = logging.getLogger('naga') # 命名对象

def clear_screen():
    """清屏函数"""
    os.system('cls' if os.name == 'nt' else 'clear')

def save_chat_log(user_input,ai_response):
    """保存聊天记录到文件"""
    try:
        date_str = get_current_data()
        time_str = get_current_time()

        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),LOG_DIR)
        if not os.path.exists(log_dir):
            os.mkdir(log_dir)

        log_file = os.path.join(log_dir,f'{date_str}.txt')
        with open(log_file,'a',encoding='utf-8') as f:
            f.write('-'*50 + '\n')
            f.write(f'时间：{time_str}\n')
            f.write(f'用户：{user_input}\n')
            f.write(f'娜迦：{ai_response}\n')
            f.write('-'*50 + '\n')

        return True
    except Exception as e:
        logger.error(f'保存聊天记录失效：{e}')
        return False

def diaplay_topic_index():
    """显示主题索引内容"""
    try:
        log_dir = get_chatlog_dir()
        summary_file = os.path.join(log_dir,SUMMARY_FILE)

        if os.path.exists(summary_file)
            with open(summary_file,'r',encoding='utf-8') as f:
                content = f.read()
            print('\n' + '-'*50)
            print('当索引内容:')
            print(content)
            print('-'*50)
            return True
        else:
            print('\n当前还没有索引内容')
            return False
    except Exception as e:
        logger.error(f'显示索引文件失败{e}')
        print('\n读取索引内容失败')
        return False

def handle_system_command(command,messages):
    """处理系统特殊命令"""
    command = command.lower().strip()

    # 退出命令
    if command in ['退出','exit','quit']:
        print('娜迦：再见，期待下次见到你')
        return True,messages

    #查看索引
    elif command in ['查看索引','show index','显示索引']:
        diaplay_topic_index()
        return False,messages


