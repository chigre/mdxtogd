# mdxtogd v2.9

v2.9 新增：让 GoldenDict 正确识别 StarDict 的语言方向。

## 语言设置

例如：

```text
INDEX_LANGUAGE = 英语
CONTENTS_LANGUAGE = 中文
```

内部仍归一化为：

```text
eng / zho
```

DSL：

```text
#INDEX_LANGUAGE "English"
#CONTENTS_LANGUAGE "Chinese"
```

Android 安装目录：

```text
ENG/ENG-ZHO/词典名
```

## StarDict 文件名

StarDict 自动使用 GoldenDict 可识别的两字母语言对：

```text
词典名.en-zh.ifo
词典名.en-zh.idx
词典名.en-zh.dict
词典名.en-zh.dict.dz
```

而 `.ifo` 内会强制保持：

```text
bookname=词典名
```

因此：

- GoldenDict 用 `en-zh` 判断 English -> Chinese
- 界面仍显示原来的词典名称

其它示例：

```text
eng + eng -> 词典名.en-en.*
zho + eng -> 词典名.zh-en.*
fra + zho -> 词典名.fr-zh.*
deu + zho -> 词典名.de-zh.*
jpn + zho -> 词典名.ja-zh.*
```

如果任一语言为 `Unk` 或没有可靠的两字母代码：

```text
词典名.ifo
词典名.idx
词典名.dict
```

不会写入错误的语言后缀。

## makestardict.bat

手工修改：

```text
词典名.android.txt
```

后双击 `makestardict.bat`，仍然会重新生成：

```text
词典名.en-zh.*
```

并保持：

```text
bookname=词典名
```

## 快捷模式

```bat
python mdxtogd.py SOURCE_FILE out/NewDict.ifo
```

第二个参数仍用于确定输出目录和词典基础名。

如果语言为 `eng -> zho`，实际 StarDict 输出：

```text
out/NewDict.en-zh.ifo
out/NewDict.en-zh.idx
out/NewDict.en-zh.dict
out/NewDict.en-zh.dict.dz
```

DSL 仍保持干净名称：

```text
out/NewDict.dsl
out/NewDict.dsl.files.zip
```

图标与 StarDict basename 保持一致：

```text
out/NewDict.en-zh.bmp
```


## v2.10：图标与 StarDict basename 统一

如果语言为：

```text
eng -> zho
```

正式词典文件统一为：

```text
词典名.en-zh.ifo
词典名.en-zh.idx
词典名.en-zh.dict
词典名.en-zh.dict.dz
词典名.en-zh.bmp
```

DSL 资源壳仍保持：

```text
词典名.dsl
词典名.dsl.files.zip
```

如果语言无法可靠确定，StarDict 不加语言对后缀，图标同样退回：

```text
词典名.bmp
```
