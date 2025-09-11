#config.py
#全局配置文件

#API配置
DEEPSEEK_API_KEY = ''

#对话相关配置
MAX_HISTORY_ROUNDS = 5  #最多保留的历史对话轮数
TEMPERATURE = 0.7       #生成文本的随机性（0-1）
MAX_TOKENS = 2000        #生成文本的最大长度

#索引相关配置
SUMMARY_ENTRIES_PER_FILE = 10   #每个日志文件提取的最大主题数
SUMMARY_UPDATE_INTERVAL = 86400 #主题摘要更新间隔（秒），默认一天
INDEX_DIALOG_THRESHOLD = 50     #自动更新索引的对话次数阈值
MIN_INDEX_INTERVAL = 600        #最小索引间谍时间（秒），避免频繁添加相似索引
LOG_DIR = 'chatlog'             #日志保存目录
SUMMARY_FILE = 'summary.txt'    #摘要文件名
METADATA_FILE = 'index_metadata.json' #索引元数据文件名

#调试设置
DEBUG = False                   #是否输出调试信息
