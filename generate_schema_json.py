#!/usr/bin/env python3
"""
Generate initial Attributes.json and Classes.json for PartClassifier.

Run once to bootstrap the JSON schema files, then edit them directly.
After running, the JSON files become the source of truth.

Usage:
    python generate_schema_json.py
"""

import json
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "input"


def _build_attributes() -> list[dict]:
    """Build the 46-attribute dictionary."""
    attrs = [
        ("23990", "Inner Diameter", "ID", ["id", "i.d.", "bore diameter", "bore", "hole diameter", "hole size", "inside diameter"], ["mm", "inches"], None, None),
        ("23991", "Outer Diameter", "OD", ["od", "o.d.", "outside diameter", "outer dia"], ["mm", "inches"], None, None),
        ("23992", "Thickness", "THK", ["thk", "thickness range", "overall thickness"], ["mm", "inches"], None, None),
        ("23993", "Material", "MAT", ["material type", "alloy", "body material", "material - body"], None, None, ["StainlessSteel", "CarbonSteel", "AlloySteel", "Brass", "Aluminum", "Nylon", "Copper", "Titanium", "Plastic", "Rubber"]),
        ("23994", "Finish", "FIN", ["coating", "surface finish", "plating", "surface treatment"], None, None, ["Plain", "ZincPlated", "BlackOxide", "Anodized", "Chromate", "Passivated", "Galvanized", "NickelPlated"]),
        ("23995", "Standard", "STD", ["specifications met", "specs met", "specification", "spec", "norm"], None, None, None),
        ("23996", "Screw Size", "SS", ["for screw size", "thread size", "thread", "nominal thread size", "bolt size", "fastener size", "screw/bolt size"], None, None, None),
        ("23997", "Hardness", "HRD", ["hardness rating"], ["HRC", "HRB", "HV"], None, None),
        ("23998", "System of Measurement", "SOM", ["measurement system", "unit system"], None, None, ["Metric", "Inch", "Imperial"]),
        ("23999", "RoHS", "RHS", ["rohs compliant", "rohs compliance"], None, None, ["Compliant", "NonCompliant", "Exempt"]),
        ("24000", "REACH", "RCH", ["reach compliant", "reach compliance"], None, None, ["Compliant", "NonCompliant"]),
        ("24001", "Performance", "PRF", ["corrosion resistance"], None, None, None),
        ("24002", "Washer Type", "WT", ["type", "head type", "head style"], None, None, None),
        ("24003", "Length", "LEN", ["overall length", "stroke", "stroke length"], ["mm", "inches"], None, None),
        ("24004", "Width", "WID", [], ["mm", "inches"], None, None),
        ("24005", "Height", "HGT", [], ["mm", "inches"], None, None),
        ("24006", "Head Diameter", "HD", ["head dia"], ["mm", "inches"], None, None),
        ("24007", "Head Height", "HH", ["head thickness"], ["mm", "inches"], None, None),
        ("24008", "Thread Pitch", "TP", ["thread pitch - metric", "threads per inch"], ["mm", "TPI"], None, None),
        ("24009", "Drive Type", "DT", ["drive style", "socket type"], None, None, ["Hex", "Phillips", "Torx", "Slotted", "HexSocket"]),
        ("24010", "Grade", "GRD", ["class", "strength grade", "property class"], None, None, None),
        ("24011", "Point Type", "PT", ["point style", "tip type"], None, None, None),
        ("24012", "Nut Type", "NT", ["nut style"], None, None, None),
        ("24013", "Width Across Flats", "WAF", ["wrench size", "af", "s dimension"], ["mm", "inches"], None, None),
        ("24014", "Diameter", "DIA", ["pin diameter", "shaft diameter"], ["mm", "inches"], None, None),
        ("24015", "Speed Rating", "SPD", ["max speed", "limiting speed", "reference speed"], ["rpm"], None, None),
        ("24016", "Dynamic Load Rating", "DLR", ["dynamic load", "basic dynamic load"], ["N", "kN"], None, None),
        ("24017", "Static Load Rating", "SLR", ["static load", "basic static load"], ["N", "kN"], None, None),
        ("24018", "Tolerance", "TOL", ["tolerance class", "accuracy"], None, None, None),
        ("24019", "Voltage", "VLT", ["rated voltage", "supply voltage", "operating voltage"], ["V", "VDC", "VAC"], None, None),
        ("24020", "Current", "CUR", ["rated current", "max current", "current rating"], ["A", "mA"], None, None),
        ("24021", "Power", "PWR", ["power consumption", "wattage"], ["W", "mW"], None, None),
        ("24022", "Resistance", "RES", ["contact resistance", "insulation resistance"], ["ohm", "kohm", "Mohm"], None, None),
        ("24023", "Temperature", "TMP", ["operating temperature", "temperature range", "max temperature"], ["C", "F"], None, None),
        ("24024", "Response Time", "RT", ["switching frequency", "response frequency"], ["ms", "Hz"], None, None),
        ("24025", "Sensing Distance", "SD", ["detection range", "sensing range", "detecting distance"], ["mm"], None, None),
        ("24026", "Output Type", "OUT", ["output", "output configuration", "npn", "pnp"], None, None, None),
        ("24027", "Protection Rating", "IP", ["ip rating", "ingress protection", "ip67", "ip68"], None, None, None),
        ("24028", "Number of Contacts", "NOC", ["number of positions", "number of pins", "pin count", "contacts"], None, None, None),
        ("24029", "Contact Material", "CM", ["contact plating", "contact finish"], None, None, None),
        ("24030", "Pitch", "PCH", ["pin pitch", "contact pitch", "spacing"], ["mm"], None, None),
        ("24031", "Port Size", "PS", ["connection size", "pipe size"], None, None, None),
        ("24032", "Pressure", "PRS", ["operating pressure", "rated pressure", "working pressure", "max pressure"], ["bar", "psi", "kPa"], None, None),
        ("24033", "Flow Rate", "FR", ["flow", "cv value", "conductance"], None, None, None),
        ("24034", "Micron Rating", "MR", ["filtration rating", "pore size", "removal rating"], ["um", "micron"], None, None),
        ("24035", "Weight", "WGT", ["mass", "net weight"], ["g", "kg", "lb"], None, None),
    ]

    result = []
    for aid, name, shortname, aliases, uom, rng, lov in attrs:
        result.append({
            "id": aid,
            "name": name,
            "shortname": shortname,
            "aliases": aliases,
            "unitOfMeasure": uom,
            "range": rng,
            "lov": lov,
            "keyLOVID": f"LOV_{aid}" if lov else None,
        })
    return result


def _cls(id_: str, name: str, aliases: list[str], attrs: list[str], children: list[dict]) -> dict:
    """Helper to build a class node."""
    return {
        "id": id_,
        "classid": id_,
        "name": name,
        "aliases": aliases,
        "attributeslist": attrs,
        "children": children,
    }


# Common root attrs: material, finish, standard, system_of_measurement, rohs, reach, performance
_ROOT_ATTRS = ["23993", "23994", "23995", "23998", "23999", "24000", "24001"]


def _build_classes() -> list[dict]:
    """Build the 81-class hierarchical tree."""
    return [
        _cls("ICM001", "Mechanical", [], _ROOT_ATTRS, [
            _cls("ICM001001", "Fastener", [], [], [
                _cls("ICM001001001", "Washer", [], ["23990", "23991", "23992", "23996", "24002"], [
                    _cls("ICM001001001001", "Flat Washer", ["flat wshr", "fender washer", "fender"], [], []),
                    _cls("ICM001001001002", "Fender Washer", ["fender wash"], [], []),
                    _cls("ICM001001001003", "Lock Washer", ["lock wshr"], [], [
                        _cls("ICM001001001003001", "Split Lock Washer", ["spt lk", "spring lock washer", "split lock"], ["23997"], []),
                        _cls("ICM001001001003002", "Internal Tooth Lock Washer", ["int tooth"], [], []),
                        _cls("ICM001001001003003", "External Tooth Lock Washer", ["ext tooth"], [], []),
                    ]),
                ]),
                _cls("ICM001001002", "Bolt", [], ["24008", "24006", "24007", "24009", "24010", "24011"], [
                    _cls("ICM001001002001", "Hex Bolt", ["hex cap screw", "hex head bolt"], ["24013"], []),
                    _cls("ICM001001002002", "Carriage Bolt", ["carriage"], [], []),
                    _cls("ICM001001002003", "Eye Bolt", [], [], []),
                ]),
                _cls("ICM001001003", "Screw", [], ["24008", "24006", "24007", "24009", "24010"], [
                    _cls("ICM001001003001", "Cap Screw", [], [], [
                        _cls("ICM001001003001001", "Socket Head Cap Screw", ["shcs", "socket head cap", "socket cap screw"], [], []),
                    ]),
                    _cls("ICM001001003002", "Set Screw", [], ["24011"], []),
                    _cls("ICM001001003003", "Machine Screw", [], [], []),
                ]),
                _cls("ICM001001004", "Nut", [], ["24013", "24012"], [
                    _cls("ICM001001004001", "Hex Nut", [], [], []),
                    _cls("ICM001001004002", "Lock Nut", ["nylon insert", "nyloc"], [], []),
                    _cls("ICM001001004003", "Wing Nut", [], [], []),
                ]),
                _cls("ICM001001005", "Pin", [], ["24014", "24003"], [
                    _cls("ICM001001005001", "Cotter Pin", ["cotter"], [], []),
                    _cls("ICM001001005002", "Dowel Pin", ["dowel"], [], []),
                    _cls("ICM001001005003", "Roll Pin", ["roll pin", "spring pin"], [], []),
                ]),
                _cls("ICM001001006", "Clip", [], [], [
                    _cls("ICM001001006001", "E-Clip", ["e-clip"], [], []),
                    _cls("ICM001001006002", "C-Clip", ["c-clip"], [], []),
                ]),
                _cls("ICM001001007", "Ring", [], [], [
                    _cls("ICM001001007001", "Retaining Ring", ["snap ring", "circlip"], [], []),
                ]),
                _cls("ICM001001008", "Rivet", [], [], [
                    _cls("ICM001001008001", "Blind Rivet", ["pop rivet"], [], []),
                ]),
                _cls("ICM001001009", "Hook", [], [], [
                    _cls("ICM001001009001", "Eye Hook", [], [], []),
                ]),
                _cls("ICM001001010", "Anchor", [], [], []),
                _cls("ICM001001011", "Insert", [], [], []),
                _cls("ICM001001012", "Stud", [], [], []),
                _cls("ICM001001013", "Standoff", [], [], []),
            ]),
            _cls("ICM001002", "Spring", [], ["24003", "24014"], [
                _cls("ICM001002001", "Compression Spring", [], [], []),
            ]),
            _cls("ICM001003", "Seal", [], ["23990", "23991", "23992"], [
                _cls("ICM001003001", "O-Ring", ["oring", "o ring"], [], []),
                _cls("ICM001003002", "Gasket", [], [], []),
            ]),
            _cls("ICM001004", "Fitting", [], ["24031"], [
                _cls("ICM001004001", "Tube Fitting", ["compression fitting"], [], []),
                _cls("ICM001004002", "VCR Fitting", ["vcr fitting"], [], []),
                _cls("ICM001004003", "Pipe Fitting", [], [], []),
            ]),
            _cls("ICM001005", "Bearing", [], ["23990", "23991", "23992", "24015", "24016", "24017", "24018"], [
                _cls("ICM001005001", "Ball Bearing", [], [], [
                    _cls("ICM001005001001", "Deep Groove Ball Bearing", ["dgbb", "deep groove", "radial ball bearing"], [], []),
                    _cls("ICM001005001002", "Angular Contact Bearing", ["angular contact"], [], []),
                ]),
                _cls("ICM001005002", "Needle Bearing", ["needle roller"], [], []),
                _cls("ICM001005003", "Crossed Roller Bearing", ["crossed roller"], [], []),
            ]),
            _cls("ICM001006", "Linear Motion", [], [], [
                _cls("ICM001006001", "Linear Guide", [], [], []),
                _cls("ICM001006002", "Linear Block", ["guide block"], [], []),
                _cls("ICM001006003", "Ball Screw", ["ball screw"], [], []),
            ]),
            _cls("ICM001007", "Bushing", [], [], []),
            _cls("ICM001008", "Spacer", [], [], []),
            _cls("ICM001009", "Bracket", [], [], []),
        ]),
        _cls("ICM002", "Electrical", [], _ROOT_ATTRS, [
            _cls("ICM002001", "Sensor", [], ["24019", "24020", "24023", "24024", "24025", "24026", "24027"], [
                _cls("ICM002001001", "Proximity Sensor", ["inductive sensor"], [], []),
                _cls("ICM002001002", "Photoelectric Sensor", [], [], []),
                _cls("ICM002001003", "Fiber Optic Sensor", ["fiber sensor", "fiber unit"], [], []),
                _cls("ICM002001004", "Laser Sensor", [], [], []),
                _cls("ICM002001005", "Pressure Sensor", ["pressure transducer"], [], []),
            ]),
            _cls("ICM002002", "Connector", [], ["24028", "24029", "24030", "24019", "24020"], [
                _cls("ICM002002001", "Terminal", [], [], []),
                _cls("ICM002002002", "Relay", [], [], []),
            ]),
            _cls("ICM002003", "Timer", [], [], []),
        ]),
        _cls("ICM003", "Vacuum & Semiconductor", [], _ROOT_ATTRS, [
            _cls("ICM003001", "Valve", [], ["24031", "24032"], [
                _cls("ICM003001001", "Solenoid Valve", ["solenoid valve"], [], []),
                _cls("ICM003001002", "Pneumatic Valve", [], [], []),
                _cls("ICM003001003", "Vacuum Valve", [], [], []),
                _cls("ICM003001004", "Gate Valve", [], [], []),
            ]),
            _cls("ICM003002", "Pneumatic", [], ["24031", "24032"], [
                _cls("ICM003002001", "Pneumatic Cylinder", ["air cylinder", "round cylinder", "compact cylinder"], [], []),
                _cls("ICM003002002", "Pressure Regulator", [], [], []),
                _cls("ICM003002003", "Flow Controller", [], [], []),
            ]),
            _cls("ICM003003", "Filter", [], ["24034"], [
                _cls("ICM003003001", "Gas Filter", [], [], []),
                _cls("ICM003003002", "Liquid Filter", [], [], []),
            ]),
            _cls("ICM003004", "Gauge", [], [], [
                _cls("ICM003004001", "Pressure Gauge", [], [], []),
                _cls("ICM003004002", "Vacuum Gauge", [], [], []),
                _cls("ICM003004003", "Mass Flow Controller", [], [], []),
            ]),
            _cls("ICM003005", "Wafer Handling", [], [], [
                _cls("ICM003005001", "Wafer Carrier", [], [], []),
                _cls("ICM003005002", "Wafer Shipper", [], [], []),
            ]),
            _cls("ICM003006", "Vacuum Pump Accessory", [], [], []),
        ]),
    ]


def _count_classes(nodes: list[dict]) -> int:
    """Recursively count classes in the tree."""
    count = 0
    for node in nodes:
        count += 1
        count += _count_classes(node.get("children", []))
    return count


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate Attributes.json
    attributes = _build_attributes()
    attrs_doc = {
        "version": "1.0",
        "description": "Teamcenter-compatible attribute dictionary for PartClassifier",
        "attributes": attributes,
    }
    attrs_path = OUTPUT_DIR / "Attributes.json"
    with open(attrs_path, "w", encoding="utf-8") as f:
        json.dump(attrs_doc, f, indent=2, ensure_ascii=False)

    # Generate Classes.json
    classes = _build_classes()
    classes_doc = {
        "version": "1.0",
        "description": "Teamcenter-compatible hierarchical class tree for PartClassifier",
        "classes": classes,
    }
    classes_path = OUTPUT_DIR / "Classes.json"
    with open(classes_path, "w", encoding="utf-8") as f:
        json.dump(classes_doc, f, indent=2, ensure_ascii=False)

    # Print summary
    num_attrs = len(attributes)
    num_lov = sum(1 for a in attributes if a["lov"])
    num_classes = _count_classes(classes)

    print(f"Generated schema files in {OUTPUT_DIR}/")
    print(f"  Attributes.json: {num_attrs} attributes ({num_lov} with LOV)")
    print(f"  Classes.json:    {num_classes} classes (hierarchical tree)")
    print()
    print("These JSON files are now the source of truth for attr_schema.py.")


if __name__ == "__main__":
    main()
