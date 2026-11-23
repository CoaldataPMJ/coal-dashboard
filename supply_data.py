from thermal_data import extract_detail, metric, panel


SUPPLY_SHEET = "产量及进口"
PROVINCE_MONTH = "主要产地月度产量"
PROVINCE_WEEK = "主要产地周度产量"


def national_production():
    for key, name, monthly, mom, yoy, daily, cumulative, cumulative_yoy in (
        ("raw", "原煤", "B", "C", "D", "E", "F", "G"),
        ("coking", "炼焦精煤", "H", "I", "J", "K", "L", "M"),
    ):
        for scope, label, column, frequency, header, rates in (
            ("monthly", "当月产量", monthly, "monthly", f"{name}当月产量", (mom, yoy)),
            ("daily", "月度日均产量", daily, "monthly", f"{name}月度日均产量", ("", "")),
            ("ytd", "累计产量", cumulative, "ytd", f"{name}累计产量", ("", cumulative_yoy)),
        ):
            item = metric(f"production-{key}-{scope}", name, "万吨/日" if scope == "daily" else "万吨",
                          frequency, SUPPLY_SHEET, "A", column, 6,
                          ((f"{column}4", header), (f"{column}5", "百万吨")), scale=100,
                          rule="positive", reported=rates, reported_only=scope != "daily", end_marker="Source")
            yield panel(f"{key}-{scope}", f"{name} · {label}", (item,))


def import_totals():
    for scope, title, frequency, columns, mom, yoy in (
        ("monthly", "进口当月值", "monthly", "NOP", "QRS", "TUV"),
        ("ytd", "进口累计值", "ytd", "WXY", "", "Z AA AB".split()),
    ):
        entries = []
        for index, (key, name, column) in enumerate(zip(("all", "thermal", "coking"), ("煤及褐煤", "动力煤", "炼焦煤"), columns)):
            header = f"{'当月值' if scope == 'monthly' else '累计值'}：{name}"
            entries.append(metric(f"import-{key}-{scope}", name, "万吨", frequency, SUPPLY_SHEET, "A", column, 6,
                                  ((f"{column}4", header), (f"{column}5", "万吨")),
                                  reported=(mom[index] if mom else "", yoy[index]), reported_only=True,
                                  end_marker="Source"))
        yield panel(scope, title, entries)


def country_imports():
    configs = (
        ("all", "煤及褐煤", "AE", (
            ("australia", "澳大利亚", "AC"), ("indonesia", "印度尼西亚", "AD"), ("mongolia", "蒙古", "AE"),
            ("russia", "俄罗斯", "AF"), ("other", "其它", "AG"), ("philippines", "菲律宾", "AH"),
            ("canada", "加拿大", "AI"), ("laos", "老挝", "AJ"),
        )),
        ("lignite", "褐煤分国别进口量", "AK", (
            ("us", "美国", "AK"), ("mongolia", "蒙古", "AL"), ("indonesia", "印度尼西亚", "AM"), ("other", "其他", "AN"),
        )),
        ("coal", "煤炭分国别进口量", "AS", (
            ("australia", "澳大利亚", "AO"), ("indonesia", "印度尼西亚", "AP"), ("malaysia", "马来西亚", "AQ"),
            ("russia", "俄罗斯", "AR"), ("vietnam", "越南", "AS"), ("mongolia", "蒙古", "AT"),
            ("us", "美国", "AU"), ("other", "其他", "AV"),
        )),
        ("thermal", "动力煤分国别进口量", "AW", (
            ("australia", "澳大利亚", "AW"), ("indonesia", "印度尼西亚", "AX"), ("russia", "俄罗斯", "AY"), ("other", "其他", "AZ"),
        )),
        ("coking", "焦煤分国别进口量", "BC", (
            ("australia", "澳大利亚", "BA"), ("mongolia", "蒙古", "BB"), ("russia", "俄罗斯", "BC"),
            ("us-canada", "美国及加拿大", "BD"), ("other", "其他", "BE"),
        )),
        ("anthracite", "无烟煤分国别进口量", "BH", (
            ("australia", "澳大利亚", "BF"), ("north-korea", "朝鲜", "BG"), ("russia", "俄罗斯", "BH"),
            ("vietnam", "越南", "BI"), ("other", "其他", "BJ"),
        )),
    )
    for category, title, title_col, entries in configs:
        yield panel(category, f"{title} · 当月值", (
            metric(f"supply-country-{category}-{key}", name, "万吨", "monthly", SUPPLY_SHEET, "A", column, 6,
                   ((f"{title_col}3", title), (f"{column}4", name), (f"{column}5", "千吨")),
                   scale=0.1, end_marker="Source")
            for key, name, column in entries
        ))


PROVINCES = (
    ("all", "合计", "B", "C", "D", "E"), ("shanxi", "山西", "F", "G", "H", "I"),
    ("inner-mongolia", "内蒙古", "J", "K", "L", "M"), ("shaanxi", "陕西", "N", "O", "P", "Q"),
    ("xinjiang", "新疆", "R", "S", "T", "U"),
)


def province_monthly():
    for scope, title, frequency, unit, field, header in (
        ("monthly", "当月产量", "monthly", "万吨", 2, "月度值"),
        ("ytd", "累计产量", "ytd", "万吨", 3, "月度累计值"),
        ("monthly-yoy", "当月产量同比", "monthly", "%", 4, "当月同比增长"),
        ("ytd-yoy", "累计产量同比", "ytd", "%", 5, "累计同比增长"),
    ):
        entries = []
        for province in PROVINCES:
            key, name, monthly, cumulative, yoy, cumulative_yoy = province
            column = province[field]
            rates = ("", yoy if scope == "monthly" else cumulative_yoy) if unit == "万吨" else ("", "")
            entries.append(metric(f"province-{scope}-{key}", "全国" if key == "all" else name, unit, frequency,
                                  PROVINCE_MONTH, "A", column, 6,
                                  ((f"{column}2", name), (f"{column}3", header), (f"{column}4", unit)),
                                  scale=0.01 if unit == "%" else 1, rule="positive" if unit == "万吨" else "value",
                                  reported=rates, reported_scales=(1, 0.01), reported_only=unit == "%",
                                  end_marker="Source"))
        yield panel(scope, title, entries)


def province_weekly():
    regions = (
        ("all", "三省合计", "L", "K", "L", "M"), ("shanxi", "山西", "C", "B", "C", "D"),
        ("inner-mongolia", "内蒙古", "F", "E", "F", "G"), ("shaanxi", "陕西", "I", "H", "I", "J"),
    )
    for scope, title, unit in (("output", "周度原煤产量", "万吨"), ("utilization", "产能利用率", "%")):
        entries = []
        for key, name, title_col, output, mom, utilization in regions:
            column = output if scope == "output" else utilization
            entries.append(metric(f"province-weekly-{scope}-{key}", name, unit, "weekly", PROVINCE_WEEK, "A", column, 6,
                                  ((f"{title_col}3", name), (f"{column}4", "产量" if scope == "output" else "产能利用率"),
                                   (f"{column}5", unit)), reported=(mom, "") if scope == "output" else ("", ""),
                                  rule="positive", end_marker="Source"))
        yield panel(scope, title, entries)


SUPPLY_GROUPS = (
    ("production", "国内煤炭产量", tuple(national_production())),
    ("imports", "煤炭进口总量", tuple(import_totals())),
    ("countries", "分国别进口", tuple(country_imports())),
    ("province-monthly", "主要产地月度产量", tuple(province_monthly())),
    ("province-weekly", "主要产地周度产量", tuple(province_weekly())),
)


def extract_supply(sheets, epoch, parse_date, col_index):
    return extract_detail(SUPPLY_GROUPS, "产量及进口", sheets, epoch, parse_date, col_index)
