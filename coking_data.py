from __future__ import annotations

from thermal_data import PRICE, STOCK, extract_detail, metric, panel, price


DOWNSTREAM = "炼焦煤-下游 "
COMBINED_COLUMNS = dict(zip("BCDHIJ", "KLMNOP"))


STEEL_PANELS = (
    panel("hot-metal", "247家钢厂日均铁水产量", (
        metric("steel-hot-metal", "日均铁水产量", "万吨/日", "weekly", "钢铁", "A", "B", 4,
               (("B1", "日均铁水产量:全国(样本数247家):当周值"),
                ("B2", "中国:日均产量(247家):铁水"), ("B3", "万吨")),
               demand_ids=(42,), rule="positive"),
    ), "每周更新，数值为当周日均铁水产量。"),
    panel("blast-furnace", "247家钢厂高炉开工率", (
        metric("steel-blast-furnace", "高炉开工率", "%", "weekly", "钢铁", "A", "C", 4,
               (("C1", "高炉开工率:全国(样本数247家):当周值"),
                ("C2", "中国:高炉开工率(247家)"), ("C3", "%")),
               demand_ids=(43,), scale=0.01),
    ), "每周更新，较前周、上年同周变化以百分点显示。"),
)


def domestic(series_id, name, col, demand_id=None):
    return price(series_id, name, col, date_col="AP", start=6,
                 header=f"冶金煤价格指数:CCI{name}(含税)", demand_id=demand_id)


def international(series_id, name, col, demand_id=None):
    return price(series_id, name, col, unit="美元/吨", date_col="AW", start=6,
                 header=f"炼焦煤指数:{name}", demand_id=demand_id)


PRICE_PANELS = (
    panel("domestic", "国内炼焦煤坑口价", (
        domestic("coking-liulin-low", "柳林低硫主焦", "AQ", 110),
        domestic("coking-liulin-high", "柳林高硫主焦", "AR"),
        domestic("coking-lingshi", "灵石高硫肥煤", "AS"),
        domestic("coking-jining", "济宁气煤", "AT"),
    ), "按《炼焦煤-价格》追溯至底表的 CCI 含税报价。"),
    panel("international", "国际炼焦煤价格", (
        international("coking-peak-downs", "峰景矿硬焦煤", "AX"),
        international("coking-mid-vol", "中挥发硬焦煤", "AY"),
        international("coking-low-vol", "低挥发主焦煤", "AZ", 98),
    ), "沿用底表的实际报价日，展示表的沿用价不计为新报价。"),
    panel("domestic-pci", "国内喷吹煤价格", (
        domestic("pci-changzhi", "长治喷吹", "AU"),
    ), "喷吹煤为炼焦煤价格表中的关联指标。"),
    panel("international-pci", "国际喷吹煤价格", (
        international("pci-mid-vol", "中挥发喷吹煤", "BA"),
        international("pci-low-vol", "低挥发喷吹煤", "BB"),
    ), "喷吹煤为炼焦煤价格表中的关联指标。"),
)


def stock_metric(series_id, name, unit, date_col, col, header, rule="value"):
    checks = ((f"{date_col}4", "指标名称"), (f"{col}4", header),
              (f"{col}5", "周"), (f"{col}6", unit))
    return metric(series_id, name, unit, "weekly", STOCK, date_col, col, 7, checks,
                  scale=0.01 if unit == "%" else 1, rule=rule)


STEEL_REGIONS = (
    ("total", "总计", "BB", "BJ"), ("northeast", "东北", "AU", "BC"), ("north", "华北", "AV", "BD"),
    ("east", "华东", "AW", "BE"), ("south", "华南", "AX", "BF"), ("central", "华中", "AY", "BG"),
    ("northwest", "西北", "AZ", "BH"),
)
PLANT_REGIONS = (
    ("total", "总计", "BZ", "BS", "CL"), ("northeast", "东北", "BT", "BM", "CF"),
    ("north", "华北", "BU", "BN", "CG"), ("east", "华东", "BV", "BO", "CH"),
    ("southwest", "西南", "BY", "BR", "CK"), ("central", "华中", "BW", "BP", "CI"),
    ("northwest", "西北", "BX", "BQ", "CJ"),
)


def steel_stocks(days=False):
    measure = "炼焦煤平均可用天数" if days else "炼焦煤库存"
    prefix = f"{measure}:国内样本钢厂(110家)"
    for key, name, inventory_col, days_col in STEEL_REGIONS:
        tail = (":合计" if days else "") if key == "total" else f":{name}地区"
        yield stock_metric(f"coking-steel-{'days' if days else 'stock'}-{key}", name, "天" if days else "万吨",
                           "AT", days_col if days else inventory_col, prefix + tail, "positive" if days else "value")


def plant_stocks(kind):
    panel_info = {
        "stock": ("炼焦煤总库存", "万吨", "BL", "value"),
        "days": ("炼焦煤平均可用天数", "天", "BL", "positive"),
        "rate": ("焦炉生产率", "%", "CB", "value"),
    }
    measure, unit, date_col, rule = panel_info[kind]
    for key, name, stock_col, days_col, rate_col in PLANT_REGIONS:
        col = {"stock": stock_col, "days": days_col, "rate": rate_col}[kind]
        label = "合计" if key == "total" else name
        yield stock_metric(f"coking-plant-{kind}-{key}", name, unit, date_col, col,
                           f"{measure}:国内独立焦化厂(100家):{label}", rule)


STOCK_PANELS = (
    panel("ports", "三港炼焦煤库存", (
        stock_metric(f"coking-port-{key}", name, "万吨", "AN", col, f"炼焦煤库存:{header}",
                     "positive" if key == "total" else "value")
        for key, name, col, header in (
            ("total", "三港合计", "AO", "三港口合计"), ("jingtang", "京唐港", "AP", "京唐港"),
            ("rizhao", "日照港", "AQ", "日照港"), ("lianyungang", "连云港", "AR", "连云港"),
        )
    ), "沿用底表实际观测日期及各港已报值。"),
    panel("steel-stock", "110家样本钢厂炼焦煤库存", steel_stocks()),
    panel("steel-days", "110家样本钢厂库存可用天数", steel_stocks(True)),
    panel("plant-stock", "100家独立焦化厂炼焦煤库存", plant_stocks("stock")),
    panel("plant-days", "100家独立焦化厂库存可用天数", plant_stocks("days")),
    panel("plant-rate", "100家独立焦化厂开工率", plant_stocks("rate"), "原表指标为焦炉生产率。"),
    panel("plant-capacity-rate", "独立焦化厂分规模开工率", (
        stock_metric(f"coking-capacity-{key}", name, "%", "CB", col,
                     f"焦炉生产率:国内独立焦化厂(100家):产能{name}", "positive")
        for key, name, col in (("large", ">200万吨", "CC"), ("mid", "100-200万吨", "CD"), ("small", "<100万吨", "CE"))
    ), "按原表标注的产能规模分组。"),
)


def downstream_panels():
    data = (
        ("monthly", "产量当月值", "BCD", "万吨", "monthly", "EFG", "HIJ", 44),
        ("monthly-mom", "产量月度环比", "EFG", "%", "monthly", "", "", None),
        ("monthly-yoy", "产量月度同比", "HIJ", "%", "monthly", "", "", 47),
        ("ytd", "产量年初至今累计", "KLM", "万吨", "ytd", "", "NOP", 50),
        ("ytd-yoy", "产量累计同比", "NOP", "%", "ytd", "", "", 53),
    )
    for panel_id, title, columns, unit, frequency, mom, yoy, first_id in data:
        entries = []
        for index, (key, name, col) in enumerate(zip(("coke", "pig-iron", "steel"), ("焦炭", "生铁", "粗钢"), columns)):
            entries.append(metric(f"coking-output-{panel_id}-{key}", name, unit, frequency, DOWNSTREAM, "A", col, 6,
                                  ((f"{col}4", name), (f"{col}5", unit)),
                                  demand_ids=(first_id + index,) if first_id else (),
                                  reported=(mom[index] if mom else "", yoy[index] if yoy else ""), rule="monthly_split",
                                  end_marker="Source"))
        yield panel(panel_id, title, entries, "如原表按 1–2 月累计分摊，悬停会标注原表推算。")


COUNTRY_IMPORTS = tuple(
    metric(f"coking-import-{key}", name, "万吨", "monthly", "产量及进口", "A", col, 6,
           (("BC3", "焦煤分国别进口量"), (f"{col}4", name), (f"{col}5", "千吨")),
           demand_ids=(demand_id,), scale=0.1, end_marker="Source")
    for key, name, col, demand_id in (
        ("australia", "澳大利亚", "BA", 138), ("mongolia", "蒙古", "BB", 139),
        ("russia", "俄罗斯", "BC", 140), ("us-canada", "美国及加拿大", "BD", 141), ("other", "其他", "BE", 142),
    )
)


COKING_GROUPS = (
    ("price", "炼焦煤价格", PRICE_PANELS),
    ("steel", "247家钢厂高炉开工率", STEEL_PANELS),
    ("inventory", "炼焦煤库存与下游开工率", STOCK_PANELS),
    ("downstream", "炼焦煤下游产量", tuple(downstream_panels())),
    ("country-import", "炼焦煤分国别进口", (
        panel("monthly", "焦煤分国别进口量", COUNTRY_IMPORTS,
              "原表单位为千吨，图中统一换算为万吨。美国及加拿大与其他沿用原表合计分类。"),
    )),
)


def extract_coking(sheets, epoch, parse_date, col_index):
    return extract_detail(COKING_GROUPS, "炼焦煤", sheets, epoch, parse_date, col_index,
                          DOWNSTREAM, "K", COMBINED_COLUMNS, (60,))
