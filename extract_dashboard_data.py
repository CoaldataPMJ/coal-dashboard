#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从煤炭数据库的周报图表和煤种底表导出看板数据。

Python 3.9+，依赖 openpyxl。只读 Excel，不计算公式、不修改工作簿。
输出使用 window.COAL_DATA，总览图表按“周报输出”的图项和单元格引用更新。
用法：python3 extract_dashboard_data.py --source "数据库.xlsx"
"""

from __future__ import annotations

import argparse
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
from coking_data import COKING_GROUPS, extract_coking
from thermal_data import THERMAL_GROUPS, detail_specs, extract_thermal
from weekly_charts import chart_requirements, extract_weekly_charts, read_chart_definitions
from overseas_data import OVERSEAS_GROUPS, extract_overseas
from supply_data import SUPPLY_GROUPS, extract_supply


ROOT = Path(__file__).resolve().parent
WEEKLY_SECTIONS = {"价格", "产量", "库存", "电力", "钢铁和化工"}
WEEKLY_STOP_TITLES = {"周涨跌幅", "港口5500动力煤价格"}
POINT_CHANGE_METRICS = {"欧洲天然气储气率", "247家钢铁高炉开工率"}
SUMMARY_METRICS = ("CCI5500", "CCTD主流港口库存", "沿海八省日耗", "内陆十七省库存")

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
    yield from detail_specs(THERMAL_GROUPS)
    yield from detail_specs(COKING_GROUPS)
    yield from detail_specs(OVERSEAS_GROUPS)
    yield from detail_specs(SUPPLY_GROUPS)


def load_sources(source, chart_definitions):
    required = {"Table of Contents": 2, "周报输出": 10, **chart_requirements(chart_definitions)}
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
            "wowLabel": "旬环比" if "旬度" in str(metric) or "旬度环比" in str(note) else
                        "月环比" if "月度环比" in str(note) else "周环比",
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


def extract_dashboard(source, years=6, supply_years=8):
    if not 1 <= years <= 100 or not 1 <= supply_years <= 100:
        raise ValueError("历史年数需为 1 到 100 之间的整数。")
    chart_definitions = read_chart_definitions(source)
    sheets, epoch, sheet_count = load_sources(source, chart_definitions)
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
        issues.append({"code": "filename_date_differs", "message": f"文件名日期为 {version_date}，目录数据库日期为 {update_date}；总览图表按周报日期截止，煤种明细保留实际观测期。"})
    by_name = {item["metric"]: item for item in metrics}
    missing_cards = [name for name in SUMMARY_METRICS if name not in by_name]
    if missing_cards:
        raise ValueError("周报缺少顶部卡片指标：" + "、".join(missing_cards))
    charts, chart_reports, chart_warnings = extract_weekly_charts(
        sheets, chart_definitions, as_date, epoch, weekly_dates["weeklyDate"], years)
    issues.extend(chart_warnings)
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="minutes")
    thermal_coal, thermal_report = extract_thermal(sheets, epoch, as_date, column_index_from_string)
    coking_coal, coking_report = extract_coking(sheets, epoch, as_date, column_index_from_string)
    overseas, overseas_report = extract_overseas(sheets, epoch, as_date, column_index_from_string)
    supply, supply_report = extract_supply(sheets, epoch, as_date, column_index_from_string)
    data = {
        "meta": {"title": "中国煤炭高频数据看板", "source": source.name,
                 "databaseDate": update_date.isoformat(),
                 **{name: value.isoformat() for name, value in weekly_dates.items()},
                 "generatedAt": generated_at, "timezone": "Asia/Shanghai", "sheetCount": sheet_count,
                 "sourceFileDate": version_date.isoformat() if version_date else None,
                 "databaseDateSource": date_source, "schemaVersion": "3.0", "historyYears": years,
                 "supplyHistoryYears": supply_years,
                 "formulaPolicy": "使用Excel已保存的计算结果；不重新计算公式"},
        "summaryCards": [by_name[name] for name in SUMMARY_METRICS],
        "weeklyMetrics": metrics, "charts": charts, "warnings": issues,
        "thermalCoal": thermal_coal, "cokingCoal": coking_coal, "overseasEnergy": overseas, "supply": supply,
    }
    report = {"source": str(source), "meta": data["meta"], "summaryCards": len(data["summaryCards"]),
              "weeklyMetrics": len(metrics), "availableWeeklyMetrics": sum(m["status"] == "ok" for m in metrics),
              "weeklySections": list(dict.fromkeys(m["section"] for m in metrics)),
              "charts": chart_reports, "warnings": issues, "thermalCoal": thermal_report, "cokingCoal": coking_report,
              "overseasEnergy": overseas_report, "supply": supply_report}
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
        "cokingGroups": len(data["cokingCoal"]["groups"]), "cokingSeries": len(data["cokingCoal"]["series"]),
        "overseasGroups": len(data["overseasEnergy"]["groups"]), "overseasSeries": len(data["overseasEnergy"]["series"]),
        "supplyGroups": len(data["supply"]["groups"]), "supplySeries": len(data["supply"]["series"]),
        "charts": {chart["id"]: {series["name"]: len(series["data"]) for series in chart["series"]} for chart in data["charts"]},
        "warnings": report["warnings"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
