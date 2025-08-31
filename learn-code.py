import numpy as np
content = "床前明月光，\n疑是地上霜。\n举头望明月，\n低头思故乡。"
print(content)
segments = content.split('-'*1)
print(segments)

x = np.arange(10)
print(x)
print(x[-2:0])

y = ""
if y:
    print("y为true")
else:
    print("y为false")