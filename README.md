# 中国煤炭高频数据看板

用煤炭 Excel 数据库生成静态网页数据，展示价格、库存、港口运输、旬度日均发电量、月度供给与周报指标。

## 查看网页

下载或克隆仓库后，直接用浏览器打开 `index.html`。网页不依赖外部图表 CDN，可离线查看。包含4个摘要卡片、5组趋势图、44项周报指标，支持图表日期筛选、图例切换、指标分类、搜索和 CSV 下载。

图表可通过鼠标或触摸查看数据，也可以聚焦图表后使用左右方向键。缺失值显示“—”，线图保留缺口；原始数值0继续按0展示。每组图表下方标注数据源的最新日期。

## 首次发布到 GitHub Pages

1. 在自己的 GitHub 账号中新建名为 `coal-dashboard` 的公开仓库。
2. 将本目录文件放到仓库根目录。网页运行所需的文件为 `index.html`、`styles.css`、`app.js`、`data.js`；更新脚本和说明可一并提交。
3. 进入仓库 **Settings → Pages**。
4. Source 选择 **Deploy from a branch**，分支选择 **main**，目录选择 **/(root)**，保存。
5. 发布完成后使用 GitHub Pages 页面给出的实际网址。

官方说明：[配置 GitHub Pages 发布源](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。本地文件准备好不代表已经在 GitHub 创建仓库或发布成功。

## 每次更新数据

先在 Excel 中更新、计算并保存数据库。Python 使用 Excel 已保存的计算结果，不会重新计算公式。

需要 Python 3.9 或更新版本。首次安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

### Mac

在本目录打开终端。默认从当前用户桌面的“周报日报数据库”文件夹选择文件名日期最新的数据库：

```bash
bash 更新数据.command
```

也可以明确指定 Excel 或其所在文件夹：

```bash
bash 更新数据.command "/完整路径/China Coal Database-20261113.xlsx"
```

### Windows PowerShell

在本目录打开 PowerShell，首次安装依赖：

```powershell
python -m pip install -r .\requirements.txt
```

指定本机的 Excel 路径运行：

```powershell
.\update_data.ps1 -Source "C:\你的文件夹\China Coal Database-20261113.xlsx"
```

如果 PowerShell 不允许执行脚本，可直接执行 Python 命令：

```powershell
python .\extract_dashboard_data.py --source "C:\你的文件夹\China Coal Database-20261113.xlsx" --output-dir .
```

### 通用 Python 命令

```bash
python3 extract_dashboard_data.py --source "/完整路径/China Coal Database-20261113.xlsx" --output-dir .
```

生成的 `data.js` 位于本目录，替换网页数据。辅助文件 `data.json` 和 `extraction_report.json` 保留在本地，由 `.gitignore` 排除。运行成功后查看输出和提取报告，再将 `data.js` 上传到 GitHub 仓库根目录，或在已克隆的仓库中执行：

```bash
git add data.js
git commit -m "Update coal dashboard data"
git push origin main
```

已配置为 `main` 根目录发布的 GitHub Pages 会根据该分支的更新重新发布。只有原始数据库更新、没有重新生成和提交 `data.js` 时，线上网页数据不会改变。

## 数据范围与单位

- 周报以“价格、产量、库存、电力、钢铁和化工”的文字标题分区，当前44项，其中42项有本期数值，2项本期源值为 `#N/A`。
- 动力煤价格优先使用 `Raw data-价格_指数` 的 FW2707R 当前区块：CW 日期；CX 为 CCI5500，DV 为鄂尔多斯5500，DX 为大同5500。旧区块仅补充新区块开始之前的历史。
- 北方港口库存采用 FW1203D 口径；曹妃甸港群为 G:K 五个码头合计。当前库存源最后有效日期为2026-08-03，页面数据说明保留提示。
- 北方三港调入为 B+E+H、吞吐为 C+F+I。2026-11-14的部分分港分项为0，按原表加总并保留具体提示。
- 旬度数据按原表日期绘制，展示的是旬度日均发电量，单位亿千瓦时。
- 原煤月产量原单位为百万吨。煤及褐煤进口从千吨除以1000转换为百万吨，不填补缺失月份。
- 本次数据的文件名日期是2026-11-13，数据库目录日期是2026-11-15，周报日期是2026-11-13。它们在数据中分别保存，网页清楚区分。

原始 Excel 留在本机，`.gitignore` 排除了 Excel 文件。发布在公开网页上的 `data.js` 可以被访问者读取。

## 文件职责

| 文件 | 用途 |
|---|---|
| `index.html` | 页面结构 |
| `styles.css` | 桌面、手机和打印样式 |
| `app.js` | 图表、表格、交互和缺失值格式化 |
| `data.js` | 从 Excel 导出的网页数据 |
| `extract_dashboard_data.py` | Excel 提取与布局校验 |
| `requirements.txt` | Python 依赖 |
| `更新数据.command` | Mac 本地更新入口 |
| `update_data.ps1` | Windows PowerShell 本地更新入口 |
| `.nojekyll` | 让 GitHub Pages 直接提供静态文件 |

布局调整时，在 Python 脚本开头的源配置中修改表名、日期列、值列和表头校验。指标值及来源不会通过网页写回 Excel。
