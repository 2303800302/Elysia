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
                    TEMPERATURE,MAX_TOKENS,
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

def get_chat_summary_context():
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
    is_vague = all(term in vague_terms for term in topic.split() if len(term)>1) #查看是否所有的词都在vague_terms里面，返回true，判定为模糊

    if is_vague:
        # 2，对话中提取可能的关键术语
        #提取引号中的内容作为可能的关键术语
        quoted_terms = re.findall(r'["\'](.*?)["\']',user_input + " " + ai_response)
        project_terms = []

        #寻找可能的项目名称（通常是名词+系统/功能/模块等）
        project_pattern = re.compile(r'([A-Za-z\u4e00-\u9fa5]{1,10}(?:系统|功能|模块|项目|计划|框架|平台))') #re.compile() 函数通过将正则表达式字符串转换为正则表达式对象
        project_matches = project_pattern.findall(user_input + " " + ai_response) #这里得到的就是["拉普拉斯系统","帕拉蒂斯计划","格里芬平台",...]等
        if project_matches:
            project_terms.extend(project_matches)

        #3. 如果找到关键术语，将他们添加到主题中
        for term in quoted_terms + project_terms: #quoted里面是引号重点内容，project是关键词内容
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

def ai_update_topic_index(user_input,ai_response,date=None,force_update=False):
    """AI自动更新主题索引"""
    try:
        #获取对话计数
        dialog_count = get_dialog_count()

        #如果对话次数少于阈值且非强制更新，则跳过
        if dialog_count < INDEX_DIALOG_THRESHOLD and not force_update:
            logger.debug(f"[AI索引]当前对话次数({dialog_count})未达到更新阈值({INDEX_DIALOG_THRESHOLD},跳过索引更新)")
            return False

        #获取日期
        date = date or get_current_data()

        #检查是否已经添加过该对话
        if is_session_indexed(user_input,ai_response,date) and not force_update:
            logger.debug(f"[AI索引]该对话已添加到索引中，跳过")
            return False

        #生成主题
        topic = ai_generate_topic_for_conversation(user_input,ai_response)

        #优化主题名称使其更精确
        refined_topic = _refine_topic_name(topic,user_input,ai_response)
        if refined_topic != topic:
            logger.info(f"主题优化：'{topic}' ➡'{refined_topic}'")
            topic = refined_topic

        #获取摘要文件路径
        log_dir = get_chatlog_dir()
        summary_file = os.path.join(log_dir,SUMMARY_FILE)

        # 读取现有摘要文件
        try:
            if os.path.exists(summary_file):
                with open(summary_file,'r',encoding='utf-8') as f:
                    summary_content = f.read()
            else:
                summary_content = ""
        except IOError as e:
            logger.error(f"读取摘要文件出错：{e}")
            summary_content = ""

        #如果文件为空或者不存在，创建基本结构
        if not summary_content:
            summary_content = f"#对话主题索引（更新时间：{get_current_datetime()})\n\n"

        # 更新索引内容
        return _update_summary_content(summary_file, summary_content, date, topic, force_update)

    except Exception as e:
        logger.error(f"AI更新主题索引时出错{e}")
        return False

def _update_summary_content(summary_file,summary_content,date,topic,force_update=False):
    """更新摘要内容并写入文件"""
    try:
        # 当前时间
        time_now = get_current_time()
        date_section = f"##{date} 对话记录"
        new_topic_entry = f"{time_now}:{topic}"

        #如果存在当天记录，添加新条目
        if date_section in summary_content:
            #查看当前记录部分
            section_start = summary_content.find(date_section) #find找到指定字符串第一个出现位置，并返回其位置的索引。没找到会返回-1
            section_end = summary_content.find("##",section_start + len(date_section)) #确定正文的结束边界（##），从date_section之后找
            if section_end == -1:
                section_end = len(summary_content)

            section_content = summary_content[
                section_start:section_end].strip() #当天记录的核心正文分割
            updated_section = section_content + '\n' + new_topic_entry
            #将新的主题条目添加到当天记录，然后更新成新记录

            #更新摘要内容,把摘要中间部分换了
            summary_content = summary_content[:section_start] +updated_section + "\n\n" + summary_content[section_end:]
        else:
            #创建新部分并插入到第一个章节前
            new_section = f"{date_section}\n{new_topic_entry}\n\n"
            first_section = summary_content.find("##")
            if first_section != -1:
                summary_content = summary_content[:first_section] + new_section + summary_content[first_section:]
            else:
                #没有章节
                summary_content += new_section

        #更新标题中时间戳
        summary_content = re.sub(
            r'# 对话主题索引 \(更新时间*?\)',
            f'# 对话主题索引 (更新时间：{get_current_datetime()})',
            summary_content
        )
        #re.sub() 是用于替换字符串中符合正则表达式模式的内容的核心函数。它的本质是：在目标字符串中查找所有匹配正则模式的子串，并用指定的内容替换它们，最终返回替换后的新字符串（原字符串不会被修改）。

        #写入文件
        with open(summary_file,'w',encoding='utf-8') as f:
            f.write(summary_content)

        #更新元数据
        metadata = load_index_metadata()
        metadata['last_update'] = time.time()
        save_index_metadata(metadata)

        action_type = '强制更新' if force_update else "自动更新"
        logger.info(f'[AI{action_type}]已写入主题「{topic}」到索引')
        return True
    except IOError as e:
        logger.error(f"[AI索引写入文件失败：{e}]")
        return False

def _sanitize_ai_response(ai_message,is_context_search=False):
    """处理AI回复内容，防止在检索模式下误触发索引更新

    Args：
        ai_message: AI回复内容
        is_context_search: 是否处于上下文检索模式

    Returns:
        处理后的回复内容
    """
    if not is_context_search:
        return ai_message

    #在检索模式下，替换可能触发索引的标准格式
    #这些替换只在系统检测到用户正在进行上下文检索时进行

    #检查是否包含标准索引格式
    if re.search(r'\[索引主题\]：(.*?)\[结束、]',ai_message):
        #替换标准格式为安全格式
        ai_message = re.sub(
            r'\[索引主题\]：(.*?)\[结束\]',
            ai_message
        )
        logger.info("检测到AI在检索模式下使用标准索引格式，以替换为安全格式")

    return ai_message


def interact_with_deepseek(messages, include_history=True):
    """
    与DeepSeek API交互，获取AI响应

    Args:
        messages: 消息列表
        include_history: 是否包含历史上下文

    Returns:
        更新后的消息列表
    """
    global _last_index_time, _last_index_topic
    try:
        # 准备要发送的消息列表
        if include_history:
            # 检查用户最后一条消息是否包含日期时间引用模式
            user_message = ""
            is_timestamp_query = False
            is_context_search = False
            timestamp_contexts = []
            last_ai_message = ""

            # 获取用户最后的输入和AI上一次的回复
            for i, msg in enumerate(reversed(messages)):
                if msg["role"] == "user" and not user_message:
                    user_message = msg["content"]
                elif msg["role"] == "assistant" and not last_ai_message:
                    last_ai_message = msg["content"]
                if user_message and last_ai_message:
                    break

            # 检测用户是否在确认查看AI提到的时间戳对话
            confirmation_patterns = [
                r'^要$', r'^是$', r'^确认$', r'^好的?$', r'^同意$', r'^继续$',
                r'^ok$', r'^okay$', r'^可以$', r'^请继续$', r'^继续查看$'
            ]

            user_confirming = any(re.search(pattern, user_message.lower()) for pattern in confirmation_patterns)

            # 检查AI上一次回复中是否包含时间戳
            ai_timestamp_matches = []
            if last_ai_message:
                ai_timestamp_matches = re.findall(r'(\d{4}-\d{2}-\d{2})?\s?(\d{2}:\d{2}:\d{2})', last_ai_message)

            # 如果用户是在确认，且AI上一次回复中包含时间戳，则认为是在查询该时间戳对话
            if user_confirming and ai_timestamp_matches:
                is_timestamp_query = True
                logger.info(f"检测到用户确认查看AI提到的时间戳对话")

                for date_str, time_str in ai_timestamp_matches:
                    # 如果没有提供日期，传递None让函数搜索所有日志文件
                    if not date_str:
                        date_str = None

                    # 加载指定时间戳附近的聊天记录
                    context_history = load_chat_by_timestamp(date_str, time_str)
                    if context_history:
                        timestamp_contexts.extend(context_history)
                        date_info = date_str if date_str else "自动检测"
                        logger.info(f"已加载AI提到的时间戳 {date_info} {time_str} 的上下文")
                    else:
                        # 如果未找到，尝试将上次搜索到的结果作为主题进行匹配
                        summary_file = os.path.join(get_chatlog_dir(), SUMMARY_FILE)
                        if os.path.exists(summary_file):
                            try:
                                with open(summary_file, "r", encoding="utf-8") as f:
                                    summary_content = f.read()

                                # 查找提到该时间戳附近的对话主题
                                time_pattern = time_str.replace(":", r"\:")  # 转义冒号用于正则
                                time_context = re.search(r'(\d{4}-\d{2}-\d{2})?.?' + time_pattern + r'.{0,100}',
                                                         summary_content)
                                if time_context:
                                    context_line = time_context.group(0)
                                    logger.info(f"在索引中找到时间戳相关信息: {context_line}")
                                    payload_messages.append({
                                        "role": "system",
                                        "content": f"虽然未能找到完整对话，但在历史索引中找到了相关信息: {context_line}"
                                    })
                            except Exception as e:
                                logger.error(f"查找时间戳索引信息时出错: {e}")

            # 检测是否是上下文检索请求
            if not is_timestamp_query:  # 如果不是时间戳确认，再检查其他模式
                context_search_patterns = [
                    r'查找.*?对话',
                    r'找到.*?聊天记录',
                    r'检索.*?记录',
                    r'查看.*?对话',
                    r'回忆.*?对话',
                    r'回看.*?聊天',
                    r'之前.*?说过',
                    r'之前.*?讨论',
                    r'之前.*?提到'
                ]

                for pattern in context_search_patterns:
                    if re.search(pattern, user_message):
                        is_context_search = True
                        logger.info("检测到上下文检索请求")
                        break

                # 检测用户消息中的日期时间引用 (格式: YYYY-MM-DD HH:MM:SS 或 HH:MM:SS)
                timestamp_matches = re.findall(r'(\d{4}-\d{2}-\d{2})?\s?(\d{2}:\d{2}:\d{2})', user_message)
                if timestamp_matches:
                    is_timestamp_query = True

                    for date_str, time_str in timestamp_matches:
                        # 如果没有提供日期，使用当前日期
                        if not date_str:
                            date_str = get_current_data()

                        # 加载指定时间戳附近的聊天记录
                        context_history = load_chat_by_timestamp(date_str, time_str)
                        if context_history:
                            timestamp_contexts.extend(context_history)
                            logger.info(f"已加载时间戳 {date_str} {time_str} 的上下文")

            # 加载最近的对话历史作为上下文
            chat_history = load_recent_chat_history()

            # 获取当前系统提示
            system_prompt = None
            for msg in messages:
                if msg["role"] == "system":
                    system_prompt = msg
                    break

            # 如果没有系统提示，创建一个
            if not system_prompt:
                system_prompt = {"role": "system", "content": "你是一个有记忆和总结能力的AI助手。"}
                messages.insert(0, system_prompt)

            # 添加有关索引引用格式的指导
            if is_context_search or is_timestamp_query:
                # 在检索模式下，提供特殊指导，避免触发索引机制
                reference_guide = """
重要：当引用历史对话的索引主题时，请使用以下格式，而不要使用[索引主题]：xxx[结束]格式：
1. 「主题：xxx」

例如，应该使用：
- 根据历史记录「主题：量子计算入门」，而不是 [索引主题]：量子计算入门[结束]
- 我在「主题：夏园记忆系统启用纪念」对话中发现...
- 历史记录中「主题：多平台服务接口测试」显示...
"""
                system_prompt["content"] = system_prompt["content"].split("\n\n")[0] + "\n\n" + reference_guide

            # 获取索引摘要上下文
            summary_context = get_chat_summary_context()
            if summary_context and not is_context_search and not is_timestamp_query:  # 在检索模式下不添加索引摘要
                # 将索引摘要添加到系统提示中
                system_prompt["content"] += f"\n\n当前主题索引:\n{summary_context}"

            # 添加当前对话计数信息到系统提示
            current_count = get_dialog_count()

            # 只有在非检索模式下才添加对话计数和索引信息
            if not is_context_search and not is_timestamp_query:
                dialog_info = f"\n\n当前会话信息: 对话次数={current_count + 1}/{INDEX_DIALOG_THRESHOLD}"
                if current_count + 1 >= INDEX_DIALOG_THRESHOLD:
                    dialog_info += "（达到索引阈值，请考虑生成主题索引）"
                system_prompt["content"] += dialog_info
                logger.debug(f"添加会话计数信息: {dialog_info}")

            # 构建完整的消息列表：系统提示 + 时间戳上下文(如果有) + 历史上下文 + 当前对话
            payload_messages = []

            # 1. 添加系统提示
            for msg in messages:
                if msg["role"] == "system":
                    payload_messages.append(msg)
                    break

            # 2. 添加时间戳上下文(如果有)
            if timestamp_contexts:
                # 添加分隔提示
                payload_messages.append({
                    "role": "system",
                    "content": f"以下是{'AI提到的' if user_confirming else '用户请求的'}时间戳附近的聊天记录:"
                })
                payload_messages.extend(timestamp_contexts)
                payload_messages.append({
                    "role": "system",
                    "content": "以上是历史对话记录，请基于这些信息回答用户的当前问题。记住，引用历史索引时不要使用[索引主题]格式。"
                })
            elif not is_timestamp_query:
                # 3. 添加历史上下文(仅在非时间戳查询模式下)
                payload_messages.extend(chat_history)

            # 4. 添加当前对话(除了系统提示外的最新消息)
            for msg in messages:
                if msg["role"] != "system" and msg not in chat_history:
                    payload_messages.append(msg)
        else:
            # 不包含历史，只使用当前消息
            payload_messages = messages

        # 准备请求负载
        api_url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
        }

        payload = {
            "model": "deepseek-chat",
            "messages": payload_messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS
        }

        # 发送API请求
        logger.info('\n正在调用DeepSeek API...')
        response = requests.post(api_url,headers=headers,json=payload)
        response.raise_for_status() # 检测访问是否成功的函数
        #requests.post() 方法发送一个 HTTP POST 请求到 api_url，携带 headers 和 payload。这个请求会把数据发送到 DeepSeek 服务器，并等待其响应。

        # 解析响应
        resp_data = response.json() # 从json格式转换为python字典格式抓换

        if 'choices' in resp_data and len(resp_data['choices']) > 0:
            ai_message = resp_data['choices'][0]['message']['content']

            # 获取用户输入
            user_input = messages[-1]['content'] if len(messages) >= 1 else ''

            # 检测是否为上下文检索或时间戳查询模式
            is_context_query = re.search(re.search(p, user_input) for p in [r'查找.*?对话', r'找到.*?聊天记录', r'检索.*?记录',
                r'查看.*?对话', r'回忆.*?对话', r'回看.*?聊天',
                r'之前.*?说过', r'之前.*?讨论', r'之前.*?提到'])

            is_timestamp_query = re.search(r'(\d{4}-\d{2}-\d{2})?\s?(\d{2}:\d{2}:\d{2})',user_input) is not None

            # 检测是否是AI提到时间戳的确认回复
            if len(messages) >= 3: # 确保足够多的消息历史
                last_ai_response = messages[-2]['content'] if messages[-2]['role'] == 'assistant' else ''
                user_confirmation = any(re.search(p,user_input).lower() for p in [r'^要$', r'^是$', r'^确认$', r'^好的?$', r'^同意$', r'^继续$',
                    r'^ok$', r'^okay$', r'^可以$', r'^请继续$', r'^继续查看$'])

                if user_confirmation and re.search(r'\d{2}:\d{2}:\d{2}',last_ai_response):
                    is_timestamp_query = True
                    logger.info("检测到用户确认查看AI提到的时间戳对话")

            # 如果处于上下文检索模式，处理AI回复，避免误触索引
            if is_context_search or is_timestamp_query:
                ai_message = _sanitize_ai_response(ai_message,True)

            # 只在非检索模式下增加对话计数
            if not is_context_search and not is_timestamp_query:
                current_count = increment_dialog_counter()

                # 检查是否应该更新索引
                should_update = False
                force_update = False

                # 条件1：对话次数达到阈值
                if current_count >= INDEX_DIALOG_THRESHOLD:
                    should_update = True
                    reset_dialog_counter() # 重置计数器
                    logger.info(f'对话次数达到阈值（{INDEX_DIALOG_THRESHOLD}），触发索引更新')

                # 条件2：AI回复中包含特定格式的索引标记
                topic_match = re.search(r'\[索引主题\]：(.*?)\[结束\]',ai_message)
                if topic_match:
                    current_topic = topic_match.group(1).strip()
                    current_time = time.time()

                    # 检查时间间隔和主题相似度
                    time_diff = current_time - _last_index_time

                    # 如果距离上次索引时间太短且主题相似，则跳过
                    if time_diff < _MIN_INDEX_INTERVAL and (_last_index_topic == current_topic or current_topic in _last_index_topic or _last_index_topic in current_topic):
                        logger.info(f'跳过相似主题索引，间隔仅{time_diff:.0f}秒：{current_topic}')
                    else:
                        should_update = True
                        force_update = True
                        _last_index_topic = current_topic
                        _last_index_time = current_time

                # 执行索引更新
                if should_update and len(messages) >= 2:
                    ai_update_topic_index(user_input,ai_message,force_update=force_update)

            return messages
        else:
            logger.error(f'API响应中未找到choices：{resp_data}')
            messages.append({'role':'assistant','content':"抱歉，爱莉的魔法失效了，请等一会再来吧"})
            return messages

    except Exception as e:
        logger.error(f'与DeepSeek API交互时出错：{str(e)}')
        traceback.print_exc() #  会把当前正在处理的异常的**完整回溯（traceback / stack trace）**打印出来，默认输出到标准错误流（sys.stderr）
        messages.append({'role':'assistant','content':'抱歉，发生了一个小错误，请稍后再尝试'})
        return messages

def load_chat_by_timestamp(date, time_str, context_size=30):
    """根据日期和时间戳加载特定时间附近的聊天记录
    Args:
        :param date:  日期字符串（YYYY-MM-DD）,如果为None则会在所有日志文件中搜索
        :param time_str:时间字符串（HH:MM:SS）
        :param context_size30:返回的上下文大小（时间点前后各半数）

    Returns:
        包含上下文对话的列表
    """
    try:
        # 获取日志文件
        log_dir = get_chatlog_dir()

        # 如果提供了特定日期，优先检查该日期的文件
        if date:
            log_file = os.path.join(log_dir,f'{date}.txt')

            if os.path.exists(log_file):
                history = _load_chat_from_file(log_file,time_str,context_size)
                if history:
                    return history
                logger.warning(f'在指定日期{date}的文件中找不到时间戳：{time_str}')

        # 如果没有提供日期或在指定日期文件中未找到，则搜索所有日志文件
        log_files = [f for f in os.listdir(log_dir) if f.endswith('.txt') and f != SUMMARY_FILE and f != METADATA_FILE]

        # 按修改时间排序（最新的在前）
        log_files.sort(key=lambda x: os.path.getmtime(os.path.join(log_dir,x)),reverse=True)

        # 从最新的文件开始搜索
        for log_file_name in log_files:
            file_date = log_file_name.replace('.txt','') # 将文件名改成时间
            # 跳过已经检查过的日期文件
            if date and file_date == date:
                continue

            log_file = os.path.join(log_dir,log_file_name)
            history = _load_chat_from_file(log_file, time_str,context_size)

            if history:
                logger.info(f'在日期{file_date}的文件中找到了时间戳{time_str}的对话')
                return history

        logger.warning(f'在所有日志文件中都找不到时间戳：{time_str}')
        return []
    except Exception as e:
        logger.error(f'加载时间戳对话记录时出错：{e}')
        return []

def _load_chat_from_file(log_file, time_str, context_size=30):
    """从指定文件中加载特定时间附近的聊天记录
    Args：
        :param log_file: 日志文件路径
        :param time_str: 时间字符串（HH:MM:SS）
        :param context_size:返回的上下文大小

    Return:
        包含上下文对话的列表，如果未找到则返回空列表
    """
    try:
        # 提取文件日期
        file_name = os.path.basename(log_file) # 去除路径，只提取文件的名字，这里就是(日期.txt)
        file_date = file_name.replace('.txt','')

        # 读取日志文件
        with open(log_file,'r',encoding='utf-8') as f:
            content = f.read()

        # 分割对话片段
        segments = content.split('-'*50)
        segments = [s.strip for s in segments if s.strip()]

        # 查找对话片段
        target_idx = -1
        for i, segment in enumerate(segments):
            lines = segment.strip().split('\n')
            time_line = next((line for line in lines if line.startswith("时间：")),'') # 迭代器，把满足条件的拿出来，否则为空
            if time_line and time_str in time_line:
                target_idx = i
                break
        if target_idx == -1:
            # 如果没有精确匹配，尝试近似匹配
            time_obj = datetime.datetime.strftime(time_str,'%H:%M:%S') #第一个datatime是模块名，第二个datetime是调用的类，第三个是函数。作用是将time_str字符串格式转化为datetime.datetime格式
            best_diff = float('inf')

            for i, segment in enumerate(segments):
                lines = segment.strip().split('\n')
                time_line = next((line for line in lines if line.startswith('时间：')),'')
                if time_line:
                    # 提取时间部分
                    segment_time = time_line.replace('时间：','').strip()
                    if " " in segment_time: # 如果包含日期和时间
                        segment_time = segment_time.split(" ")[1] # 获取时间部分

                    try:
                        segment_time_obj = datetime.datetime.strptime(segment_time,'%H:%M:%S')
                        # 计算时间差（秒）
                        time_diff = abs((segment_time_obj - time_obj)).total_second()
                        if time_diff < best_diff:
                            best_diff = time_diff
                            target_idx = i
                    except ValueError:
                        continue
            if target_idx == -1 or best_diff > 3600: # 如果最佳匹配超过1小时，认为无匹配
                return []

        # 计算上下文的开始和结束索引
        half_size = context_size // 2
        star_idx = max(0,target_idx - half_size)
        end_idx = min(len(segments), target_idx + half_size + 1)

        # 提取上下文对话
        history = []
        for i in range(star_idx,end_idx):
            segment =segments[i]
            lines = segment.strip().split('\n')
            if len(lines) >= 3: # 确保有时间，用户和娜迦的内容
                time_line = next((line for line in lines if line.startswith("时间：")),'')
                user_line = next((line for line in lines if line.starswith('用户：')),'')
                naga_line = next((line for line in lines if line.starswith('娜迦：')),'')

                if time_line and user_line and naga_line:
                    time_content = time_line.replace("时间: ", "").strip()
                    user_content = user_line.replace("用户: ", "").strip()
                    naga_content = naga_line.replace("娜迦: ", "").strip()

                    # 特殊标记当前目标对话
                    if i == target_idx:
                        prefix = '【目标对话】' if i == target_idx else ''
                        history.append({'role':'system','content':f'{prefix}时间：{time_content}(来自{file_date})'}
                                       )

                    history.append({'role':'user','content':user_content})
                    history.append({'role':'assistant','content':naga_content})

        if history:
            logger.info(f'已加载时间戳{time_str}附近的{len(history)//2}条对话记录 (来自{file_date})')
            return history
        return []
    except Exception as e:
        logger.error(f'从文件{log_file}加载对话记录是出错：{e}')
        return []




















































