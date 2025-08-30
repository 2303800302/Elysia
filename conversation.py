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
    if session_id in _indexed_sessions:
        return True

    #将当前会话标记为已添加
    _indexed_sessions.add(session_id)
    return False

def clean_text(text):
    """清理文本，移除不必要的字符"""
    if text is None:
        return ""

    #检查文本是否包含文件路径
    contains_path = re.search(r'(?:[A-Za-z]:\\|\.\/|\/|"[A-Za-z]:\\|\'\S+\.(?:txt|py|json|md|csv|xlsx|docx)\'|"\S+\.(?:txt|py|json|md|csv|xlsx|docx)")', text) is not None

    if contains_path:
        # 保留路径所需的特殊字符
        text = re.sub(r'[^\w\s,.!?，。！？\\/:\-\."\'_~]', '', text)
        #举个例子，源文本是请读取 C:\Users\文档#报告.docx！
        #那么清洗后读取就是请读取 C:\Users\文档报告.docx！
    else:
        #标准清理(既不是路径，又有路径中的符号，则清除这些符号)
        #如text为明天@下午3点开会#讨论项目！，清理后为明天下午3点开会讨论项目！
        text = re.sub(r'[^\w\s,.!?，。！？]', '', text)

    # 压缩空白字符
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_chatlog_dir():
    """获取chatlog目录路径"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(script_dir,LOG_DIR)
    if not os.path.exists(log_dir):
        try:
            os.mkdir(log_dir)
            logger.info(f"创建日志目录：{log_dir}")
        except Exception as e:
            logger.error(f"创建日志目录失败：{e}")
    return log_dir

def load_index_metadata():
    """加载索引元数据"""
    log_dir = get_chatlog_dir()
    metadata_file = os.path.join(log_dir,METADATA_FILE)

    if os.path.exists(metadata_file):
        try:
            with open(metadata_file,"r",encoding='utf-8') as f:
                return json.load(f) #针对f提取数据转化为python数据类型
        except json.JSONDecodeError as e: #读取json格式时，文件内容不能有效触发，如json语法错误（缺少括号，引号不匹配等）
            logger.error(f"解析元数据文件出错{e}")
        except IOError  as e: #IOError 是输入输出错误的通用异常，主要在文件操作失败时触发，常见原因包括：文件不存在，没有读取权限等
            logger.error(f"读取元数据文件出错{e}")

        return {"last_update":0, "files":{}} #避免读取失败时，没有返回值

def save_index_metadata(metadata):
    """保存索引元数据"""
    log_dir = get_chatlog_dir()
    metadata_file = os.path.join(log_dir,METADATA_FILE)

    try:
        with open(metadata_file,"w",encoding='utf-8') as f:
            json.dumps(metadata,f,ensure_ascii=False,indent=2)
            #dumps是将python数据结构写入文件并转换为json格式函数
            #第一个参数是需要转化为json格式的python数据（通常为字典，列表）
            #f是打开的文件，“w”是可以读模式
            #ensure_ascii=false是控制非ascii字符（中文，日文等）的处理方式
            #默认为true会转化为uniconde编码，不方便阅读
            #indent是控制joson格式的缩进与换行
    except IOError as e:
        logger.error(f"保存元数据文件出错：{e}")

def generate_chat_summary(log_file,max_entries=SUMMARY_ENTRIES_PER_FILE):
    """生成单个聊天日志的主题摘要"""
    try:
        if not os.path.exists(log_file):
            return ""

        with open(log_file,'r',encoding='utf-8') as f: #有日志就读取，没有就返回空
            content = f.read()

        segments = content.split("-"*50) #到时候日志格式就是用“-”*50分开的
        segments = [s.strip() for s in segments if s.strip()]

        #只处理最新的max_entries个对话
        if len(segments) > max_entries:
            segments = segments[-max_entries:]

        summaries = []
        for segment in segments:
            lines = segment.strip().split('\n')
            #strip() 方法的作用是：删除字符串 “首尾” 的所有空白字符（包括空格、换行符 \n、制表符 \t 等），但保留字符串 “内部” 的换行和空格。
            if len(lines) >= 3:
                time_line = next((line for line in lines if line.startswith("时间：")),"")
                user_line = next((line for line in lines if line.startswith("用户：")),"")
                #next内置函数，用于获取生成器的下一个元素，第二个“”是默认值，没有符合条件元素就返回这个
                if time_line and user_line:
                     time_str = time_line.replace("时间：","").strip()
                     user_content = user_line.replace("用户：","").strip()

                     #提取简短主题
                     topic = user_content[:20] + ("..." if len(user_content) > 20 else "")
                     summaries.append(f"{time_str}:{topic}")

        return "\n".join(summaries) # 用\n换行拼接summaries列表
    except IOError as e: #出现保存或者读取错误，如文件不存在，读取权限不足
        logger.error(f"读取日志文件出错：{e}")
        return ""
    except Exception as e: #exception是一个兜底万能错误，所以一般放最后
        logger.error(f"生成摘要错误：{e}")
        return ""

def update_chat_summary_index():
    """更新所有聊天日志的主题索引文件"""
    try:
        log_dir = get_chatlog_dir()
        summary_file = os.path.join(log_dir,SUMMARY_FILE)

        #加载索引元数据
        metadata = load_index_metadata()
        current_time = time.time()

        #获取所有日志文件。 os.listdir作用是返回这个路径的文件和文件夹的名字的列表
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".txt") and f != SUMMARY_FILE and f != METADATA_FILE]

        #按照修改时间排序（最新的在前面）os.getmtime返回指定路径最后修改时间
        log_files.sort(key=lambda x: os.path.getmtime(os.path.join(log_dir,x), reverse=True))

        # 检查哪些文件需要更新
        files_to_process = []
        for log_file in log_files: #这里log_files是个含文件和文件夹名的列表
            file_path = os.path.join(log_dir,log_file)
            mtime = os.path.getmtime(file_path)

            #如果文件是新的或者已经修改
            if log_file not in metadata["files"] or metadata["files"][log_file] < mtime:
                files_to_process.append((log_files,file_path))
                #更新文件元数据
                metadata["files"][log_file] = mtime

        #如果没有新文件或者更改，且距离上次更新未超过设定更新阈值，直接返回
        if not files_to_process and (current_time - metadata["last_update"] < SUMMARY_UPDATE_INTERVAL):
            logger.debug("没有新的对话日志需要处理，索引已经是最新")
            return summary_file

        #生成摘要内容
        summary_content = f" 对话主题索引（更新时间：{get_current_datetime()}）\n\n"

        #处理需要更新的文件
        process_files = set()
        for log_file, file_path in files_to_process:
            date = log_file.replace(".txt","")
            process_files.add(log_file)

            summary_content += f"##{date}对话记录\n"
            file_summary = generate_chat_summary(file_path)

            if file_summary:
                summary_content += file_summary + "\n\n"
            else:
                summary_content += "无效对话\n\n"

        #添加未更改的文件内容（从现有摘要中获取）
        if os.path.exists(summary_file):
            try:
                with open(summary_file,'r',encoding='utf-8') as f:
                    old_content = f.read()

                #从旧摘要中提取未更改的文件内容
                for log_file in log_files:
                    if log_file not in process_files:
                        date = log_file.replace(".txt","")
                        section_header = f"##{date}对话记录"

                        if section_header in old_content:
                            section_start = old_content.find(section_header)
                            section_end = old_content.find("##",section_start + len(section_header))
                            if section_end == -1:
                                section_end = len(old_content)

                                section_content = old_content[section_start:section_end].strip()
                                if section_content:
                                    summary_content += section_content + "\n\n"
            except Exception as e:
                logger.error(f"读取摘要出错：{e}")
        #保存摘要文件
        with open(summary_file,'w',encoding='utf-8') as f:
            f.write(summary_content)

        #更新元数据并保存
        metadata["last_update"] = current_time
        save_index_metadata(metadata)

        logger.info(f"已更新对话主题索引：{summary_file}")
        return summary_file
    except Exception as e:
        logger.error(f"更新主题索引出错{e}")

def load_recent_chat_history(limit=MAX_HISTORY_ROUNDS):
    """加载最近的聊天记录作为上下文"""
    try:
        #获取chatlog目录
        log_dir = get_chatlog_dir()
        if not os.path.exists(log_dir):
            return []

        #获取最新日志文件
        today = get_current_data()
        log_file = os.path.join(log_dir,f"{today}.txt")

        if not os.path.exists(log_file):
            return []

















