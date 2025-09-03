import re
import os
import json
import time
import datetime
import requests
import traceback
import logging

from debugpy.common.log import log_dir
from gensim.scripts.segment_wiki import segment

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

        #读取日志文件
        with open(log_file,'r',encoding='utf-8') as f:
            content = f.read()

        #解析日志文件
        history = []
        segments = content.split("-"*50) #划分开是列表
        for segment in segments[-limit-1,-1]: #获取最新的limit对话
            if not segment.strip(): #去掉首尾符合是空白、
                continue

            lines = segment.strip().split("\n")
            if len(lines) >= 3: #确保有时间，用户和娜迦的内容
                user_line = next((line for line in lines if line.startswith("用户：")),"") #后面""是保证没有要寻找内容时返回空字符串，便面报错
                naga_line = next((line for line in lines if line.startswith("娜迦：")),"")

                if user_line and naga_line:
                    user_content = user_line.replace("用户：","").strip()
                    naga_content = naga_line.replace("娜迦：","").strip() #将对话开头去除，再将首尾符合去掉

                    history.append({"role":"user","content":user_content})
                    history.append({"role":"assistant","content":naga_content})

            return history
    except Exception as e:
        logger.error(f"加载历史记录出错：{e}")
        return []

def get_chat_summary_content():
    """获取主题摘要作为上下文参考"""
    try:
        log_dir = get_chatlog_dir()
        summary_file = os.path.join(log_dir,SUMMARY_FILE)

        #如果摘要文件不存在获取过期（超过一天），则更新
        if not os.path.exists(summary_file) or \
                (time.time() - os.path.getmtime(summary_file)) >\
                SUMMARY_UPDATE_INTERVAL: #1天=86400秒
                update_chat_summary_index() #这个or后面的\是续行符

        #读取摘要文件
        if os.path.exists(summary_file):
            with open(summary_file,'r',encoding='utf-8') as f:
                return f.read()

        return ""
    except Exception as e:
        logger.error(f"读取主题摘要时出错{e}")
        return ""

def ai_generate_topic_for_conversation(use_input,ai_response):
    """AI根据对话内容生成主题"""
    try:
        #首先检查AI回复中是否已经包含标准格式的主题索引
        topic_match = re.search(r"\[索引主题\]:(.*?)\[结束\]",ai_response)  #找到搜索内容，否则返回空
        if topic_match:
            #如果AI回复中包含标准格式的主题索引，直接提取
            topic = topic_match.group(1).strip() #group函数是精准提取正则匹配中的特定部分
            logger.debug(f"从AI回复中直接提取到主题1索引：{topic}")
            return topic

        #如果没有明确指示，调用API让AI生成主题总结
        return _generate_ai_topic_summary(use_input,ai_response)
    except Exception as e:
        logger.error(f"生成主题出错{e}")
        return use_input[:20] + "..."

def _generate_ai_topic_summary(user_input,ai_response):
    """调用API生成对话主题总结"""
    try:
        #首先检查AI回复中是否包含了标准格式的主题索引，直接提取
        topic_match = re.search(r"\[索引主题\]：(.*?)\[结束\]",ai_response)
        if topic_match:
            #如果AI回复中已经包含了标准格式的主题索引，直接提取
            topic = topic_match.group(1).strip() #针对group（）提取，看正则表达式中的括号排序，依次从左到右1，2，3（0是整个），如果有嵌套括号，也是从左到右，先大括号，再在大括号中的小括号从左到右。此处就是(.*?)
            logger.debug(f"从AI回复中直接提取到主题索引：{topic}")
            return topic

        # 如果AI回复中没有包含标准格式的主题索引，调用API生成
        prompt = f"""请根据以下对话，总结一个简洁的主题标题，使用15字以内。
请在回复中包含主题索引，格式必须是：[索引主题]：你的主题内容[结束]

可以这样回复：我认为这段对话的主题是[索引主题]：量子计算入门[结束]，希望对你有帮助。

对话内容：
用户: {user_input}
AI: {ai_response}"""

        #准备请求负载
        api_url = "https://api.deepseek.com/v1/chat/completions"
        #API 的地址，就像你要访问的网站 URL，这里是 DeepSeek 提供的聊天接口地址
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
        }
        #         #请求的 “头部信息”，相当于给 API 的 “身份凭证” 和 “数据说明”：
        # Content-Type: application/json 表示发送的是 JSON 格式的数据，API 需要按 JSON 解析。
        # Authorization: Bearer {密钥} 是认证方式，DEEPSEEK_API_KEY 是用户在 DeepSeek 平台申请的 API 密钥（类似 “密码”，证明你有权限调用 API）。

        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
            "max_tokens": 100
        } # payload 是发送给API的具体任务指令

        #发送API请求
        logger.debug("正在生成对话主题总结...")
        response = requests.post(api_url,headers=headers,json=payload)
        response.raise_for_status() #检查请求是否成功，如果api返回错误会抛出异常
        #requests.post()用requests库发送一个post请求（http的一种提交方式）
        #第一个参数是请求地址
        #第二个参数是前面定义的请求头
        #第三个参数会自动把payload转换为json格式发送

        #解析响应
        resp_data = response.json() #API 的回复通常是 JSON 格式的字符串，这个方法会把它转换成 Python 字典（resp_data），方便提取数据。

        if "choices" in resp_data and len(resp_data["choices"]) > 0:
            ai_content = resp_data["choices"][0]["message"]["content"].strip()

            #使用正则表达式匹配标准格式 "[索引主题]: xxx[结束]"
            match = re.search(r"\[索引主题\]: (.*?)\[结束\]",ai_content)
            if match:
                topic = match.group(1).strip()
                #限制长度
                if len(topic) > 20:
                    topic = topic[:20] + "..."

                logger.debug(f"AI生成的标准格式主题：{topic}")
                return topic
            else:
                # 未能匹配到标准格式，尝试提取整个回复作为主题
                logger.warning(f"AI回复未按照标准格式：{ai_content}")
                #提取回复的前20个字作为主题
                topic = ai_content[:20] + ("..." if len(ai_content)> 20 else "")
                return topic
        else:
            logger.error(f"AI生成主题失败，使用默认主题")
            return user_input[:20] + "..."
    except Exception as e:
        logger.error(f"调用API生成主题时出错：{e}")
        return user_input[:20] + "..."

def _refine_topic_name(topic,user_input,ai_response):
    """优化索引1主题名称，使其更精确和有意义

    采用通用算法提取关键概念，不依赖特定领域词汇
    """
    if not topic: #如果是空，即topic是空字符串
        return topic

    #检查主题是否过于模糊
    vague_terms = ['系统',"功能","记录","版本","更新","讨论","分析","概述"]
    is_vague = all(term in vague_terms for term in topic.split() if len(term)>1) #查看是否所有的次都在vague_terms里面，返回true

    if is_vague:
        # 2，对话中提取可能的关键术语
        #提取引号中的内容作为可能的关键术语
        quoted_terms = re.findall(r'["\'](.*?)["\']',user_input + " " + ai_response)
        project_terms = []

        #寻找可能的项目名称（通常是名词+系统/功能/模块等）
        project_pattern = re.compile(r'([A-Za-z\u4e00-\u9fa5]{1,10}(?:系统|功能|模块|项目|计划|框架|平台))')
        project_matches = project_pattern.findall(user_input + " " + ai_response)
        if project_matches:
            project_terms.extend(project_matches)

        #3. 如果找到关键术语，将他们添加到主题中
        for term in quoted_terms + project_terms:
            if term and term not in topic and len(term) > 1:
                if any(vague in topic for vague in vague_terms):
                    #替换模糊术语
                    for vague in vague_terms:
                        if vague in topic:
                            return topic.replace(vague,term)

                else:
                    #添加为前缀
                    return f"{term}{topic}"

    #4. 移除冗余词汇
    redundant_pairs = [
        ("系统功能","系统"),
        ("功能功能", "功能"),
        ("模块模块", "模块")

    ]

    result = topic
    for pair in redundant_pairs:
        result = result.replace(pair[0],pair[1])

    return result




























