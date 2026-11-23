from __future__ import annotations

import calendar
import math
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta


PRICE = "Raw data-价格_指数"
STOCK = "Raw data-产量_库存_开工率_其他"
TRANSPORT = "Raw data-北方三港"
POWER = "动力煤-下游"
TEN_DAY = "动力煤-下游旬度"
INDUSTRY_USE = "动力煤-分行业煤耗"
IMPORTS = "产量及进口"
COMBINED_POWER_COLUMNS = dict(zip("BCDEJKLM", "NOPQRSTU"))


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    unit: str
    frequency: str
    sheet: str
    date_column: str
    columns: tuple[str, ...]
    start_row: int
    headers: tuple[tuple[str, str], ...]
    demand_ids: tuple[int, ...] = ()
    scale: float = 1
    rule: str = "value"
    cadence: str = ""
    reported: tuple[str, str] = ("", "")
    end_marker: str = ""
    reported_scales: tuple[float, float] = (1, 1)
    reported_only: bool = False

    @property
    def value_columns(self):
        return self.columns + tuple(col for col in self.reported if col)


def metric(series_id, name, unit, frequency, sheet, date_column, columns, start, headers, **settings):
    return Metric(series_id, name, unit, frequency, sheet, date_column,
                  tuple(columns.split()), start, tuple(headers), **settings)


def panel(panel_id, label, metrics, note=""):
    return panel_id, label, tuple(metrics), note


def price(series_id, name, column, unit="元/吨", date_col="BV", start=9,
          header=None, demand_id=None, price_type=None):
    checks = [(f"{column}{2 if date_col == 'BV' else 3}", header or name)]
    if date_col == "BV":
        checks += [("BV2", "指标名称"), (f"{column}6", "人民币" if unit == "元/吨" else "美元"),
                   (f"{column}7", unit)]
        if price_type:
            checks.append((f"{column}4", price_type))
    elif date_col not in {"A", "AF", "AK"}:
        checks.append((f"{column}5", unit))
    return metric(series_id, name, unit, "daily", PRICE, date_col, column, start, checks,
                  demand_ids=(demand_id,) if demand_id else (), cadence="market", rule="positive")


PRICE_PANELS = (
    panel("spot", "CCI5500", (
        price("cci5500", "CCI5500", "B", date_col="A", start=6,
              header="动力煤价格指数(RMB):CCI5500(含税)", demand_id=105),
    )),
    panel("ordos", "鄂尔多斯坑口", (
        price(f"ordos{heat}", f"内蒙古鄂尔多斯{heat}", column, demand_id=106 if heat == 5500 else None,
              price_type="坑口含税价")
        for heat, column in ((5500, "CA"), (5000, "CC"), (4500, "CE"))
    ), "当前坑口含税报价。历史旧源另列，便于核对价差和覆盖期。"),
    panel("shanxi", "山西坑口", (
        price(key, name, col, demand_id=demand_id, price_type="坑口含税价")
        for key, name, col, demand_id in (
            ("shuozhou5000", "山西朔州5000", "CI", None),
            ("datong5500", "山西大同5500", "CG", 107),
            ("changzhi5800", "山西长治5800", "CK", None),
        )
    )),
    panel("import-usd", "进口到岸 · 美元", (
        metric("import4700-usd", "CCI进口4700", "美元/吨", "daily", "动力煤-价格", "A", "M", 6,
               (("M4", "CCI进口4700"), ("M5", "美元/吨")), rule="positive"),
        metric("import3800-usd", "CCI进口3800", "美元/吨", "daily", "动力煤-价格", "A", "N", 6,
               (("N4", "CCI进口3800"), ("N5", "美元/吨")), rule="positive"),
    )),
    panel("international", "国际动力煤", (
        price(key, name, column, "美元/吨", date_column, 6, header, demand_id)
        for key, name, column, date_column, header, demand_id in (
            ("newcastle", "纽卡斯尔 NEWC", "O", "M", "纽卡斯尔NEWC动力煤现货价", 94),
            ("newcastle5500", "纽卡斯尔5500", "R", "Q", "纽卡斯尔港:FOB价:动力煤(2#,A23%,Q5500,NAR)", 95),
            ("richards-bay", "理查德 RB", "N", "M", "理查德RB动力煤现货价", 96),
            ("ara", "欧洲 ARA", "P", "M", "欧洲ARA港动力煤现货价", 97),
        )
    )),
    panel("freight", "国际煤炭海运费", (
        price("freight-australia", "澳大利亚纽卡斯尔—中国舟山", "AC", "美元/吨", "AB", 6,
              "FDI:煤炭:澳大利亚纽卡斯尔-中国舟山", 103),
        price("freight-indonesia", "印尼塔巴尼奥—中国广州", "AD", "美元/吨", "AB", 6,
              "FDI:煤炭:印尼塔巴尼奥-中国广州", 104),
    )),
)


def weekly_stock(series_id, name, date_col, column, header, demand_id=None):
    return metric(series_id, name, "万吨", "weekly", STOCK, date_col, column, 7,
                  ((f"{column}4", header), (f"{column}5", "周"), (f"{column}6", "万吨")),
                  demand_ids=(demand_id,) if demand_id else ())


def fw_stock(series_id, name, columns, labels):
    return metric(series_id, name, "万吨", "daily", "Raw data-港口库存", "A", columns, 5,
                  [(f"{col}2", label) for col, label in zip(columns.split(), labels)]
                  + [(f"{col}4", "万吨") for col in columns.split()])


INVENTORY_PANELS = tuple(
    panel(key, name, (metric(
        key, name, "万吨", "daily", "动力煤-港口库存", "A", column, 6,
        ((f"{title_column}3", title), (f"{column}4", "库存"), (f"{column}5", "万吨")),
        reported=(mom, yoy), end_marker="Source",
    ),))
    for key, name, column, title_column, title, mom, yoy in (
        ("yangtze-stock", "长江口库存", "B", "C", "长江口库存", "C", "D"),
        ("north-stock", "北方港港口库存", "E", "F", "北方港港口", "F", "G"),
        ("cctd-total", "CCTD主流港口·合计", "H", "I", "CCTD主流港口:合计", "I", "J"),
        ("cctd-coastal", "CCTD主流港口·沿海", "K", "L", "CCTD主流港口:沿海港口", "L", "M"),
        ("cctd-river", "CCTD主流港口·内河", "N", "O", "CCTD主流港口:内河港口", "O", "P"),
    )
)

PORTS = ("秦皇岛港", "曹妃甸港", "黄骅港")
PORT_COLUMNS = ("BCD", "EFG", "HIJ")
PORT_FIELDS = ("铁路调入量", "港口吞吐量", "锚地船舶数")
PORT_CHECKS = tuple((f"{column}3", f"煤炭调度:{port}:{field}")
                    for port, columns in zip(PORTS, PORT_COLUMNS)
                    for column, field in zip(columns, PORT_FIELDS)) + (
                        ("K3", "煤炭库存:秦皇岛港"), ("L3", "煤炭库存:曹妃甸港"), ("M3", "黄华港库存"),
                        ("B4", "万吨"), ("C4", "万吨"), ("D4", "艘"),
                    )


def transport_panels():
    configs = (
        ("in", "铁路调入", "万吨", 0), ("out", "港口吞吐", "万吨", 1),
        ("ships", "锚地船舶", "艘", 2), ("stock", "三港库存", "万吨", 3),
        ("balance", "港口供需平衡", "千吨", 4),
    )
    for panel_id, name, unit, index in configs:
        subsets = ("K", "L", "M") if index == 3 else tuple(
            columns[:2] if index == 4 else columns[index] for columns in PORT_COLUMNS
        )
        series = []
        for region, port, columns in zip(("total", "qhd", "cfd", "hh"), ("三港合计", *PORTS),
                                         ("".join(subsets), *subsets)):
            series.append(metric(f"port-{panel_id}-{region}", port, unit, "daily", TRANSPORT, "A",
                                 " ".join(columns), 5, PORT_CHECKS,
                                 rule="transport_balance" if index == 4 else "transport",
                                 scale=10 if index == 4 else 1))
        yield panel(panel_id, name, series, "合计按三港同日的有效分项计算。")


def plant_panel(prefix, sheet, first_id):
    metrics = []
    for index, (key, label, column, title_column, unit) in enumerate((
        ("use", "日耗", "B", "C" if prefix != "inland" else "B", "万吨"),
        ("stock", "库存", "E", "F", "万吨"), ("days", "可用天数", "H", "I", "天"),
        ("supply", "供煤", "K", "L", "万吨"),
    )):
        item = metric(f"{prefix}-{key}", label, unit, "daily", sheet, "A", column, 6,
                      ((f"{title_column}4", label), (f"{column}5", unit)), demand_ids=(first_id + index,),
                      rule="positive" if prefix == "plants25" else "value")
        metrics.append(panel(key, label, (item,)))
    return tuple(metrics)


def power_panels():
    sources = (
        ("monthly", "当月发电量", "BCDE", "亿千瓦时", "monthly", "FGHI", "JKLM", 13),
        ("monthly-yoy", "当月发电同比", "JKLM", "%", "monthly", "", "", 17),
        ("ytd", "年初至今累计发电量", "NOPQ", "亿千瓦时", "ytd", "", "RSTU", 21),
        ("ytd-yoy", "累计发电同比", "RSTU", "%", "ytd", "", "", 25),
    )
    for panel_id, title, columns, unit, frequency, mom, yoy, first_id in sources:
        series = []
        for index, (key, name, header, col) in enumerate(zip(
            ("total", "thermal", "hydro", "other"), ("总发电", "火电", "水电", "其他"),
            ("全社会", "火电", "水电", "其他"), columns,
        )):
            if index == 0:
                header = {"ytd": "累计值", "ytd-yoy": "YTD YoY"}.get(panel_id, header)
            series.append(metric(f"power-{panel_id}-{key}", name, unit, frequency, POWER, "A", col, 6,
                                 ((f"{col}4", header), (f"{col}5", unit)), demand_ids=(first_id + index,),
                                 reported=(mom[index] if mom else "", yoy[index] if yoy else ""),
                                 rule="monthly_split", reported_only=True))
        yield panel(panel_id, title, series, "其他为总发电减火电和水电。")
    yield panel("gd-electricity", "广东日前现货平均电价", (
        metric(key, name, "元/兆瓦时", "daily", PRICE, "EG", col, 7,
               ((f"{col}1", f"日前现货成交电价:平均电价:{header}:广东"), (f"{col}3", "厘/千瓦时")),
               demand_ids=(demand_id,))
        for key, name, header, col, demand_id in (
            ("gd-coal", "广东燃煤", "燃煤", "EI", 36), ("gd-all", "广东发电侧", "发电侧", "EJ", 37),
        )
    ), "原单位厘/千瓦时，转换后数值相同。")


CHEMICALS = tuple(metric(f"chem-{key}", name, "万吨", "weekly", "动力煤-化工周度", "A", column, 2,
                         (("A1", "日期"), (f"{column}1", header)), demand_ids=(38,) if key == "total" else ())
                  for key, name, column, header in (
                      ("total", "五类化工合计", "B", "化工行业合计耗煤（甲醇、合成氨、PVC、纯碱、乙二醇）（万吨）"),
                      ("methanol", "甲醇", "C", "甲醇耗煤（万吨）"),
                      ("ammonia", "合成氨", "D", "合成氨耗煤（万吨）"),
                      ("pvc", "PVC", "E", "PVC耗煤（万吨）"),
                      ("soda", "纯碱", "F", "纯碱耗煤（万吨）"),
                      ("glycol", "乙二醇", "G", "乙二醇耗煤（万吨）"),
                  ))


def ten_day_series(growth=False):
    for key, name, header, col, rate, demand_id in (
        ("total", "总发电", "总发电量", "B", "C", 29),
        ("thermal", "火电", "火电", "D", "E", 30),
        ("hydro", "水电", "水电", "F", "G", 31),
    ):
        yield metric(f"ten-day-{key}{'-yoy' if growth else ''}", name, "%" if growth else "亿千瓦时/日",
                     "tenDay", TEN_DAY, "A", rate if growth else col, 6,
                     ((f"{col}4", header), (f"{col}5", "亿千瓦时"), (f"{rate}4", "同比")),
                     demand_ids=(demand_id + 3 if growth else demand_id,), reported=("", "" if growth else rate))


def industry_use_panels():
    industries = (
        ("total", "总消费量", "总消费量", "B", "C"),
        ("power", "电力", "电力行业消费量", "D", "E"),
        ("heating", "供热", "供热耗煤消费量", "F", "G"),
        ("materials", "建材", "建材行业消费量", "H", "I"),
        ("metallurgy", "冶金", "冶金行业消费量", "J", "K"),
        ("chemicals", "化工", "化工行业消费量", "L", "M"),
        ("other", "其他行业", "其他行业消费量", "N", "O"),
    )
    for scope, label, selected in (("total", "总消费量", industries[:1]), ("sectors", "分行业", industries[1:])):
        for frequency, title, value_item in (
            ("monthly", "当月值", "月度值"), ("ytd", "年初至今累计", "月度累计值"),
        ):
            metrics = []
            for key, name, header, monthly_col, ytd_col in selected:
                col = monthly_col if frequency == "monthly" else ytd_col
                metrics.append(metric(f"industry-use-{frequency}-{key}", name, "万吨", frequency, INDUSTRY_USE, "A",
                                      col, 7, ((f"{col}2", header), (f"{col}3", "月度"),
                                               (f"{col}4", value_item), (f"{col}5", "万吨"))))
            yield panel(f"{scope}-{frequency}", f"{label} · {title}", metrics, "来源：中国煤炭资源网 FW5002D。")


COUNTRY_IMPORTS = tuple(
    metric(f"country-import-{key}", name, "万吨", "monthly", IMPORTS, "A", col, 6,
           (("AW3", "动力煤分国别进口量"), (f"{col}4", name), (f"{col}5", "千吨")),
           demand_ids=(demand_id,), scale=0.1, end_marker="Source")
    for key, name, col, demand_id in (
        ("australia", "澳大利亚", "AW", 134), ("indonesia", "印度尼西亚", "AX", 135),
        ("russia", "俄罗斯", "AY", 136), ("other", "其他", "AZ", 137),
    )
)


THERMAL_GROUPS = (
    ("price", "价格", PRICE_PANELS),
    ("inventory", "港口库存", INVENTORY_PANELS),
    ("transport", "港口运输", tuple(transport_panels())),
    ("plants25", "二十五省电厂汇总", plant_panel("plants25", "动力煤-二十五省汇总", 9)),
    ("inland", "内陆十七省电厂", plant_panel("inland", "动力煤-内陆电厂", 1)),
    ("coastal", "沿海八省电厂", plant_panel("coastal", "动力煤-沿海电厂", 5)),
    ("power", "下游月度发电", tuple(power_panels())),
    ("ten-day", "下游旬度发电", (
        panel("generation", "旬度日均发电量", ten_day_series()),
        panel("growth", "旬度发电同比", ten_day_series(True)),
    )),
    ("three-gorges", "三峡出库流量", (
        panel("three-gorges", "三峡出库流量", (
            metric("three-gorges", "三峡出库流量", "立方米/秒", "daily", TEN_DAY, "CN", "CO", 9,
                   (("CO7", "中国:流量(出库):水库站:三峡"), ("CO8", "立方米/秒")), demand_ids=(35,)),
        )),
    )),
    ("chemical", "下游化工周度", (
        panel("total", "五类化工合计耗煤", CHEMICALS[:1]), panel("parts", "化工分项耗煤", CHEMICALS[1:]),
    )),
    ("industry-use", "分行业煤耗", tuple(industry_use_panels())),
    ("country-import", "分国别进口", (
        panel("monthly", "动力煤分国别进口量", COUNTRY_IMPORTS, "原表单位为千吨，图中统一换算为万吨。其他沿用原表分类。"),
    )),
)


def detail_specs(groups):
    for _, _, panels in groups:
        for _, _, metrics, _ in panels:
            yield from metrics


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def period_key(day, frequency):
    if frequency == "weekly":
        return day - timedelta(days=day.weekday())
    if frequency == "tenDay":
        return day.replace(day=1 if day.day <= 10 else 11 if day.day <= 20 else 21)
    if frequency in {"monthly", "ytd"}:
        return day.replace(day=1)
    return day


def shift_month(day, month_count):
    year, month = divmod(day.year * 12 + day.month - 1 + month_count, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def comparison_key(day, frequency, annual):
    if frequency == "weekly":
        if not annual:
            return day - timedelta(days=7)
        year, week, _ = day.isocalendar()
        try:
            return date.fromisocalendar(year - 1, week, 1)
        except ValueError:
            return None
    if frequency == "tenDay" and not annual:
        return day.replace(day=day.day - 10) if day.day > 1 else shift_month(day, -1).replace(day=21)
    if frequency == "ytd" and day.month == 1 and not annual:
        return None
    return shift_month(day, -12 if annual else -1)


def compare(spec, current, reference, reported, target):
    if spec.frequency == "ytd" and target is None:
        return [None, None, "year-reset"]
    if current[0] is None:
        return [None, None, "missing"]
    if reference and (current[1] == "combined") != (reference[1][1] == "combined"):
        return [None, None, "different-period"]
    basis = reference[0].isoformat() if reference else None
    if finite(reported):
        result = [round(reported, 8), basis, "reported"]
        return result + [True] if reference and reference[1][1] == "estimated" else result
    if spec.reported_only:
        return [None, None, "not-reported"]
    if not reference:
        return [None, None, "no-base"]
    base, quality, _ = reference[1]
    estimated = quality == "estimated"
    value = current[0]
    if spec.unit == "%" or spec.rule == "transport_balance":
        result = round(value - base, 8)
        return [result, basis, "value", True] if estimated else [result, basis]
    if base <= 0:
        return [None, basis, "nonpositive-base", estimated, round(value - base, 6)]
    result = round(value / base - 1, 8)
    return [result, basis, "value", True] if estimated else [result, basis]


def row_value(spec, values):
    if not all(finite(value) for value in values):
        return None, "excel-error" if any(isinstance(value, str) and value.startswith("#") for value in values) else "missing"
    if spec.rule == "positive" and values[0] <= 0:
        return None, "placeholder"
    if spec.rule == "transport_balance":
        value = sum(values[::2]) - sum(values[1::2])
    else:
        value = sum(values)
    return round(value * spec.scale, 8), ""


def transport_check(get, day):
    uncertain = set()
    for columns in PORT_COLUMNS:
        inflow, outflow, ships = (get(column) for column in columns)
        if inflow == outflow == 0:
            uncertain.update(columns[:2])
            if ships == 0:
                uncertain.add(columns[2])
    for column in ("K", "L", "M"):
        if get(column) == 0 and day < date(2014, 3, 19):
            uncertain.add(column)
    return uncertain


def monthly_periods(sheet, parse_date, epoch, cumulative_index, extra_split_days):
    by_period = {}
    for row in sheet.rows[5:]:
        day = parse_date(row[0], epoch)
        if day and day.month in {1, 2}:
            by_period[(day.year, day.month)] = row
    estimates, combined = set(), set()
    for (year, month), feb in by_period.items():
        total = feb[cumulative_index]
        if month != 2 or not finite(total) or total <= 0:
            continue
        jan = by_period.get((year, 1))
        if jan is None or not finite(jan[1]) or jan[1] == 0:
            if not finite(feb[1]) or feb[1] == 0 or math.isclose(feb[1], total, abs_tol=0.00001):
                combined.add(year)
            continue
        month_days = calendar.monthrange(year, 2)[1]
        if finite(feb[1]):
            split_days = (31 + month_days, *extra_split_days)
            match = any(math.isclose(jan[1], total * 31 / days, abs_tol=0.00001) for days in split_days)
            if match and math.isclose(jan[1] + feb[1], total, abs_tol=0.00001):
                estimates.update(((year, 1), (year, 2)))
    return estimates, combined


def read_metric(spec, sheet, parse_date, epoch, col_index, monthly_calendar, combined_columns):
    date_index = col_index(spec.date_column) - 1
    indices = {col: col_index(col) - 1 for col in (*spec.value_columns, *"BCDEFGHIJKLM")
               if col}
    values = {}
    duplicate_count = conflict_count = 0
    estimated_periods, combined_years = monthly_calendar
    for row in sheet.rows[spec.start_row - 1:]:
        raw_date = row[date_index]
        if spec.end_marker and isinstance(raw_date, str) and raw_date.strip().casefold().startswith(spec.end_marker.casefold()):
            break
        day = parse_date(raw_date, epoch)
        if not day:
            continue
        def get(column):
            return row[indices[column]] if column and indices[column] < len(row) else None
        value, quality = row_value(spec, [get(col) for col in spec.columns])
        rates = tuple(get(col) * scale if finite(get(col)) else None
                      for col, scale in zip(spec.reported, spec.reported_scales))
        if spec.sheet == TRANSPORT and set(spec.columns) & transport_check(get, day):
            value, quality = None, "coverage"
        if spec.rule == "monthly_split" and value is not None and (day.year, day.month) in estimated_periods:
            if spec.frequency != "ytd" or day.month == 1:
                quality = "estimated"
        if spec.rule == "monthly_split" and spec.frequency == "monthly" and day.year in combined_years:
            column = spec.columns[0]
            if day.month == 1:
                value, quality = None, "missing"
            elif day.month == 2:
                combined_column = combined_columns.get(column)
                value, quality = row_value(spec, [row[col_index(combined_column) - 1] if combined_column else None])
                rates = (None, None)
                if value is not None:
                    quality = "combined"
        if day in values:
            duplicate_count += 1
            conflict_count += int(value != values[day][0] and value is not None and values[day][0] is not None)
            if value is None and values[day][0] is not None:
                continue
        values[day] = (value, quality, rates)
    days = sorted(values)
    valid_days = [day for day in days if values[day][0] is not None]
    source = {"sheet": spec.sheet, "dateColumn": spec.date_column, "valueColumns": list(spec.columns),
              "reportedColumns": list(spec.reported), "startRow": spec.start_row, "scale": spec.scale,
              "demandIds": list(spec.demand_ids)}
    latest = valid_days[-1].isoformat() if valid_days else None
    first = valid_days[0].isoformat() if valid_days else None
    by_period = {period_key(day, spec.frequency): (day, values[day]) for day in valid_days}
    gaps = 0
    periods = sorted(by_period)
    if spec.frequency in {"weekly", "tenDay", "monthly"}:
        gaps = sum(comparison_key(next_day, spec.frequency, False) != previous_day
                   for previous_day, next_day in zip(periods, periods[1:]))
    if spec.frequency == "daily":
        allowed = 7 if spec.cadence == "market" else 1
        gaps = sum((later - earlier).days > allowed for earlier, later in zip(valid_days, valid_days[1:]))
    points = []
    for day in days[bisect_left(days, valid_days[0]) if valid_days else len(days):]:
        current = values[day]
        changes = []
        for annual, reported in zip((False, True), current[2]):
            target = comparison_key(period_key(day, spec.frequency), spec.frequency, annual)
            reference = by_period.get(target)
            if target and reference is None and spec.cadence == "market":
                index = bisect_right(valid_days, target) - 1
                if index >= 0 and (target - valid_days[index]).days <= 7:
                    reference = valid_days[index], values[valid_days[index]]
            changes.append(compare(spec, current, reference, reported, target))
        point = [day.isoformat(), current[0], *changes]
        points.append(point + [current[1]] if current[1] else point)
    data = {"id": spec.id, "name": spec.name, "unit": spec.unit, "frequency": spec.frequency,
            "cadence": spec.cadence, "source": source, "firstValidDate": first, "latestValidDate": latest,
            "changeUnit": "pp" if spec.unit == "%" else "absolute" if spec.rule == "transport_balance" else "%",
            "points": points}
    report = {"id": spec.id, **source, "firstDate": first, "lastDate": latest,
              "lastDatedRow": days[-1].isoformat() if days else None, "validPointCount": len(valid_days),
              "duplicateDates": duplicate_count, "conflictingDates": conflict_count, "gapCount": gaps,
              "qualityCounts": dict(Counter(quality for _, quality, _ in values.values() if quality))}
    return data, report


def extract_thermal(sheets, epoch, parse_date, col_index):
    return extract_detail(THERMAL_GROUPS, "动力煤", sheets, epoch, parse_date, col_index,
                          POWER, "N", COMBINED_POWER_COLUMNS)


def extract_detail(config, label, sheets, epoch, parse_date, col_index, monthly_sheet=None, cumulative_col=None,
                   combined_columns=None, extra_split_days=()):
    series, groups, reports = {}, [], []
    dates, date_indices = [], {}
    monthly_calendar = monthly_periods(sheets[monthly_sheet], parse_date, epoch,
                                       col_index(cumulative_col) - 1, extra_split_days) if monthly_sheet else (set(), set())
    for group_id, group_name, panels in config:
        visible_panels = []
        for panel_id, title, metrics, note in panels:
            for spec in metrics:
                item, report = read_metric(spec, sheets[spec.sheet], parse_date, epoch, col_index,
                                           monthly_calendar, combined_columns or {})
                item["points"] = [point for point in item["points"] if "2021-01-01" <= point[0] <= "2026-12-31"]
                valid = [point for point in item["points"] if point[1] is not None]
                item["firstValidDate"] = valid[0][0] if valid else None
                item["latestValidDate"] = valid[-1][0] if valid else None
                for point in item["points"]:
                    for record, field in ((point, 0), (point[2], 1), (point[3], 1)):
                        stamp = record[field]
                        if stamp is not None:
                            if stamp not in date_indices:
                                date_indices[stamp] = len(dates)
                                dates.append(stamp)
                            record[field] = date_indices[stamp]
                series[spec.id] = item
                reports.append(report)
            visible_panels.append({"id": panel_id, "name": title, "note": note,
                                   "seriesIds": [spec.id for spec in metrics]})
        if not any(series[spec.id]["latestValidDate"] for _, _, metrics, _ in panels for spec in metrics):
            raise ValueError(f"{label}「{group_name}」没有有效数据，请核对来源及公式缓存。")
        groups.append({"id": group_id, "name": group_name, "panels": visible_panels})
    return {
        "groups": groups, "series": series, "dates": dates,
        "pointFields": ["dateIndex", "value", "mom", "yoy", "quality"],
        "comparisonFields": ["value", "baseDateIndex", "status", "estimatedBase", "absoluteChange"],
    }, reports
