# 表格识别方案对比测试报告

> 项目：超快激光论文知识库 · 四方案独立对比（PyMuPDF / Docling / PaddleOCR / Camelot）
> 数据日期：2026-08-11（PaddleOCR 4 例失败案例补跑完成后）
> 数据文件：`results/summary.json`、`results/summary.csv`、`results/diagnostics.json`、`results/review/<case_id>/`

## 1. 测试环境

| 项 | 值 |
|---|---|
| OS | Windows 11 Pro（10.0.26100），CPU only，无 CUDA |
| Python | 3.12.13（四个独立虚拟环境） |
| 语料 | `data/literature_archive/` 真实超快激光论文 14 篇 |
| 样本 | 21 个 Gold 表格 case（手工标注，`gold/*.json` 为唯一行数据源） |
| 指标脚本 | `evaluate.py`（Table Recall / Shape / Cell / Numeric / Header-Value / Runtime） |
| 结果保留 | 每个工具每个 case 均保存统一 `rows[][]` 结果 + 工具原始输出（`*_raw.json`）+ `env.json` + `pip_freeze.txt` |

四个工具分别运行在独立虚拟环境，避免 PyTorch / PaddlePaddle / OpenCV 依赖冲突；benchmark 代码未侵入 `src/ultrafast_ingestion/`、`src/ultrafast_knowledge/`。

## 2. 四种工具准确版本

| 工具 | 运行环境 | 准确版本（以 pip_freeze 为准） |
|---|---|---|
| PyMuPDF | `.venv-table-pymupdf` | pymupdf 1.28.2 |
| Docling + TableFormer | `.venv-table-docling` | docling 2.119.0、docling-core 2.91.0、torch 2.13.0、transformers 5.15.0；TableFormer `ACCURATE` |
| PaddleOCR PP-StructureV3 | `.venv-table-paddle` | paddleocr 3.7.0、paddlepaddle 3.2.2（CPU）、paddlex 3.7.2；pymupdf 1.28.2 仅用于页面渲染 |
| Camelot 2.0 `flavor="ml"` | `%LOCALAPPDATA%\Temp\cv` | camelot-py 2.0.0、torch 2.13.0+cpu、timm 1.0.28、transformers 4.57.6、opencv-python-headless 5.0.0.93 |

说明：任务文档安装示例为 `paddlepaddle==3.3.0`，本机 Python 3.12 实际安装为 3.2.2（见 `results/paddleocr/pip_freeze.txt`，以实测为准）。Camelot 因 torch 无法在中文长路径解包（见第 8 节），实际运行环境在 `%LOCALAPPDATA%\Temp\cv`，由 `run_all.py` 的 `TABLE_BENCH_VENV_CAMELOT` 覆盖机制指定。

## 3. benchmark 样本说明

21 个 case 分布：

| 表格类型 | 数量 | 说明 |
|---|---|---|
| bordered（有线表） | 14 | 元素成分、工艺参数、正交实验结果、孔/槽几何数据等 |
| borderless（三线/无线表） | 5 | 参数-值表、矩阵表、多块网格 |
| image（图片型表格） | 1 | 表格主体为栅格图、无文本层（`179b114f-p5-t1`），仅评检出 |
| figure（图型两栏表） | 1 | 双面板图式表（`3c0cf585-p4-t1`），仅评检出 |

其中 19 个 case 有完整 gold rows（shape/cell/numeric/header-value 全评），2 个 case（image/figure）只有检出评分。

指标口径（`evaluate.py`）：
- Table Recall：至少一个预测表包含匹配的 gold 非空单元格即算检出；
- Shape：行数与列数同时精确一致；
- Cell：对齐后单元格精确匹配比例；
- Numeric：gold 数值单元格内数字 token 序列精确一致；
- Header-Value：值单元格同时保持正确列头与行头；
- 归一化仅做空白折叠、μ/µ→u、U+2212→-，不做单位换算、四舍五入或语义修复。

## 4. 总指标

| Tool | Recall | Shape | Cell | Numeric | Hdr | Cold(s) | Warm(s) | Fail |
|---|---|---|---|---|---|---|---|---|
| pymupdf | 0.143 | 0.000 | 0.004 | 0.009 | 0.000 | 0.06 | 0.13 | 0 |
| docling | 0.619 | 0.053 | 0.314 | 0.459 | 0.012 | 14.69 | 3.38 | 0 |
| paddleocr | 0.381 | 0.263 | 0.253 | 0.272 | 0.233 | 107.68 | 133.71 | 0 |
| camelot | **0.857** | **0.737** | **0.659** | **0.732** | **0.517** | 2.79 | 0.51 | 0 |

要点：
- Camelot 在 Recall / Shape / Cell / Numeric / Header-Value 五项全部第一，且速度比 Docling 快约 7 倍、比 PaddleOCR 快约 260 倍；
- Docling 数值恢复第二（0.459），但表头-值关联几乎为零（0.012），结构精度仅 0.053；
- PaddleOCR 无失败案例，但只检出 8/21（0.381）；对成功检出的表质量很高（多例满分）；
- PyMuPDF 在真实科学表格上基本失效。

## 5. 每类表格指标

### 5.1 bordered（14 例，可评 14）

| Tool | Recall | Shape | Cell | Numeric | Hdr |
|---|---|---|---|---|---|
| pymupdf | 0.071 | 0.000 | 0.005 | 0.012 | 0.000 |
| docling | 0.643 | 0.071 | 0.327 | 0.460 | 0.016 |
| paddleocr | 0.214 | 0.214 | 0.207 | 0.214 | 0.186 |
| camelot | **1.000** | **0.857** | **0.736** | **0.839** | **0.559** |

Camelot 对有线表 14/14 全检出，结构 12/14 精确。

### 5.2 borderless（5 例，可评 5）

| Tool | Recall | Shape | Cell | Numeric | Hdr |
|---|---|---|---|---|---|
| pymupdf | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| docling | 0.600 | 0.000 | 0.278 | 0.457 | 0.000 |
| paddleocr | **0.800** | **0.400** | 0.380 | **0.433** | 0.367 |
| camelot | **0.800** | **0.400** | **0.442** | **0.433** | **0.400** |

无线表是当前数据集最难的类别：Camelot 与 PaddleOCR 检出最好但结构都只对 2/5；Docling 数值尚可但表头全丢。

### 5.3 image（1 例，仅检出）

| Tool | Recall |
|---|---|
| pymupdf | 1.000（strategy=text 全页文本兜底，非真实解析，见 7.1） |
| docling | 1.000（OCR 出 3×6 数值矩阵，内容真实） |
| paddleocr | 1.000（OCR 出 5×7 矩阵，含 α/β 表头，内容真实） |
| camelot | 0.000（完全漏检） |

### 5.4 figure（1 例，仅检出）

| Tool | Recall |
|---|---|
| pymupdf | 1.000（输出为坐标轴文本碎片，非表格） |
| docling | 0.000 |
| paddleocr | 0.000 |
| camelot | 0.000 |

## 6. 典型成功案例

- **Camelot `185a6a06-p5-t1`（borderless 参数表）**：7 行全部正确，Shape/Numeric/Hdr 全 1.000，Parameters/Values 表头完整。
- **Camelot `fa290122-p10-t1`（复杂合并表头，Nitrogen/Air 分组）**：识别出 17×7，正确保留分组行，Numeric 1.000、Hdr 0.833。
- **Camelot `e9dbf6f7-p6-t1`（转置布局 1×10）**：Shape/Numeric/Hdr 全 1.000。
- **Camelot `aad1014d-p6-t2`（25 行 L25 正交实验表）**：Shape/Numeric/Hdr 全 1.000。
- **PaddleOCR `33dae6e7-p3-t1` / `33dae6e7-p4-t2`（有线表）**：Shape/Cell/Numeric/Hdr 全 1.000，其中 14 行实验方案表无污染。
- **PaddleOCR `185a6a06-p5-t1`（borderless）**：Shape/Numeric 1.000、Hdr 0.833。
- **PaddleOCR `c5f4b1ec-p6-t3`（borderless 多行单元格）**：Shape/Numeric/Hdr 全 1.000。
- **Docling `fa290122-p10-t1`**：数值列恢复极好（Numeric 0.988），但表头行丢失（Hdr 0.000）。
- **Docling / PaddleOCR `179b114f-p5-t1`（图片型表格）**：从无文本层栅格图 OCR 出数值矩阵（Docling 3×6；Paddle 5×7 带 α/β 表头），这是 PyMuPDF/Camelot 做不到的。

## 7. 典型失败案例

- **PyMuPDF `33dae6e7-p3-t1`**：把整页正文当表格，输出 46×7 行文本碎片；`fa290122-p10-t1` 输出 51×10 碎片；5 个 borderless 全未检出；`3c0cf585`（figure）输出坐标轴标签碎片。结论：`find_tables()` + `strategy="text"` 对科学论文表格不可用。
- **Docling `3c59d7dc-p4-t2`**：4 行数据正确但整体缺表头行（Shape 0、Hdr 0）；`fa290122-p10-t1` 表头被替换为 "Nitrogen"×7；`33dae6e7-p4-t2` 行列结构错乱（Shape 0）。复杂合并表头是 Docling 的主要短板。
- **PaddleOCR**：13/21 未检出（6da19607 系列 3 例、aad1014d 系列 2 例、e9dbf6f7 系列 2 例、fa290122、4ae395a7、64edf201、c08322e5、c5f4b1ec-p3-t1 等）；`c5f4b1ec-p3-t1` 实际检测出 6×7 网格但把 "C≤ 0.05–0.15" 拆成两行两格，与 gold 的 3×7 合并单元格表示不一致而被判未检出；`d47fcb19-p5-t1` 结构转置（Numeric 0.167）；OCR 将 μm 误识为 m（如 `185a6a06-p5-t1` 的 "Spot diameter (m)"、`d47fcb19` 多个单元格）。
- **Camelot**：图片型 `179b114f` 与图型 `3c0cf585` 完全漏检（0 表）；`33dae6e7-p4-t2` 结构 15×5 精确但第一列混入正文段落（Hdr 0.214）；`6da19607-p4-t1` 最后一行扫描速度单元格混入页脚 "5 of 16"；`d47fcb19-p5-t1` 结构错误（Numeric 0.167）。

## 8. 安装和运行过程中出现的问题

1. **Camelot 模型下载（HF 网络）**：Hugging Face 直连/代理仅约 0.13 MB/s 且频繁断线。改用 ModelScope 高速下载（约 33 MB/s）并手工装入 `%USERPROFILE%\.cache\huggingface\hub`，涉及三个仓库：`microsoft/table-transformer-detection`、`microsoft/table-transformer-structure-recognition-v1.1-all`、`timm/resnet18.a1_in1k`（Camelot ml 的 timm backbone，易遗漏）。离线运行需 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`。
2. **Windows 长路径无法解包 torch（WinError 206）**：中文工作目录路径过长，`.venv-table-camelot` 内 torch 解包失败、camelot 未装上（该 venv 现存 762 MB 残余）。实际 Camelot 环境迁移至 ASCII 短路径 `%LOCALAPPDATA%\Temp\cv`（1017 MB），`run_all.py` 支持 `TABLE_BENCH_VENV_CAMELOT` 覆盖。
3. **PaddleOCR 页面渲染文件名过长**：`render_page` 原以完整 PDF stem 命名 PNG，路径超长导致 PyMuPDF 打开失败（`FzErrorSystem: code=2`），4 例失败；已改为 `case_id` 命名并补跑完成，现 21/21 无失败。
4. **PaddleX 模型源检查卡死**：本地代理环境下模型源连通性检查挂起，需 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`（脚本已内置）。
5. **PaddlePaddle 版本**：任务文档示例 `paddlepaddle==3.3.0` 在 Python 3.12 下实际安装为 3.2.2；benchmark 以实测版本记录（不调参、不改代码）。
6. **Docling 首次冷启动**：TableFormer ACCURATE 模型需下载，冷启动 14.7s；热页 3.4s/页。

## 9. 各工具资源消耗

| 工具 | 运行内存（运行期观察值） | 磁盘（venv + 模型缓存） |
|---|---|---|
| PyMuPDF | < 0.2 GB | venv 64.5 MB（模型无） |
| Docling | ~1 GB+（torch） | venv 1317.9 MB；HF 缓存含 docling 模型（与 Camelot 共用，见下） |
| PaddleOCR | ~3.7 GB（峰值） | venv 1078.0 MB；PaddleX 官方模型缓存 1791.0 MB |
| Camelot | ~0.8 GB | 实际运行 venv 1016.9 MB；另 `.venv-table-camelot` 残余 762.2 MB（未使用）；HF 缓存含 3 个模型 |

HF 模型缓存总量 2480.4 MB，由 Docling 与 Camelot 共用（docling-layout-heron、docling-models、table-transformer ×2、timm resnet18、sentence-transformers MiniLM）。

速度（本机 CPU）：
- Camelot：冷启动 2.79s，页均 0.51s —— 可在全库批量运行；
- Docling：冷启动 14.69s，页均 3.38s —— 全库约 7 倍于 Camelot；
- PaddleOCR：冷启动 107.68s，页均 133.71s —— 全库不可行（单页约 2 分钟，且内存峰值 3.7GB）；
- PyMuPDF：0.06s / 0.13s —— 最快但质量不合格。

## 10. 推荐结论

**结论：Camelot 2.0 `flavor="ml"` 是本项目下一阶段正式表格提取的最佳基础方案。** PaddleOCR 在“成功检出”的质量上可与 Camelot 匹敌甚至局部更好，但其检出率（8/21）、速度（约 134s/页）与资源（约 3.7GB）使它不适合作为当前全库流程的主方案；Docling 数值恢复好但表头-值关联几乎不可用；PyMuPDF 不可用。

7 个子问题回答：

1. **Numeric Accuracy 最高**：Camelot（0.732），其次 Docling（0.459）、PaddleOCR（0.272）、PyMuPDF（0.009）。Camelot 的数值错位主要来自页脚/正文混入单元格，而非数值本身识别错误。
2. **Header-Value Association 最可靠**：Camelot（0.517），唯一明显优于其他的工具（Docling 0.012、PaddleOCR 0.233、PyMuPDF 0.000）。
3. **三线表（borderless）最好**：Camelot 与 PaddleOCR 并列检出最优（0.800）；Camelot Cell 0.442、Hdr 0.400 略优；但整体只有 40% 结构精确——无线表是当前数据集难点，Camelot 相对最好但仍有提升空间。
4. **复杂表头最好**：Camelot（`fa290122` 保留 Nitrogen/Air 分组行，Hdr 0.833）；Docling 在此类上丢表头（Hdr 0.000）；PaddleOCR 未检出。
5. **图片型表格是否构成当前数据集问题**：构成真实但低频的问题（21 例中 1 例 image + 1 例 figure）。Camelot 对二者均漏检；Docling/PaddleOCR 的 OCR 能恢复图片表数值矩阵（`179b114f` 验证有效）。若正式方案以 Camelot 为主，图片型表格需要单独的 OCR 类工具补充——这是下一任务再设计 fallback 的明确依据，本轮不实现。
6. **单一工具是否足够**：对有线表 + 无线表的文本层表格，Camelot 基本足够（Recall 0.857，bordered 1.000）；对图片型表格不足。
7. **是否确实需要 fallback**：需要，但范围很小——只针对“无文本层/图片型表格”（约 5% 当前样本）。不需要为有线表/无线表设计 fallback；且不应采用 PyMuPDF 作为 fallback（其输出为整页文本碎片，会污染知识库）。

**下一阶段建议（按优先级）**：
1. 以 Camelot 2.0 ml 作为正式表格提取基础（固定版本、模型离线缓存）；
2. 增加“页面无文本层/表格区域为图片”的检测，命中时转 Docling 或 PaddleOCR OCR（二选一，需在下一任务单独小样本对比）；
3. 对 Camelot 输出的页脚/正文污染做边界清理（例如按表格 bbox 裁剪文本），但本轮不实现。
