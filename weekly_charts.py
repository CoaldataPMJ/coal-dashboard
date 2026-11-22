from __future__ import annotations

import calendar
from datetime import date, timedelta
import math
from pathlib import PurePosixPath
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl.utils.cell import range_boundaries


NAMESPACES = {
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "x": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
}
CHART_LAYOUT = (
    ("price", "港口5500动力煤价格", "元/吨", "日度", True),
    ("international", "国际动力煤价格", "美元/吨", "日度", False),
    ("plant-use", "二十五省动力煤日耗", "万吨", "日度", True),
    ("plant-stock", "二十五省动力煤库存", "万吨", "日度", True),
    ("coking-price", "炼焦煤价格", "元/吨", "日度", False),
    ("hot-metal", "日均铁水产量", "万吨/日", "月度均值", True),
)
COLORS = ("#eb6673", "#97ccdf", "#009cca", "#193d6c", "#d92828", "#e6ac00")


def relations(archive, part):
    path = PurePosixPath(part)
    target = str(path.parent / "_rels" / (path.name + ".rels"))
    if target not in archive.namelist():
        return {}
    result = {}
    for entry in ET.fromstring(archive.read(target)):
        if entry.attrib.get("TargetMode") == "External":
            continue
        result[entry.attrib["Id"]] = posixpath.normpath(
            posixpath.join(posixpath.dirname(part), entry.attrib["Target"])
        ).lstrip("/") if not entry.attrib["Target"].startswith("/") else entry.attrib["Target"].lstrip("/")
    return result


def parse_reference(formula):
    match = re.fullmatch(r"(?:'((?:[^']|'')+)'|([^!]+))!(\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?)", formula or "")
    if not match:
        raise ValueError(f"不支持的周报图表区域引用：{formula!r}")
    sheet = (match.group(1) or match.group(2)).replace("''", "'")
    first_col, first_row, last_col, last_row = range_boundaries(match.group(3))
    return {"sheet": sheet, "range": match.group(3), "firstColumn": first_col,
            "lastColumn": last_col, "firstRow": first_row, "lastRow": last_row, "formula": formula}


def read_chart_definitions(source):
    charts = []
    with ZipFile(source) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next(item for item in workbook.find("s:sheets", NAMESPACES)
                     if item.attrib["name"] == "周报输出")
        sheet_part = relations(archive, "xl/workbook.xml")[sheet.attrib[f"{{{NAMESPACES['r']}}}id"]]
        for drawing_part in relations(archive, sheet_part).values():
            if "/drawings/" not in drawing_part or not drawing_part.endswith(".xml"):
                continue
            drawing_rels = relations(archive, drawing_part)
            for anchor in ET.fromstring(archive.read(drawing_part)):
                chart_ref = anchor.find(".//c:chart", NAMESPACES)
                if chart_ref is None:
                    continue
                chart_part = drawing_rels[chart_ref.attrib[f"{{{NAMESPACES['r']}}}id"]]
                series = []
                for entry in ET.fromstring(archive.read(chart_part)).findall(".//c:ser", NAMESPACES):
                    references = {}
                    for name, selector in (("name", "c:tx//c:f"), ("categories", "c:cat//c:f"), ("values", "c:val//c:f")):
                        text = entry.find(selector, NAMESPACES)
                        if text is not None:
                            references[name] = parse_reference(text.text)
                    if "name" not in references or "values" not in references:
                        raise ValueError(f"{chart_part} 缺少序列名称或数值引用。")
                    series.append(references)
                origin = anchor.find("x:from", NAMESPACES)
                charts.append({"part": chart_part, "row": int(origin.find("x:row", NAMESPACES).text),
                               "column": int(origin.find("x:col", NAMESPACES).text), "series": series})
    charts.sort(key=lambda item: (item["row"], item["column"]))
    if len(charts) != len(CHART_LAYOUT):
        raise ValueError(f"周报输出含 {len(charts)} 张图，与当前六图模板不一致，请核对图表配置。")
    for chart, (chart_id, title, unit, frequency, seasonal) in zip(charts, CHART_LAYOUT):
        chart.update({"id": chart_id, "title": title, "unit": unit, "frequency": frequency, "seasonal": seasonal})
    return charts


def chart_requirements(definitions):
    required = {}
    for chart in definitions:
        for series in chart["series"]:
            for ref in series.values():
                required[ref["sheet"]] = max(required.get(ref["sheet"], 0), ref["lastColumn"])
    return required


def read_range(sheets, ref):
    rows = sheets[ref["sheet"]].rows
    return [row[ref["firstColumn"] - 1:ref["lastColumn"]] for row in rows[ref["firstRow"] - 1:ref["lastRow"]]]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def extract_weekly_charts(sheets, definitions, parse_date, epoch, end_date, years):
    charts, reports, warnings = [], [], []
    for definition in definitions:
        chart_series, series_reports = [], []
        source_caption = f"周报输出!{'B' if definition['column'] < 4 else 'F'}{definition['row']}"
        actual_caption = sheets["周报输出"].cell(source_caption.split("!")[1])
        if actual_caption != definition["title"]:
            raise ValueError(f"{source_caption} 图名应为 {definition['title']!r}，实际为 {actual_caption!r}。")
        default_categories = next((item["categories"] for item in definition["series"] if "categories" in item), None)
        for index, item in enumerate(definition["series"]):
            name_value = read_range(sheets, item["name"])[0][0]
            name = str(int(name_value)) if finite(name_value) else str(name_value or "").strip()
            if not name:
                raise ValueError(f"周报图表 {definition['title']} 的序列名为空。")
            year = int(name) if definition["seasonal"] and name.isdigit() else None
            if definition["seasonal"] and (year is None or not 1900 < year < 2200):
                raise ValueError(f"周报年度图 {definition['title']} 的年份标签不可识别：{name!r}")
            categories_ref = item.get("categories", default_categories)
            if categories_ref is None:
                raise ValueError(f"{definition['title']} 缺少横轴引用。")
            categories = read_range(sheets, categories_ref)
            values = read_range(sheets, item["values"])
            if len(values) != len(categories) or any(len(row) != 1 for row in values):
                raise ValueError(f"{definition['title']} 的日期与数值引用长度不一致。")
            points, invalid, future = [], 0, 0
            for point_index, (category, values_row) in enumerate(zip(categories, values)):
                raw_date = category[0]
                if raw_date is None and values_row[0] is None:
                    continue
                if year is not None and definition["frequency"] == "月度均值":
                    if not finite(raw_date) or not 1 <= raw_date <= 12:
                        raise ValueError(f"铁水月度图的月份不合法：{raw_date!r}")
                    month, day = int(raw_date), 1
                elif year is not None:
                    parsed = parse_date(raw_date, epoch)
                    if parsed is None:
                        raise ValueError(f"周报年度图的日期不合法：{raw_date!r}")
                    month, day = parsed.month, parsed.day
                    if len(categories) == 366 and parsed.year == 1900:
                        template_day = date(2000, 1, 1) + timedelta(days=point_index)
                        month, day = template_day.month, template_day.day
                else:
                    actual_date = parse_date(raw_date, epoch)
                    if actual_date is None:
                        raise ValueError(f"周报连续图的日期不合法：{raw_date!r}")
                if year is not None:
                    if day > calendar.monthrange(year, month)[1]:
                        continue
                    actual_date = date(year, month, day)
                    display_date = date(2000, month, day)
                else:
                    display_date = actual_date
                value = values_row[0] if finite(values_row[0]) else None
                if actual_date > end_date:
                    value = None
                    future += 1
                if value is None:
                    invalid += 1
                if not definition["seasonal"] and actual_date < date(end_date.year - years, end_date.month,
                                                                     min(end_date.day, calendar.monthrange(end_date.year - years, end_date.month)[1])):
                    continue
                point = {"date": display_date.isoformat(), "value": round(value, 6) if value is not None else None,
                         "sourceDate": actual_date.isoformat()}
                points.append(point)
            valid = [point for point in points if point["value"] is not None]
            if not valid:
                raise ValueError(f"周报图表「{definition['title']}」的 {name} 没有有效数据，请检查公式缓存。")
            chart_series.append({"name": name, "color": COLORS[index % len(COLORS)], "data": points,
                                 "dateRange": {"first": valid[0]["sourceDate"], "last": valid[-1]["sourceDate"]}})
            series_reports.append({"name": name, "references": item, "categories": categories_ref,
                                   "pointCount": len(points), "validPointCount": len(valid), "missingPointCount": invalid,
                                   "futureMasked": future, "lastDate": valid[-1]["sourceDate"]})
        caption = "按周报原图引用范围，月份对齐各年" if definition["seasonal"] else "按周报原图序列与日期范围"
        if definition["id"] == "hot-metal":
            caption = "周报原图为月度均值，已保存数据截至各年对应月份"
        charts.append({key: definition[key] for key in ("id", "title", "unit", "frequency", "seasonal")} |
                      {"subtitle": caption, "series": chart_series, "source": source_caption,
                       "sourceChart": definition["part"]})
        reports.append({"id": definition["id"], "source": source_caption, "series": series_reports})
    return charts, reports, warnings
