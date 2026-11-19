#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 China Coal Database-20261113.xlsx 的布局导出煤炭看板数据。

Python 3.9+，依赖 openpyxl。只读 Excel，不计算公式、不修改工作簿。
输出继续使用 window.COAL_DATA，兼容原脚本的五组图表和主要字段。
用法：python3 extract_dashboard_data.py --source "数据库.xlsx"
"""

from __future__ import annotations

import argparse
import calendar
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string
from openpyxl.utils.datetime import CALENDAR_WINDOWS_1900, from_excel
from openpyxl.utils.exceptions import InvalidFileException
from thermal_data import extract_thermal, thermal_specs


ROOT = Path(__file__).resolve().parent
PRICE_SHEET = "Raw data-价格_指数"
INVENTORY_SHEET = "Raw data-港口库存"
TRANSPORT_SHEET = "Raw data-北方三港"
POWER_SHEET = "Raw data-旬度发电量"
MONTHLY_SHEET = "Raw data-月度数据"

# 周报按 B 列的文字分区，插入指标行时不必修改行号。
WEEKLY_SECTIONS = {"价格", "产量", "库存", "电力", "钢铁和化工"}
WEEKLY_STOP_TITLES = {"周涨跌幅", "港口5500动力煤价格"}
POINT_CHANGE_METRICS = {"欧洲天然气储气率", "247家钢铁高炉开工率"}
SUMMARY_METRICS = ("CCI5500", "CCTD主流港口库存", "沿海八省日耗", "内陆十七省库存")


@dataclass(frozen=True)
class SourceSpec:
    """一段时序数据的布局。列字母、起始行、表头校验都集中在这里。"""

    sheet: str
    date_column: str
    value_columns: tuple[str, ...]
    start_row: int
    headers: tuple[tuple[str, str], ...]
    scale: float = 1.0
    positive_only: bool = False
    label: str = ""


def price_source(date_column, value_column, start_row, header, label, current=False):
    checks = [(f"{value_column}{2 if current else 3}", header)]
    if current:
        # 新区块同一指标有人民币、美元和指数环比多列，必须同时核对值项与单位。
        checks += [(f"{value_column}6", "人民币"), (f"{value_column}7", "元/吨")]
        checks += [(f"{date_column}2", "指标名称")]
    return SourceSpec(PRICE_SHEET, date_column, (value_column,), start_row,
                      tuple(checks), positive_only=True, label=label)


# 多段价格按先旧后新的顺序配置。新区块覆盖区间内的缺值保持缺失，
# 旧区块仅补充新区块开始之前的历史，不拿旧报价填充新区块中的缺口。
PRICE_SOURCES = {
    "CCI5500": (
        price_source("A", "B", 6, "动力煤价格指数(RMB):CCI5500(含税)", "Wind历史"),
        price_source("CW", "CX", 8, "CCI5500", "FW2707R当前数据", True),
    ),
    "鄂尔多斯 5500": (
        price_source("AF", "AG", 4, "内蒙古鄂尔多斯5500", "汾渭旧数据"),
        price_source("CW", "DV", 8, "内蒙古鄂尔多斯5500", "FW2707R当前数据", True),
    ),
    "大同 5500": (
        price_source("AK", "AM", 4, "山西大同5500", "汾渭旧数据"),
        price_source("CW", "DX", 8, "山西大同5500", "FW2707R当前数据", True),
    ),
}


def inventory_source(columns, names):
    return SourceSpec(
        INVENTORY_SHEET, "A", columns, 5,
        tuple((f"{column}2", name) for column, name in zip(columns, names))
        + tuple((f"{column}4", "万吨") for column in columns),
        label="FW1203D北方港口库存",
    )


INVENTORY_SOURCES = {
    "港口合计": (inventory_source(("B",), ("合计",)),),
    "秦皇岛港": (inventory_source(("C",), ("秦皇岛港",)),),
    # 原脚本只加 G:J，遗漏 K 列华电曹妃甸港。本版将五个码头全部纳入。
    "曹妃甸港群": (inventory_source(
        ("G", "H", "I", "J", "K"),
        ("国投曹妃甸港", "国储曹妃甸港", "曹妃甸港二期", "华能曹妃甸港", "华电曹妃甸港"),
    ),),
}


def transport_source(columns, suffix):
    ports = ("秦皇岛港", "曹妃甸港", "黄骅港")
    return SourceSpec(
        TRANSPORT_SHEET, "A", columns, 5,
        tuple((f"{column}3", f"煤炭调度:{port}:{suffix}") for column, port in zip(columns, ports))
        + tuple((f"{column}4", "万吨") for column in columns),
        label="北方三港逐港加总",
    )


TRANSPORT_SOURCES = {
    "铁路调入量": (transport_source(("B", "E", "H"), "铁路调入量"),),
    "港口吞吐量": (transport_source(("C", "F", "I"), "港口吞吐量"),),
}
POWER_SOURCES = {
    name: (SourceSpec(POWER_SHEET, "M", (column,), 8,
                      ((f"{column}7", name), ("M7", "date"), ("A7", "单位：亿千瓦时")),
                      positive_only=True, label="CCTD旬度日均发电量"),)
    for name, column in (("总发电量", "C"), ("火电", "E"), ("水电", "G"))
}
SUPPLY_SOURCES = {
    "原煤产量": (SourceSpec(MONTHLY_SHEET, "BG", ("BH",), 7,
        (("BH3", "产量:原煤:当月值"), ("BH5", "百万吨")),
        positive_only=True, label="国家统计局月度原煤产量"),),
    "煤及褐煤进口": (SourceSpec(MONTHLY_SHEET, "BR", ("BS",), 6,
        (("BS3", "进口数量:煤及褐煤:当月值"), ("BS5", "千吨")),
        scale=0.001, positive_only=True, label="月度进口：千吨转百万吨"),),
}

# 五个图表 ID 沿用旧版，附加的 source/dateRange 等字段可由页面按需使用。
CHARTS = (
    ("price", "动力煤价格走势", "港口与坑口含税价格", "元/吨", "日度", 14, PRICE_SOURCES),
    ("inventory", "北方港口煤炭库存", "FW1203D口径，曹妃甸港群含五个码头", "万吨", "日度", 14, INVENTORY_SOURCES),
    ("transport", "北方三港调入与吞吐", "秦皇岛、曹妃甸、黄骅港合计", "万吨", "日度", 14, TRANSPORT_SOURCES),
    ("power", "旬度日均发电量", "总发电、火电与水电；日期沿用原表旬度标记", "亿千瓦时", "旬度", 45, POWER_SOURCES),
    ("supply", "煤炭供给", "全国原煤产量与煤及褐煤进口", "百万吨", "月度", 75, SUPPLY_SOURCES),
)
COLORS = ("#ef7d32", "#2a7f9e", "#5a9f68")


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean_number(value, digits=6):
    return round(float(value), digits) if is_number(value) else None


def as_date(value, epoch=CALENDAR_WINDOWS_1900):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                pass
    # 仅在配置指定的日期列解析 Excel 日期序列，避免把年份当作日期。
    if is_number(value) and 20000 <= value <= 80000:
        return from_excel(value, epoch=epoch).date()
    return None


def normalize(value):
    return re.sub(r"\s+", "", str(value or ""))


@dataclass
class SheetData:
    name: str
    rows: list[tuple]
    formats: dict[str, str]

    def cell(self, address):
        column, row = coordinate_from_string(address)
        col = column_index_from_string(column) - 1
        return self.rows[row - 1][col] if row <= len(self.rows) and col < len(self.rows[row - 1]) else None


def filename_date(path):
    match = re.fullmatch(r"China Coal Database-(\d{8})\.xlsx", path.name, re.IGNORECASE)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            pass
    return None


def discover_source(source=None, search_dirs=None):
    if source is not None:
        candidate = Path(source).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"找不到数据库：{candidate}")
        return candidate
    search_dirs = search_dirs if search_dirs is not None else (ROOT, Path.cwd())
    candidates = []
    for folder in dict.fromkeys(Path(p).resolve() for p in search_dirs):
        if not folder.is_dir():
            continue
        for candidate in folder.glob("*.xlsx"):
            stamp = filename_date(candidate)
            if candidate.is_file() and (stamp or candidate.name.lower() == "china coal database.xlsx"):
                candidates.append((stamp or date.min, candidate))
    if not candidates:
        raise FileNotFoundError("未在脚本目录或当前目录找到 China Coal Database*.xlsx。请用 --source 指定文件路径。")
    # 按文件名中的有效日期选择，不以文件修改时间冒充数据库版本日期。
    return max(candidates, key=lambda item: item[0])[1]


def source_specs():
    for *_, mapping in CHARTS:
        for specs in mapping.values():
            yield from specs
    yield from thermal_specs()


def load_sources(source):
    required = {"Table of Contents": 2, "周报输出": 10}
    for spec in source_specs():
        columns = [spec.date_column, *spec.value_columns]
        columns += [coordinate_from_string(address)[0] for address, _ in spec.headers]
        required[spec.sheet] = max(required.get(spec.sheet, 0), *(column_index_from_string(c) for c in columns))
    book = load_workbook(source, read_only=True, data_only=True, keep_links=False)
    try:
        missing = sorted(set(required) - set(book.sheetnames))
        if missing:
            raise ValueError("缺少工作表：" + "、".join(missing))
        sheets = {}
        for name, max_column in required.items():
            sheet = book[name]
            rows, formats = [], {}
            for row in sheet.iter_rows(max_col=max_column):
                rows.append(tuple(cell.value for cell in row))
                if name == "周报输出":
                    for cell in row:
                        if cell.value is not None:
                            formats[cell.coordinate] = cell.number_format
            sheets[name] = SheetData(name, rows, formats)
        return sheets, book.epoch, len(book.sheetnames)
    finally:
        book.close()


def validate_layout(sheets):
    failures = []
    for spec in source_specs():
        sheet = sheets[spec.sheet]
        for address, expected in spec.headers:
            actual = sheet.cell(address)
            if normalize(actual) != normalize(expected):
                failures.append(f"{spec.sheet}!{address} 应为 {expected!r}，实际为 {actual!r}")
    for address, expected in (("G5", "周环比"), ("I5", "同比"), ("J5", "备注")):
        actual = sheets["周报输出"].cell(address)
        if normalize(actual) != normalize(expected):
            failures.append(f"周报输出!{address} 应为 {expected!r}，实际为 {actual!r}")
    if failures:
        raise ValueError("Excel布局与配置不符，请核对列配置：\n" + "\n".join(dict.fromkeys(failures)))


def read_weekly(sheet, epoch, issues):
    metrics = []
    section = group = ""
    for row_number, row in enumerate(sheet.rows[5:], 6):
        heading, metric, unit = row[1:4]
        if heading and not metric:
            heading = str(heading).strip()
            if heading in WEEKLY_STOP_TITLES:
                break
            if heading in WEEKLY_SECTIONS:
                section, group = heading, ""
            else:
                group = heading
            continue
        if not metric or unit is None:
            continue
        if not section:
            raise ValueError(f"周报输出第 {row_number} 行之前没有识别到分区标题。")
        current, previous, wow, year_ago, yoy, note = row[4:10]
        source_errors = {}
        for name, value in zip(("current", "previous", "wow", "yearAgo", "yoy"), row[4:9]):
            if not is_number(value):
                source_errors[name] = str(value) if value is not None else "空值或公式未缓存"
        item = {
            "section": section, "group": group, "metric": str(metric), "unit": str(unit),
            "current": clean_number(current), "previous": clean_number(previous),
            "wow": clean_number(wow, 8), "yearAgo": clean_number(year_ago), "yoy": clean_number(yoy, 8),
            "note": str(note or ""), "sourceRow": row_number,
            "source": f"周报输出!C{row_number}:J{row_number}",
            "status": "ok" if is_number(current) else "unavailable",
            "valueIsFraction": "%" in sheet.formats.get(f"E{row_number}", ""),
            "changeType": "percentagePoints" if metric in POINT_CHANGE_METRICS else "relative",
            "sourceErrors": source_errors,
        }
        metrics.append(item)
        if source_errors:
            issues.append({"code": "weekly_missing_value", "metric": str(metric),
                           "message": f"周报输出第{row_number}行存在缺失或错误值，已保留为null。", "fields": source_errors})
    if not metrics:
        raise ValueError("周报输出没有可识别的指标，请检查 C:J 列布局及公式缓存。")
    dates = {name: as_date(sheet.cell(address), epoch) for name, address in
             (("weeklyDate", "E5"), ("previousWeeklyDate", "F5"), ("yearAgoDate", "H5"))}
    if not all(dates.values()):
        raise ValueError("周报输出!E5、F5、H5 必须为有效日期。请检查 Excel 并重新计算、保存。")
    return metrics, dates


def read_points(sheet, spec, end_date, epoch):
    """同日重复记录按工作表最后一行取值，并在报告中列出重复次数。"""
    di = column_index_from_string(spec.date_column) - 1
    indices = [column_index_from_string(column) - 1 for column in spec.value_columns]
    by_date = {}
    stats = {"sheet": spec.sheet, "dateColumn": spec.date_column,
             "valueColumns": list(spec.value_columns), "startRow": spec.start_row,
             "scale": spec.scale, "label": spec.label,
             "duplicateDates": 0, "missingRows": 0, "rowsAfterCutoff": 0}
    for row_number, row in enumerate(sheet.rows[spec.start_row - 1:], spec.start_row):
        day = as_date(row[di], epoch)
        if day is None:
            continue
        if day > end_date:
            stats["rowsAfterCutoff"] += 1
            continue
        values = [row[index] for index in indices]
        valid = all(is_number(value) for value in values)
        value = sum(values) * spec.scale if valid else None
        # 库存与运输允许真实零值。价格等使用零作为缺失占位时不生成零报价。
        if value is not None and spec.positive_only and value <= 0:
            value = None
        if value is None:
            stats["missingRows"] += 1
        key = day.isoformat()
        if key in by_date:
            stats["duplicateDates"] += 1
        by_date[key] = {"date": key, "value": clean_number(value), "_row": row_number}
    valid_dates = sorted(key for key, point in by_date.items() if point["value"] is not None)
    stats["validPoints"] = len(valid_dates)
    stats["firstDate"] = valid_dates[0] if valid_dates else None
    stats["lastDate"] = valid_dates[-1] if valid_dates else None
    # 不把源数据开始前或结束后的整段空白画成历史数据。
    if not valid_dates:
        return [], stats
    last_row = by_date[valid_dates[-1]]["_row"]
    stats["latestSourceRow"] = last_row
    stats["latestInputs"] = {
        column: sheet.rows[last_row - 1][index]
        for column, index in zip(spec.value_columns, indices)
    }
    points = [by_date[key] for key in sorted(by_date) if valid_dates[0] <= key <= valid_dates[-1]]
    return points, stats


def years_before(day, years):
    year = day.year - years
    return day.replace(year=year, day=min(day.day, calendar.monthrange(year, day.month)[1]))


def build_series(name, specs, sheets, epoch, end_date, years, lag_days, color, issues):
    merged, reports = {}, []
    for spec in specs:
        points, report = read_points(sheets[spec.sheet], spec, end_date, epoch)
        reports.append(report)
        if not points:
            raise ValueError(f"{name} 的 {spec.label} 没有有效数据。请检查公式缓存和源列 {spec.value_columns}。")
        start = points[0]["date"]
        merged = {key: point for key, point in merged.items() if key < start}
        merged.update({point["date"]: {**point, "_source": len(reports) - 1} for point in points})
    cutoff = years_before(end_date, years).isoformat()
    selected = [merged[key] for key in sorted(merged) if key >= cutoff]
    valid = [point for point in selected if point["value"] is not None]
    if not valid:
        raise ValueError(f"{name} 在最近 {years} 年内没有有效数据。")
    segments = []
    for index, report in enumerate(reports):
        used = [p for p in selected if p["_source"] == index and p["value"] is not None]
        if used:
            segments.append({"label": report["label"], "sheet": report["sheet"],
                             "dateColumn": report["dateColumn"], "valueColumns": report["valueColumns"],
                             "scale": report["scale"], "firstDate": used[0]["date"],
                             "lastDate": used[-1]["date"], "pointCount": len(used)})
    last_date = date.fromisoformat(valid[-1]["date"])
    if (end_date - last_date).days > lag_days:
        issues.append({"code": "stale_series", "series": name,
                       "message": f"{name} 的源数据最后有效日期为 {last_date}，距数据库日期超过 {lag_days} 天；未外推或补齐。"})
    for report in reports:
        if report["duplicateDates"]:
            issues.append({"code": "duplicate_dates", "series": name,
                           "message": f"{report['label']} 有 {report['duplicateDates']} 条同日重复记录，取工作表最后一行。"})
        inputs = report.get("latestInputs", {})
        zeros = [column for column, value in inputs.items() if value == 0]
        if len(inputs) > 1 and zeros and any(value != 0 for value in inputs.values()):
            issues.append({"code": "aggregate_zero_components", "series": name,
                           "date": report["lastDate"], "zeroColumns": zeros,
                           "message": f"{name} 最新合计中 {','.join(zeros)} 列为0，已按原表加总；请核对分项的0是否表示尚未更新。"})
    result = {"name": name, "color": color,
              "data": [{"date": point["date"], "value": point["value"]} for point in selected],
              "dateRange": {"first": valid[0]["date"], "last": valid[-1]["date"]},
              "missingPointCount": len(selected) - len(valid), "sources": segments}
    return result, {"name": name, "pointCount": len(selected), "validPointCount": len(valid),
                    "dateRange": result["dateRange"], "missingPointCount": result["missingPointCount"], "sources": reports}


def extract_dashboard(source, years=6, supply_years=8):
    if not 1 <= years <= 100 or not 1 <= supply_years <= 100:
        raise ValueError("历史年数需为 1 到 100 之间的整数。")
    sheets, epoch, sheet_count = load_sources(source)
    validate_layout(sheets)
    issues = []
    metrics, weekly_dates = read_weekly(sheets["周报输出"], epoch, issues)
    update_date = as_date(sheets["Table of Contents"].cell("B7"), epoch)
    date_source = "Table of Contents!B7"
    if update_date is None:
        update_date = weekly_dates["weeklyDate"]
        date_source = "周报输出!E5（目录日期不可用）"
        issues.append({"code": "database_date_fallback", "message": "目录B7日期不可用，图表截止日期采用周报E5，未采用文件修改时间。"})
    if weekly_dates["weeklyDate"] > update_date:
        raise ValueError("周报日期晚于目录数据库日期，请先核对 Table of Contents!B7 与 周报输出!E5。")
    version_date = filename_date(source)
    if version_date and version_date != update_date:
        issues.append({"code": "filename_date_differs", "message": f"文件名日期为 {version_date}，目录数据库日期为 {update_date}，分别保留；图表以目录日期为截止。"})
    by_name = {item["metric"]: item for item in metrics}
    missing_cards = [name for name in SUMMARY_METRICS if name not in by_name]
    if missing_cards:
        raise ValueError("周报缺少顶部卡片指标：" + "、".join(missing_cards))
    charts, chart_reports = [], []
    for chart_id, title, subtitle, unit, frequency, lag_days, mapping in CHARTS:
        series, series_reports = [], []
        for index, (name, specs) in enumerate(mapping.items()):
            item, report = build_series(name, specs, sheets, epoch, update_date,
                supply_years if chart_id == "supply" else years, lag_days,
                COLORS[index % len(COLORS)], issues)
            series.append(item)
            series_reports.append(report)
        charts.append({"id": chart_id, "title": title, "subtitle": subtitle, "unit": unit,
                       "frequency": frequency, "series": series})
        chart_reports.append({"id": chart_id, "series": series_reports})
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="minutes")
    thermal_coal, thermal_report = extract_thermal(sheets, epoch, as_date, column_index_from_string)
    data = {
        "meta": {"title": "中国煤炭高频数据看板", "source": source.name,
                 "databaseDate": update_date.isoformat(),
                 **{name: value.isoformat() for name, value in weekly_dates.items()},
                 "generatedAt": generated_at, "timezone": "Asia/Shanghai", "sheetCount": sheet_count,
                 "sourceFileDate": version_date.isoformat() if version_date else None,
                 "databaseDateSource": date_source, "schemaVersion": "2.1", "historyYears": years,
                 "supplyHistoryYears": supply_years,
                 "formulaPolicy": "使用Excel已保存的计算结果；不重新计算公式"},
        "summaryCards": [by_name[name] for name in SUMMARY_METRICS],
        "weeklyMetrics": metrics, "charts": charts, "warnings": issues, "thermalCoal": thermal_coal,
    }
    report = {"source": str(source), "meta": data["meta"], "summaryCards": len(data["summaryCards"]),
              "weeklyMetrics": len(metrics), "availableWeeklyMetrics": sum(m["status"] == "ok" for m in metrics),
              "weeklySections": list(dict.fromkeys(m["section"] for m in metrics)),
              "charts": chart_reports, "warnings": issues, "thermalCoal": thermal_report}
    return data, report


def write_outputs(data, report, output_dir):
    output_dir = Path(output_dir).expanduser().resolve()
    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    texts = {
        "data.json": compact + "\n",
        "extraction_report.json": json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        "data.js": "window.COAL_DATA = " + compact + ";\n",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_dir) as staging:
        for name, text in texts.items():
            (Path(staging) / name).write_text(text, encoding="utf-8")
        for name in texts:
            (Path(staging) / name).replace(output_dir / name)
    return output_dir / "data.js"


def main(argv=None):
    parser = argparse.ArgumentParser(description="按煤炭Excel实际布局生成网页看板数据。")
    parser.add_argument("--source", type=Path, help="Excel路径；省略时在脚本/当前目录选文件名日期最新的数据库。")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dashboard", help="输出目录，默认脚本旁的dashboard。")
    parser.add_argument("--years", type=int, default=6, help="价格/库存/运输/发电保留的历史年数，默认6。")
    parser.add_argument("--supply-years", type=int, default=8, help="供给图历史年数，默认8。")
    args = parser.parse_args(argv)
    try:
        source = discover_source(args.source)
        data, report = extract_dashboard(source, args.years, args.supply_years)
        output = write_outputs(data, report, args.output_dir)
    except (OSError, ValueError, KeyError, BadZipFile, InvalidFileException) as error:
        print(f"提取失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps({"source": str(source), "output": str(output),
        "databaseDate": data["meta"]["databaseDate"], "weeklyDate": data["meta"]["weeklyDate"],
        "summaryCards": report["summaryCards"], "weeklyMetrics": report["weeklyMetrics"],
        "availableWeeklyMetrics": report["availableWeeklyMetrics"],
        "thermalGroups": len(data["thermalCoal"]["groups"]), "thermalSeries": len(data["thermalCoal"]["series"]),
        "charts": {chart["id"]: {series["name"]: len(series["data"]) for series in chart["series"]} for chart in data["charts"]},
        "warnings": report["warnings"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
