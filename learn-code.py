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

import re

text = "今天是 2025-09-05 12:34:56，记录一下"

# 正则：可选日期 + 时间
pattern = r'(\d{4}-\d{2}-\d{2})?.?(\d{2}:\d{2}:\d{2})'
match = re.search(pattern, text)

print("match 对象:", match)                     # <re.Match object; span=(3, 22), match='2025-09-05 12:34:56'>
print("group(0):", match.group(0))              # 整体匹配 → "2025-09-05 12:34:56"
print("group(1):", match.group(1))              # 第 1 个捕获组 (日期) → "2025-09-05"
print("group(2):", match.group(2))              # 第 2 个捕获组 (时间) → "12:34:56"
print("span:", match.span())                    # 匹配的起止位置 → (3, 22)

print(type(match))