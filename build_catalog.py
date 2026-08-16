#!/usr/bin/env python3
"""Extract regulator catalog from Targaz Product List.pdf into catalog.json."""
import json
import re

import pymupdf

doc = pymupdf.open("Targaz Product List.pdf")
PIN_COLS = [0.5, 1, 2, 4, 6, 10, 12, 16, 19]
FRG_PINS = [0.5, 1, 2, 3, 4, 5]
CNG_PINS = [25, 50, 100, 150, 200]


def page_items(page):
    items = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for line in b.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text:
                continue
            x0, y0, x1, y1 = line["bbox"]
            items.append({"t": text, "x": x0, "y": y0, "x1": x1, "y1": y1})
    return items


def parse_price(s):
    if "ASK" in s.upper():
        return None
    m = re.search(r"([\d.]+)\s*€", s)
    if not m:
        return None
    raw = m.group(1)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
        return float(raw.replace(".", ""))
    return float(raw.replace(",", "."))


def parse_weight(s):
    m = re.search(r"([\d,]+)\s*kg", s, re.I)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def pout_to_mbar(s):
    s = s.lower().strip()
    m = re.match(r"([\d,]+)\s*mbar", s)
    if m:
        return float(m.group(1).replace(",", "."))
    m = re.match(r"([\d,]+)\s*bar", s)
    if m:
        return float(m.group(1).replace(",", ".")) * 1000
    return None


def parse_cap(s):
    s = s.strip()
    if s in ("-", "–"):
        return None
    s = s.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        return float(s.replace(".", ""))
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def connection_from_text(t):
    u = t.upper()
    if "FLANGE" in u or "FLANŞ" in u:
        return "flanged"
    if "THREAD" in u or "DİŞ" in u or "NPT" in u:
        return "threaded"
    return None


def fill_price_weight_forward(rows):
    last_w = last_p = None
    last_model = None
    for r in rows:
        key = (r["model"], r.get("connection"))
        if key != last_model:
            last_w = last_p = None
            last_model = key
        if r.get("weightKg") is not None:
            last_w = r["weightKg"]
        else:
            r["weightKg"] = last_w
        if r.get("priceEur") is not None:
            last_p = r["priceEur"]
        else:
            r["priceEur"] = last_p
    last_w = last_p = None
    last_model = None
    for r in reversed(rows):
        key = (r["model"], r.get("connection"))
        if key != last_model:
            last_w = last_p = None
            last_model = key
        if r.get("weightKg") is not None:
            last_w = r["weightKg"]
        else:
            r["weightKg"] = last_w
        if r.get("priceEur") is not None:
            last_p = r["priceEur"]
        else:
            r["priceEur"] = last_p


def extract_caka_hp():
    catalog = []
    for pi in range(5, 10):
        items = page_items(doc[pi])
        models = [it for it in items if re.match(r"^CAKA\s+\d+", it["t"])]
        skus = [it for it in items if re.match(r"^MM\.08\.\d+\.Y\d+", it["t"])]
        rows = []
        for sku_it in skus:
            model_it = max(
                (m for m in models if m["y"] < sku_it["y"] - 5),
                key=lambda m: m["y"],
                default=None,
            )
            if not model_it:
                continue
            zone = [it for it in items if model_it["y"] - 5 < it["y"] < sku_it["y"]]
            conn = None
            dims = None
            dn_in = dn_out = None
            for it in zone:
                c = connection_from_text(it["t"])
                if c:
                    conn = c
                if it["t"].upper() in ("THREADED", "FLANGED"):
                    conn = it["t"].lower()
                if re.search(r"\d+\s*x\s*\d+\s*x\s*\d+", it["t"]):
                    dims = it["t"]
                if "DN" in it["t"].upper():
                    dns = re.findall(r"DN\s*(\d+)", it["t"], re.I)
                    if len(dns) >= 2:
                        dn_in, dn_out = int(dns[0]), int(dns[1])
                    elif len(dns) == 1:
                        dn_in = dn_out = int(dns[0])

            row_items = [it for it in items if abs(it["y"] - sku_it["y"]) < 6]
            pout_label = None
            caps = []
            for it in sorted(row_items, key=lambda z: z["x"]):
                pm = pout_to_mbar(it["t"])
                if pm is not None:
                    pout_label = it["t"]
                elif (it["t"] in ("-", "–") or re.fullmatch(r"\d+", it["t"])) and 200 < it["x"] < 345:
                    caps.append(parse_cap(it["t"]))
            while len(caps) < 9:
                caps.append(None)
            caps = caps[:9]

            weight = price = None
            for it in items:
                if abs(it["y"] - sku_it["y"]) < 22 and it["x"] > 340:
                    if "kg" in it["t"].lower():
                        weight = parse_weight(it["t"])
                    if "€" in it["t"]:
                        price = parse_price(it["t"])

            if dn_in is None:
                m = re.search(r"CAKA\s+(\d+)", model_it["t"])
                if m:
                    dn_in = dn_out = int(m.group(1))

            rows.append(
                {
                    "family": "CAKA",
                    "model": model_it["t"],
                    "sku": sku_it["t"].strip(),
                    "spring": sku_it["t"].split(".")[-1],
                    "connection": conn or "threaded",
                    "dnIn": dn_in,
                    "dnOut": dn_out or dn_in,
                    "maxInletBar": 20,
                    "outletMbar": pout_to_mbar(pout_label) if pout_label else None,
                    "outletLabel": pout_label,
                    "ssv": False,
                    "priceEur": price,
                    "askForPrice": False,
                    "weightKg": weight,
                    "dimensionsMm": dims,
                    "capacityType": "table",
                    "pinCols": PIN_COLS,
                    "capacity": caps,
                    "cg": None,
                }
            )
        fill_price_weight_forward(rows)
        catalog.extend(rows)
    return catalog


def extract_frg_hp():
    catalog = []
    items = page_items(doc[14])
    # DN and commercial data from catalog page (SKU prefix is authoritative)
    meta = {
        "31": {"dn": 25, "model": "FRG-HP 25", "weight": 3.6, "price": 143},
        "32": {"dn": 32, "model": "FRG-HP 32", "weight": 3.6, "price": 414},
        "33": {"dn": 40, "model": "FRG-HP 40", "weight": 3.6, "price": 414},
        "34": {"dn": 50, "model": "FRG-HP 50", "weight": 3.5, "price": 451},
    }
    skus = [it for it in items if re.match(r"^MM\.01\.3\d\.01\.\d+", it["t"])]

    for sku_it in skus:
        sku = sku_it["t"].strip()
        code = sku.split(".")[2]  # 31..34
        m = meta[code]
        row_items = [it for it in items if abs(it["y"] - sku_it["y"]) < 6]
        pout_label = None
        caps = []
        for it in sorted(row_items, key=lambda z: z["x"]):
            pm = pout_to_mbar(it["t"])
            if pm is not None:
                pout_label = it["t"]
            elif (it["t"] in ("-", "–") or re.fullmatch(r"\d+", it["t"])) and 180 < it["x"] < 420:
                caps.append(parse_cap(it["t"]))
        while len(caps) < 6:
            caps.append(None)
        caps = caps[:6]

        catalog.append(
            {
                "family": "FRG-HP",
                "model": m["model"],
                "sku": sku,
                "spring": sku.split(".")[-1],
                "connection": "threaded",
                "dnIn": m["dn"],
                "dnOut": m["dn"],
                "maxInletBar": 5,
                "outletMbar": pout_to_mbar(pout_label) if pout_label else None,
                "outletLabel": pout_label,
                "ssv": False,
                "priceEur": m["price"],
                "askForPrice": False,
                "weightKg": m["weight"],
                "dimensionsMm": None,
                "capacityType": "table",
                "pinCols": FRG_PINS,
                "capacity": caps,
                "cg": None,
            }
        )
    return catalog


def extract_governors():
    catalog = []
    frg_ssv = [
        ("FRG-SSV 15", "MM.01.21.01", 15, 1.7, 71),
        ("FRG-SSV 20", "MM.01.22.01", 20, 1.8, 71),
        ("FRG-SSV 25", "MM.01.23.01", 25, 1.8, 71),
        ("FRG-SSV 32", "MM.01.24.01", 32, 3.6, 143),
        ("FRG-SSV 40", "MM.01.25.01", 40, 3.5, 143),
        ("FRG-SSV 50", "MM.01.26.01", 50, 3.5, 150),
    ]
    heur_ssv = {15: 25, 20: 40, 25: 60, 32: 100, 40: 150, 50: 200}
    for name, sku, dn, w, price in frg_ssv:
        catalog.append(
            {
                "family": "FRG-SSV",
                "model": name,
                "sku": sku,
                "spring": None,
                "connection": "threaded",
                "dnIn": dn,
                "dnOut": dn,
                "maxInletBar": 1,
                "outletMbar": None,
                "outletMinMbar": 21,
                "outletMaxMbar": 300,
                "outletLabel": "21-300 mbar",
                "ssv": True,
                "priceEur": price,
                "askForPrice": False,
                "weightKg": w,
                "dimensionsMm": None,
                "capacityType": "heuristic",
                "heuristicMaxFlow": heur_ssv.get(dn, 100),
                "pinCols": None,
                "capacity": None,
                "cg": None,
            }
        )

    frg = [
        ("FRG 15", "MM.01.21.02", 15, 1.4, 57),
        ("FRG 20", "MM.01.22.02", 20, 1.4, 57),
        ("FRG 25", "MM.01.23.02", 25, 1.4, 57),
        ("FRG 32", "MM.01.24.02", 32, 3.4, 135),
        ("FRG 40", "MM.01.25.02", 40, 3.2, 135),
        ("FRG 50", "MM.01.26.02", 50, 3.2, 143),
        ("FRG 65", "MM.01.51.02", 65, 12.5, 528),
        ("FRG 80", "MM.01.52.02", 80, 11.0, 535),
        ("FRG 100", "MM.01.53.02", 100, 12.0, 614),
    ]
    heur = {
        15: 25,
        20: 40,
        25: 60,
        32: 100,
        40: 150,
        50: 200,
        65: 400,
        80: 600,
        100: 900,
    }
    for name, sku, dn, w, price in frg:
        catalog.append(
            {
                "family": "FRG",
                "model": name,
                "sku": sku,
                "spring": None,
                "connection": "flanged" if dn >= 65 else "threaded",
                "dnIn": dn,
                "dnOut": dn,
                "maxInletBar": 0.5 if dn >= 65 else 1.0,
                "outletMbar": None,
                "outletMinMbar": 21,
                "outletMaxMbar": 300,
                "outletLabel": "21-300 mbar",
                "ssv": False,
                "priceEur": price,
                "askForPrice": False,
                "weightKg": w,
                "dimensionsMm": None,
                "capacityType": "heuristic",
                "heuristicMaxFlow": heur.get(dn, 100),
                "pinCols": None,
                "capacity": None,
                "cg": None,
            }
        )
    return catalog


def extract_cex_csr():
    catalog = []
    rows = [
        ("CEX", "CEX 75", "-", 75, 21, 150, 2.3, 150),
        ("CEX", "CEX 75", "-", 75, 150, 300, 2.3, 150),
        ("CEX", "CEX 100", "-", 100, 21, 150, 2.3, 165),
        ("CEX", "CEX 100", "-", 100, 150, 300, 2.3, 175),
        ("CSR", "CSR 6-25", "-", 25, 21, 150, 1.2, 92),
        ("CSR", "CSR 6-25", "-", 25, 150, 300, 1.2, 92),
        ("CSR", "CSR 50", "-", 50, 21, 150, 1.2, 115),
        ("CSR", "CSR 50", "-", 50, 150, 300, 1.2, 115),
    ]
    for fam, model, sku, cap, omin, omax, w, price in rows:
        catalog.append(
            {
                "family": fam,
                "model": model,
                "sku": sku,
                "spring": None,
                "connection": "threaded",
                "dnIn": None,
                "dnOut": None,
                "maxInletBar": 5,
                "outletMbar": None,
                "outletMinMbar": omin,
                "outletMaxMbar": omax,
                "outletLabel": f"{omin}-{omax} mbar",
                "ssv": False,
                "priceEur": price,
                "askForPrice": False,
                "weightKg": w,
                "dimensionsMm": None,
                "capacityType": "fixed",
                "fixedCapacity": cap,
                "pinCols": None,
                "capacity": None,
                "cg": None,
            }
        )
    return catalog


def extract_caka_pl_xl():
    catalog = []
    pl = [
        ("CAKA 25 PL", "MM.08.14.P00", 25, 50, 450, 20, 3100, "454 x 380 x 345"),
        ("CAKA 40 PL", "MM.08.20.P00", 40, 25, 950, 26, 3400, "454 x 400 x 345"),
        ("CAKA 50 PL", "MM.08.30.P00", 50, 50, 1900, 46, 4000, "454 x 600 x 345"),
        ("CAKA 80 PL", "MM.08.42.P00", 80, 25, 4500, 65, 4800, "454 x 627 x 345"),
        ("CAKA 100 PL", "MM.08.50.P00", 100, 25, 6200, 75, 5000, "570 x 537 x 455"),
    ]
    for model, sku, dn, maxin, cg, w, price, dims in pl:
        catalog.append(
            {
                "family": "CAKA-PL",
                "model": model,
                "sku": sku,
                "spring": None,
                "connection": "flanged",
                "dnIn": dn,
                "dnOut": dn,
                "maxInletBar": maxin,
                "outletMbar": None,
                "outletMinMbar": 20,
                "outletMaxMbar": 4000,
                "outletLabel": "pilot-controlled",
                "ssv": False,
                "priceEur": price,
                "askForPrice": False,
                "weightKg": w,
                "dimensionsMm": dims,
                "capacityType": "cg",
                "cg": cg,
                "pinCols": None,
                "capacity": None,
            }
        )

    def add_axial(family, model_base, cl, maxin, rows):
        for dn, sku, cg, dims, w, price in rows:
            catalog.append(
                {
                    "family": family,
                    "model": f"{model_base} DN{dn} ({cl})",
                    "sku": sku,
                    "spring": None,
                    "connection": "flanged",
                    "dnIn": dn,
                    "dnOut": dn,
                    "maxInletBar": maxin,
                    "outletMbar": None,
                    "outletMinMbar": 20,
                    "outletMaxMbar": 8000,
                    "outletLabel": "axial / pilot",
                    "ssv": False,
                    "priceEur": price,
                    "askForPrice": price is None,
                    "weightKg": w,
                    "dimensionsMm": dims,
                    "capacityType": "cg",
                    "cg": cg,
                    "pinCols": None,
                    "capacity": None,
                    "pressureClass": cl,
                }
            )

    add_axial(
        "CAKA-XL",
        "CAKA XL",
        "CL150",
        25,
        [
            (25, "MM.09.11.P00", 525, "210 x 225", 25, 2640),
            (40, "MM.09.21.P00", 1350, "251 x 365", 45, 2800),
            (50, "MM.09.31.P00", 2200, "286 x 287", 60, 3360),
            (80, "MM.09.41.P00", 5100, "337 x 400", 85, 3760),
            (100, "MM.09.51.P00", 8200, None, 90, None),
            (150, "MM.09.61.P00", 20000, None, None, None),
        ],
    )
    add_axial(
        "CAKA-XL",
        "CAKA XL",
        "CL300-600",
        100,
        [
            (25, "MM.09.11.P00", 525, "210 x 225", 25, 3200),
            (40, "MM.09.21.P00", 1350, "251 x 365", 45, 3600),
            (50, "MM.09.31.P00", 2200, "286 x 287", 60, 4000),
            (80, "MM.09.41.P00", 5100, "337 x 400", 85, 4480),
            (100, "MM.09.51.P00", 8200, None, 90, None),
            (150, "MM.09.61.P00", 20000, None, None, None),
        ],
    )
    add_axial(
        "CAKA-MXL",
        "CAKA MXL",
        "CL150",
        25,
        [
            (25, "MM.09.13.P00", 450, "385 x 225", 50, 5000),
            (40, "MM.09.23.P00", 1150, "450 x 365", 90, 5500),
            (50, "MM.09.33.P00", 1950, "535 x 287", 110, 6500),
            (80, "MM.09.43.P00", 4600, "600 x 400", 150, 7250),
            (100, "MM.09.53.P00", 6900, None, 155, None),
            (150, "MM.09.63.P00", 16500, None, None, None),
        ],
    )
    add_axial(
        "CAKA-MXL",
        "CAKA MXL",
        "CL300-600",
        100,
        [
            (25, "MM.09.13.P00", 450, "385 x 225", 50, 6000),
            (40, "MM.09.23.P00", 1150, "450 x 365", 90, 7000),
            (50, "MM.09.33.P00", 1950, "535 x 287", 110, 7800),
            (80, "MM.09.43.P00", 4600, "600 x 400", 150, 8500),
            (100, "MM.09.53.P00", 6900, None, 155, None),
            (150, "MM.09.63.P00", 16500, None, None, None),
        ],
    )
    add_axial(
        "CAKA-BXL",
        "CAKA BXL",
        "CL150",
        25,
        [
            (25, "MM.09.12.P00", 500, "390 x 225", 50, 3300),
            (40, "MM.09.22.P00", 1100, "440 x 365", 75, 3600),
            (50, "MM.09.32.P00", 1900, "535 x 287", 90, 4200),
            (80, "MM.09.42.P00", 4000, "600 x 400", 130, 4700),
            (100, "MM.09.52.P00", 6500, None, 135, None),
            (150, "MM.09.62.P00", 16000, None, None, None),
        ],
    )
    add_axial(
        "CAKA-BXL",
        "CAKA BXL",
        "CL300-600",
        100,
        [
            (25, "MM.09.12.P00", 500, "390 x 225", 50, 4000),
            (40, "MM.09.22.P00", 1100, "440 x 365", 75, 4500),
            (50, "MM.09.32.P00", 1900, "535 x 287", 90, 5000),
            (80, "MM.09.42.P00", 4000, "600 x 400", 130, 5600),
            (100, "MM.09.52.P00", 6500, None, 135, None),
            (150, "MM.09.62.P00", 16000, None, None, None),
        ],
    )
    return catalog


def extract_cng():
    catalog = []
    cng = [
        ("CNG 15", "MM.12.10.00", 15, [300, 400, 450, 500, 550], 4.0, 750),
        ("CNG 25", "MM.12.20.00", 25, [700, 1000, 1250, 1500, 2000], 9.7, 1050),
        ("CNG 40", "MM.12.30.00", 40, [900, 1300, 1600, 2000, 2600], 9.7, 1500),
    ]
    for model, sku, dn, caps, w, price in cng:
        catalog.append(
            {
                "family": "CNG",
                "model": model,
                "sku": sku,
                "spring": None,
                "connection": "threaded",
                "dnIn": dn,
                "dnOut": dn,
                "maxInletBar": 250,
                "outletMbar": None,
                "outletMinMbar": 5000,
                "outletMaxMbar": 40000,
                "outletLabel": "5-40 bar",
                "ssv": False,
                "priceEur": price,
                "askForPrice": False,
                "weightKg": w,
                "dimensionsMm": None,
                "capacityType": "table",
                "pinCols": CNG_PINS,
                "capacity": caps,
                "cg": None,
                "connectionDetail": "NPT",
            }
        )
    return catalog


def main():
    caka = extract_caka_hp()
    frg_hp = extract_frg_hp()
    gov = extract_governors()
    cex = extract_cex_csr()
    plxl = extract_caka_pl_xl()
    cng = extract_cng()
    all_items = caka + frg_hp + gov + cex + plxl + cng

    # Deduplicate identical model+sku+outlet rows
    seen = set()
    unique = []
    for r in all_items:
        key = (r["family"], r["model"], r["sku"], r.get("outletLabel"), r.get("connection"), r.get("pressureClass"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    print(
        "CAKA",
        len(caka),
        "FRG-HP",
        len(frg_hp),
        "GOV",
        len(gov),
        "CEX/CSR",
        len(cex),
        "PL/XL",
        len(plxl),
        "CNG",
        len(cng),
        "UNIQUE",
        len(unique),
    )
    missing_w = sum(1 for r in unique if r.get("weightKg") is None)
    missing_p = sum(1 for r in unique if r.get("priceEur") is None and not r.get("askForPrice"))
    print("missing weight", missing_w, "missing price (non-ask)", missing_p)
    for r in unique[:5]:
        print(r["model"], r["sku"], r["connection"], r["outletLabel"], r["capacity"][:4] if r.get("capacity") else None, r["weightKg"], r["priceEur"])

    with open("catalog.json", "w", encoding="utf-8") as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)
    print("wrote catalog.json")


if __name__ == "__main__":
    main()
