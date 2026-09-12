最近整理了一套自己一直在用的词典转换脚本，

主要用于把 **MDict/MDX 词典转换成适合 Android GoldenDict 使用的 StarDict + DSL 资源词典**。

脚本名称：

```text
mdxtogd.py
```

配置文件：

```text
config.txt
```

目前支持的输入格式包括：

```text
MDX
Tabfile
MDict Textfile
```

其中 MDict Textfile 指类似下面这种格式：

```text
词条1
内容第一行
内容第二行
</>
词条2
内容
</>
```

程序会先统一转成 Tabfile。正文中的实际换行会转换为字面量 `\n`，因此每个词条在 Tabfile 中始终只占一行，之后再继续进行资源路径替换和 StarDict 转换。

## 一、主要功能

### 1. 支持 MDX + 多个 MDD

如果输入：

```text
词典.mdx
```

程序会自动寻找同目录下的：

```text
词典.mdd
词典.1.mdd
词典.2.mdd
……
```

无需在配置文件中逐个填写。

MDD 中的图片、CSS、JS、字体、音频等资源会解包并重新整理，然后生成 Android GoldenDict 使用的：

```text
词典.dsl
词典.dsl.files.zip
```

DSL 使用 UTF-8 with BOM。

---

### 2. 支持本地资源

有些 MDX 中引用的 CSS、图片或字体并不在 MDD 里，而是直接放在词典文件旁边，例如：

```text
词典.mdx
mecd.css
images/
fonts/
```

程序也会尝试解析这些实际被引用到的本地资源，并纳入相同的资源重写流程。

CSS 内部继续引用的图片、字体等资源，也会进一步解析。

---

### 3. 资源包支持两种目录方式

配置：

```text
resource_layout = root
```

表示把资源全部放到 `.dsl.files.zip` 根目录。

如果存在同名文件，会自动重命名，并同步修改正文/CSS/JS 中的引用。

也可以：

```text
resource_layout = original
```

保留 MDD 原来的目录结构，例如：

```text
images/a.png
css/style.css
fonts/font.woff2
```

对于资源特别多的词典，我个人更推荐 `original`，管理和排查都比较方便。

---

### 4. CSS 可以放 ZIP，也可以独立放文件夹

```text
css_storage = zip
```

CSS 放入：

```text
词典.dsl.files.zip
```

或者：

```text
css_storage = folder
```

CSS 作为独立文件，与正式词典文件放在同一目录。

---

## 二、自动处理 Android GoldenDict 资源路径

程序会根据 DSL 在 Android GoldenDict 中的实际安装路径，计算 DSL resource ID，并把类似：

```text
images/a.png
../fonts/font.woff2
mecd.css
```

改写成 Android GoldenDict 能访问的资源地址。

例如：

```text
content://mobi.goldendict.android/resource/<DSL_ID>/images/a.png
```

DSL resource ID 使用 DSL 相对于 GoldenDict 根目录的路径计算。

例如：

```text
/storage/emulated/0/GoldenDict/ENG/ENG-ZHO/词典名/词典名.dsl
```

实际参与计算的是：

```text
ENG/ENG-ZHO/词典名/词典名.dsl
```

---

## 三、自动识别词典语言

配置文件中强烈建议填写：

```text
INDEX_LANGUAGE =
CONTENTS_LANGUAGE =
```

不过写法比较宽松。

例如英语可以写：

```text
eng
en
English
english
英语
英文
英
```

中文可以写：

```text
zho
zh
chi
Chinese
中文
汉语
漢語
汉
漢
中
```

程序内部会统一转换成标准代码。

例如：

```text
INDEX_LANGUAGE = 英
CONTENTS_LANGUAGE = 汉
```

会统一识别成：

```text
eng → zho
```

DSL 中则自动生成：

```text
#INDEX_LANGUAGE "English"
#CONTENTS_LANGUAGE "Chinese"
```

如果没有填写，程序还会尝试从词典文件名判断，例如：

```text
xx英汉词典
→ eng / zho

xx汉英词典
→ zho / eng

英英词典
→ eng / eng

POR-ZH
→ por / zho
```

无法可靠判断时使用：

```text
Unk / Unk
```

建议还是手工填写，自动判断主要作为兜底。

---

## 四、StarDict 的语言也会自动处理

这是专门针对 GoldenDict 做的一项处理。

StarDict 本身没有 DSL 那样的：

```text
#INDEX_LANGUAGE
#CONTENTS_LANGUAGE
```

GoldenDict 可以根据 StarDict 文件名中的语言对判断语言。

因此，例如：

```text
INDEX_LANGUAGE = eng
CONTENTS_LANGUAGE = zho
```

StarDict 自动生成：

```text
词典名.en-zh.ifo
词典名.en-zh.idx
词典名.en-zh.dict
词典名.en-zh.dict.dz
```

这样 GoldenDict 可以识别为：

```text
English → Chinese
```

但是 `.ifo` 内仍然保持：

```text
bookname=词典名
```

因此词典在 GoldenDict 中显示的仍然是原来的词典名，不会显示成：

```text
词典名.en-zh
```

类似地：

```text
zho → eng
生成 .zh-en.*

eng → eng
生成 .en-en.*

fra → zho
生成 .fr-zh.*
```

如果某一端语言无法确定，则不会强行添加错误的语言后缀。

---

## 五、Android 目录自动生成

如果不填写：

```text
install_dir =
```

程序会按照语言自动生成目录。

例如：

```text
INDEX_LANGUAGE = eng
CONTENTS_LANGUAGE = zho
```

默认得到：

```text
ENG/ENG-ZHO/词典名
```

最终 Android 位置类似：

```text
/storage/emulated/0/GoldenDict/
└─ ENG/
   └─ ENG-ZHO/
      └─ 词典名/
```

这样词典多了以后，可以按照：

```text
源语言
→ 语言方向
→ 具体词典
```

来分类。

转换完成后还会自动生成：

```text
GoldenDict安装位置.txt
```

里面直接写明应该把正式词典文件复制到 Android 的哪个目录。

---

## 六、自动处理词典图标

如果 MDX/Textfile/Tabfile 同目录存在同名图片：

```text
词典.png
词典.jpg
词典.jpeg
词典.bmp
```

程序会自动找到并转换为：

```text
词典.bmp
```

尺寸：

```text
48 × 64
```

用于 GoldenDict 词典图标。

图片会保持原始宽高比缩放，并居中到 48×64 画布，避免直接拉伸变形。

图像转换需要：

```text
Pillow
```

可以安装：

```bat
python -m pip install Pillow
```

---

## 七、最终 Tabfile 会保留下来

程序完成各种：

```text
entry://
图片路径
CSS路径
JS路径
字体路径
其它资源路径
```

替换以后，会保留：

```text
词典名.android.txt
```

这是最终送入 StarDict 转换前的 Tabfile。

因此，如果转换完成后还想手工修改正文，可以直接编辑这个文件。

同时程序会生成：

```text
makestardict.bat
_makestardict.py
```

修改完：

```text
词典名.android.txt
```

以后直接双击：

```text
makestardict.bat
```

即可重新生成 StarDict，不需要重新跑 MDX/MDD 解包和资源转换过程。

重新生成时同样会保持：

```text
词典名.en-zh.*
```

这样的语言标记。

---

## 八、StarDict 的 `.dict` 与 `.dict.dz`

配置：

```text
stardict_dictzip = true
```

会同时保留：

```text
词典名.en-zh.dict
词典名.en-zh.dict.dz
```

如果：

```text
stardict_dictzip = false
```

则只生成：

```text
词典名.en-zh.dict
```

生成 `.dict.dz` 需要：

```bat
python -m pip install python-idzip
```

---

## 九、配置文件尽量简化

目前 `config.txt` 采用普通文本：

```text
key = value
```

不使用 JSON，方便直接打开修改。

最基本可以只写：

```text
source_file = ./词典.mdx
```

推荐再填写：

```text
INDEX_LANGUAGE = eng
CONTENTS_LANGUAGE = zho
```

其它项目一般都有默认值。

一个常用示例：

```text
source_file = ./外研社英汉多功能词典.mdx
input_type = auto

INDEX_LANGUAGE = 英
CONTENTS_LANGUAGE = 汉

dictionary_name =
output_dir =

device_goldendict_root = /storage/emulated/0/GoldenDict
install_dir =

css_storage = zip
resource_layout = original

local_resource_dirs = .
local_resource_recursive = true

rewrite_inside_resources = true

stardict_dictzip = true
stardict_html = true

keep_raw_tabfile = false
```

其中：

```text
dictionary_name =
output_dir =
```

留空时会自动根据输入文件名生成。

---

## 十、两种运行方式

### 方法 1：使用 config.txt

```bat
python mdxtogd.py
```

程序默认读取当前目录的：

```text
config.txt
```

---

### 方法 2：直接指定输入和输出

```bat
python mdxtogd.py xx/词典.mdx yy/新词典名称.ifo
```

Tabfile/Textfile 也可以：

```bat
python mdxtogd.py dict.tab out/NewDict.ifo
python mdxtogd.py dict.txt out/NewDict.ifo
```

如果语言是：

```text
eng → zho
```

最终 StarDict 会自动生成：

```text
out/NewDict.en-zh.ifo
out/NewDict.en-zh.idx
out/NewDict.en-zh.dict
out/NewDict.en-zh.dict.dz
out/NewDict.en-zh.bmp
```

而 DSL 和 ZIP压缩包 仍然保持：

```text
NewDict.dsl
NewDict.dsl.files.zip
```

---

## 十一、主要依赖

核心需要：

```text
Python
PyGlossary
mdict-utils
```

建议同时安装：

```text
Pillow
python-idzip
```

例如：

```bat
python -m pip install pyglossary mdict-utils Pillow python-idzip
```

部分 PyGlossary 插件可能还会提示缺少 `lxml`，如果希望一起安装：

```bat
python -m pip install lxml
```

---

## 十二、输出目录示例

例如：

```text
外研社英汉多功能词典/
```

转换工作目录大致如下：

```text
外研社英汉多功能词典/
├─ 外研社英汉多功能词典/
│  ├─ 外研社英汉多功能词典.dsl
│  ├─ 外研社英汉多功能词典.dsl.files.zip
│  ├─ 外研社英汉多功能词典.en-zh.ifo
│  ├─ 外研社英汉多功能词典.en-zh.idx
│  ├─ 外研社英汉多功能词典.en-zh.dict
│  ├─ 外研社英汉多功能词典.en-zh.dict.dz
│  └─ 外研社英汉多功能词典.en-zh.bmp
│
├─ 外研社英汉多功能词典.android.txt
├─ makestardict.bat
├─ _makestardict.py
├─ GoldenDict安装位置.txt
└─ conversion_report.json
```

Android 端只需要复制内层正式词典目录中的文件。

---

## 十三、一些说明

这套脚本主要是按我自己在 Android GoldenDict 上实际使用词典的需求逐步整理出来的，因此重点不是做一个通用格式转换器，而是尽量把：

```text
MDX/MDD
↓
资源整理
↓
Android GoldenDict DSL资源
↓
StarDict
↓
语言识别
↓
目录部署
```

这一整套过程自动化。

不同 MDX 的 HTML/CSS/JS 写法差异很大，因此不敢保证所有词典都能完全无修改直接转换。如果碰到特殊资源路径、特殊脚本、特殊 MDD 结构等问题，也欢迎反馈具体词典结构或报错信息，后续可以继续完善。

建议第一次转换新词典后，重点检查：

```text
conversion_report.json
GoldenDict安装位置.txt
词典名.android.txt
```

如果有：

```text
⚠️ 未解析本地资源
```

最好先确认对应资源到底是在 MDD、本地文件夹，还是原词典引用本身已经失效。

目前我自己主要用于 Android GoldenDict 的 MDX → StarDict + DSL resource 转换，欢迎大家测试、改进和反馈。
