# import numpy as np
# content = "床前明月光，\n疑是地上霜。\n举头望明月，\n低头思故乡。"
# print(content)
# segments = content.split('-'*1)
# print(segments)
#
# x = np.arange(10)
# print(x)
# print(x[-2:0])
#
# y = ""
# if y:
#     print("y为true")
# else:
#     print("y为false")

# import re
#
# text = "今天是 2025-09-05 12:34:56，记录一下"
#
# # 正则：可选日期 + 时间
# pattern = r'(\d{4}-\d{2}-\d{2})?.?(\d{2}:\d{2}:\d{2})'
# match = re.search(pattern, text)
#
# print("match 对象:", match)                     # <re.Match object; span=(3, 22), match='2025-09-05 12:34:56'>
# print("group(0):", match.group(0))              # 整体匹配 → "2025-09-05 12:34:56"
# print("group(1):", match.group(1))              # 第 1 个捕获组 (日期) → "2025-09-05"
# print("group(2):", match.group(2))              # 第 2 个捕获组 (时间) → "12:34:56"
# print("span:", match.span())                    # 匹配的起止位置 → (3, 22)
#
# print(type(match))


# 示例：打印到控制台 / 捕获为字符串 / 写入文件
# import traceback
# import io
#
# def func_that_raises():
#     # 故意抛一个异常
#     return 1 / 0
#
# # 1) 使用 print_exc()，默认打印到 stderr（控制台）
# try:
#     func_that_raises()
# except Exception:
#     print("=== 使用 traceback.print_exc()（默认输出 stderr） ===")
#     traceback.print_exc()   # 直接把完整 traceback 打印到标准错误
#
# # 2) 使用 format_exc() 获取 traceback 字符串（适合上报或写日志）
# try:
#     func_that_raises()
# except Exception:
#     tb_str = traceback.format_exc()   # 返回字符串
#     print("\n=== 使用 traceback.format_exc() 得到的字符串（可存储或发送） ===")
#     print(tb_str)  # 你可以把 tb_str 存到数据库或发送到监控服务
#
# # 3) 把 traceback 写入自定义文件或 StringIO
# try:
#     func_that_raises()
# except Exception:
#     buf = io.StringIO()
#     traceback.print_exc(file=buf)     # 将 traceback 写入 buf（而非直接打印）
#     content = buf.getvalue()
#     buf.close()
#     # 现在 content 就包含 traceback，可以写入文件或上传
#     with open("error_trace.txt", "w", encoding="utf-8") as f:
#         f.write(content)
#     print("\n已把 traceback 写入 error_trace.txt")


import datetime

time_str = "13:45:30"   # 这是一个字符串

# strptime = string parse time
dt = datetime.datetime.strptime(time_str, "%H:%M:%S")

print("原始字符串:", time_str)
print("解析后的 dt:", dt)
print("dt 的类型:", type(dt))
