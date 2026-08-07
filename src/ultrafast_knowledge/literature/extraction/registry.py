"""Extraction 侧模式注册表（规则层候选检测用）。

与全局 ontology 的关系：材料 canonical 复用 ultrafast_shared/ontology；
工艺/几何为抽取专用 registry（避免污染 TaskContext 的工艺下拉语义）。

原则：正则只做"候选发现"，不裁决语义角色（角色归 LLM，未知则 abstain）。
"""

from __future__ import annotations

import re


def _compiled(expression: str) -> re.Pattern[str]:
    return re.compile(expression, re.IGNORECASE)


# ---- 材料候选模式（长/特异优先，SiC 先于 Si、TBC 先于 Glass）----
MATERIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SiCp/Al", _compiled(r"\bAl[- ]?SiC\b|al(?:uminium|uminum) silicon carbide|sicp[/ ]al|sic particle reinforced al(?:uminium|uminum)|铝碳化硅|碳化硅颗粒增强铝")),
    ("Aluminum", _compiled(r"\bal[- ]?\d{4}\b|\baluminum\b|\baluminium\b|aluminum alloy|aluminium alloy|铝合金|\bal\b")),
    ("CFRP", _compiled(r"\bT300\b|\bCFRP\b|carbon fib(?:er|re) reinforced|碳纤维增强|碳纤维复合|碳纤维")),
    ("Copper", _compiled(r"\bcopper\b|\bCu\b|无氧铜")),
    ("Diamond", _compiled(r"\bdiamond\b|金刚石")),
    ("Epoxy", _compiled(r"\bepoxy\b|环氧树脂|环氧胶|环氧")),
    ("FusedSilica", _compiled(r"fused silica|fused quartz|quartz glass|silicon dioxide|\bsilica\b|熔融石英|石英玻璃|二氧化硅")),
    ("GlassCeramic", _compiled(r"glass[- ]?ceramic|microcrystalline glass|微晶玻璃")),
    ("Glass", _compiled(r"boro[- ]?aluminosilicate glass|borosilicate glass|soda[- ]?lime glass|cover glass|chemically strengthened glass|glass wafer|glass substrate|ultra[- ]?thin glass|\bglass\b|玻璃基板|玻璃晶圆|玻璃盖板|超薄玻璃|硼硅酸盐玻璃|\b玻璃\b")),
    ("NickelSuperalloy", _compiled(r"nickel[- ]?based superalloy|nickel superalloy|nickel[- ]?base superalloy|\bInconel\b|\bCMSX\b|\bGH\d{4}\b|镍基高温合金|镍基合金|高温合金")),
    ("Sapphire", _compiled(r"\bsapphire\b|蓝宝石|\bAl2O3\b|\balumina\b|氧化铝")),
    ("SiC", _compiled(r"\bSiC(p)?\b|silicon carbide|碳化硅")),
    ("Silicon", _compiled(r"\bsilicon\b|silicon wafer|si wafer|\bsi substrate\b|单晶硅|硅片")),
    ("Steel", _compiled(r"\bsteel\b|stainless steel|\bQ345B\b|\bX100\b|不锈钢|\b钢\b")),
    ("TBC", _compiled(r"thermal barrier|热障涂层|陶瓷热障")),
    ("Ti6Al4V", _compiled(r"\bTi[- ]?6Al[- ]?4V\b|\bTC4\b|titanium alloy|钛合金")),
    ("ZrO2", _compiled(r"\bZrO2\b|\bzirconia\b|\bYSZ\b|yttria[- ]?stabilized zirconia|氧化锆")),
)

# ---- 工艺候选模式 ----
PROCESS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("laser_induced_etching", _compiled(r"laser induced deep etching|\bLIDE\b|激光诱导深蚀刻")),
    ("wet_etching", _compiled(r"wet etch(?:ing)?|湿法刻蚀|湿法蚀刻|化学刻蚀")),
    ("surface_texturing", _compiled(r"surface textur(?:ing|e)|表面织构|表面微结构|织构化")),
    ("micromachining", _compiled(r"micromachin(?:ing|e)|微加工|微制造")),
    ("scribing", _compiled(r"scribing|internal scribing|划线|刻划|划切")),
    ("drilling", _compiled(r"\bdrill(?:ing|ed|s)\b|percussion drill|钻孔|打孔")),
    ("cutting", _compiled(r"\bcut(?:ting)?\b|laser cut|切割|划切")),
    ("milling", _compiled(r"\bmill(?:ing)?\b|铣削|微铣削")),
    ("ablation", _compiled(r"\bablati(?:on|ve)\b|烧蚀")),
    ("bonding", _compiled(r"\bbond(?:ing)?\b|adhesive bond|adhesive|胶接|粘接|胶粘")),
    ("cleaning", _compiled(r"\bclean(?:ing)?\b|清洗|清洁")),
    ("polishing", _compiled(r"\bpolish(?:ing)?\b|抛光")),
    ("non_laser_reference", _compiled(r"mechanical drill(?:ing)?|sandblast|electrochemical discharge|\bDRIE\b|ultrasonic testing|plasma etch|\bNDE\b|机械钻孔|喷砂|超声检测|等离子刻蚀")),
)

# ---- 加工对象/几何模式 ----
GEOMETRY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("circular_hole", _compiled(r"through[- ]?hole|through glass via|\bTGV\b|micro[- ]?hole|\bholes?\b|圆孔|通孔|微孔|孔洞")),
    ("rectangular_groove", _compiled(r"\bgrooves?\b|rectangular groove|沟槽|矩形槽")),
    ("single_line", _compiled(r"single line|单线|划线")),
    ("surface_texture", _compiled(r"surface texture|microstructure|表面织构|微结构")),
    ("lens", _compiled(r"\blens(?:es)?\b|\bCRL\b|refractive lens|透镜")),
    ("wafer", _compiled(r"\bwafer(s)?\b|\bpanel(s)?\b|玻璃晶圆|晶圆")),
    ("plate", _compiled(r"\bplate(s)?\b|板材|钢板")),
    ("sheet", _compiled(r"\bsheet(s)?\b|glass sheet|薄片|片材")),
    ("film", _compiled(r"\bfilm(s)?\b|薄膜")),
)

# ---- 激光体制 ----
LASER_TYPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("fs", _compiled(r"\bfemtosecond\b|\bfs\b|飞秒")),
    ("ps", _compiled(r"\bpicosecond\b|\bps\b|皮秒")),
    ("ns", _compiled(r"\bnanosecond\b|\bns\b|纳秒")),
    ("uv", _compiled(r"\bUV\b|\bultraviolet\b|紫外")),
)

# ---- 数值/牌号证据 ----
WAVELENGTH_RE = re.compile(r"\b([1-9]\d{2,3})\s*(?:nm|纳米)\b")
PULSE_WIDTH_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(fs|ps|ns)\b")

GRADE_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("CFRP", (re.compile(r"\bT300\b|\bT700\b|\bT800\b"),)),
    ("Steel", (re.compile(r"\bQ345B\b|\bX100\b|\bQ235\b"),)),
    ("NickelSuperalloy", (re.compile(r"\bGH\d{4}\b|\bInconel\s?718\b|\bInconel\s?625\b"),)),
    ("Ti6Al4V", (re.compile(r"\bTC4\b"),)),
)

# ---- LLM 输出与 raw text 的工艺 canonical 归一 ----
PROCESS_ALIASES: dict[str, str] = {
    "cutting": "cutting",
    "cut": "cutting",
    "laser cutting": "cutting",
    "切割": "cutting",
    "scribing": "scribing",
    "internal scribing": "scribing",
    "划线": "scribing",
    "drilling": "drilling",
    "laser drilling": "drilling",
    "percussion drilling": "drilling",
    "drill": "drilling",
    "钻孔": "drilling",
    "milling": "milling",
    "铣削": "milling",
    "ablation": "ablation",
    "laser ablation": "ablation",
    "烧蚀": "ablation",
    "micromachining": "micromachining",
    "micromachining process": "micromachining",
    "微加工": "micromachining",
    "laser induced deep etching": "laser_induced_etching",
    "lide": "laser_induced_etching",
    "laser induced etching": "laser_induced_etching",
    "wet etching": "wet_etching",
    "wet etch": "wet_etching",
    "etching": "wet_etching",
    "湿法刻蚀": "wet_etching",
    "bonding": "bonding",
    "adhesive bonding": "bonding",
    "gluing": "bonding",
    "胶接": "bonding",
    "粘接": "bonding",
    "surface texturing": "surface_texturing",
    "texturing": "surface_texturing",
    "表面织构": "surface_texturing",
    "cleaning": "cleaning",
    "清洗": "cleaning",
    "polishing": "polishing",
    "抛光": "polishing",
    "mechanical drilling": "non_laser_reference",
    "sandblasting": "non_laser_reference",
    "sandblasting erosion": "non_laser_reference",
    "ecdm": "non_laser_reference",
    "deep reactive ion etching": "non_laser_reference",
    "drie": "non_laser_reference",
    "plasma etching": "non_laser_reference",
    "ultrasonic testing": "non_laser_reference",
    "non-laser": "non_laser_reference",
    "ndoe": "non_laser_reference",
}

LASER_ALIASES: dict[str, str] = {
    "fs": "fs",
    "femtosecond": "fs",
    "femtosecond laser": "fs",
    "飞秒": "fs",
    "飞秒激光": "fs",
    "ps": "ps",
    "picosecond": "ps",
    "picosecond laser": "ps",
    "皮秒": "ps",
    "皮秒激光": "ps",
    "ns": "ns",
    "nanosecond": "ns",
    "nanosecond laser": "ns",
    "纳秒": "ns",
    "纳秒激光": "ns",
    "uv": "uv",
    "ultraviolet": "uv",
    "紫外": "uv",
    "ultrafast": "",
    "超快": "",
}
