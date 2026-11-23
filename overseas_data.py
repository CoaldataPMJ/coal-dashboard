from thermal_data import extract_detail, metric, panel, price


OVERSEAS_GROUPS = (
    ("oil", "国际原油", (
        panel("prices", "国际原油价格", (
            metric(key, name, "美元/桶", "daily", "国际能源", "G", column, 4,
                   ((f"{column}2", header), (f"{column}3", "美元/桶")), cadence="market", rule="positive")
            for key, name, column, header in (
                ("wti", "WTI原油", "H", "期货结算价(连续):WTI原油"),
                ("brent", "布伦特原油", "I", "期货结算价(连续):布伦特原油"),
                ("oman", "阿曼原油", "J", "全球:现货价:原油(阿曼)"),
            )
        )),
    )),
    ("gas", "海外天然气", (
        panel("henry-hub", "NYMEX Henry Hub", (
            price("henry-hub", "NYMEX Henry Hub", "X", "美元/百万英热单位", "W", 7,
                  "期货收盘价(连续):NYMEX天然气", 93),
        )),
        panel("ttf", "ICE TTF", (
            price("ttf", "ICE TTF", "Y", "欧元/兆瓦时", "W", 7,
                  "期货结算价(连续):ICE荷兰TTF天然气", 92),
        )),
    )),
)


def extract_overseas(sheets, epoch, parse_date, col_index):
    return extract_detail(OVERSEAS_GROUPS, "海外能源", sheets, epoch, parse_date, col_index)
