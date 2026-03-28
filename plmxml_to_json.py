#!/usr/bin/env python3
"""
plmxml_to_json.py - Convert Teamcenter PLMXML classification exports to JSON.

Parses PLMXML files containing classification hierarchies (AdminClass),
attributes (ClassificationAttribute), KeyLOVs, and Formats, then outputs
Classes.json and Attributes.json compatible with PartClassifier.

Usage:
    python plmxml_to_json.py --plmxml export.xml
    python plmxml_to_json.py --plmxml export.xml --sml attrs.sml
    python plmxml_to_json.py --plmxml export.xml --output input/
    python plmxml_to_json.py --plmxml export.xml --dry-run
    python plmxml_to_json.py --plmxml export.xml --merge
    python plmxml_to_json.py --demo
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional


class PLMXMLParser:
    """Parse Teamcenter PLMXML classification exports into JSON structures."""

    def __init__(self, plmxml_path: str, sml_path: Optional[str] = None):
        """
        Initialize parser with file paths.

        Args:
            plmxml_path: Path to the PLMXML XML file.
            sml_path: Optional path to an SML file for additional metadata.
        """
        self.plmxml_path = plmxml_path
        self.sml_path = sml_path
        self.root = None
        self.keylovs: dict[str, dict] = {}
        self.formats: dict[str, dict] = {}
        self.attributes: dict[str, dict] = {}
        self.flat_classes: dict[str, dict] = {}

        print(f"[INIT] Loading PLMXML: {plmxml_path}")
        try:
            tree = ET.parse(plmxml_path)
            self.root = tree.getroot()
        except ET.ParseError as e:
            print(f"[ERROR] Malformed XML in {plmxml_path}: {e}")
            sys.exit(1)
        except FileNotFoundError:
            print(f"[ERROR] File not found: {plmxml_path}")
            print("  Usage: python plmxml_to_json.py --plmxml <path_to_plmxml>")
            sys.exit(1)

        self._strip_namespaces(self.root)
        print(f"[INIT] XML loaded, root tag: <{self.root.tag}>")

        if sml_path:
            print(f"[INIT] SML file provided: {sml_path}")

    def _strip_namespaces(self, root: ET.Element) -> None:
        """
        Remove all XML namespace prefixes from tag names for easier matching.

        Transforms tags like '{http://www.plmxml.org/Schemas/PLMXMLSchema}AdminClass'
        into plain 'AdminClass'.

        Args:
            root: The root Element to process recursively.
        """
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]
            # Also strip namespaces from attribute keys
            new_attrib = {}
            for key, val in elem.attrib.items():
                if "}" in key:
                    key = key.split("}", 1)[1]
                new_attrib[key] = val
            elem.attrib = new_attrib

    def _parse_keylovs(self) -> None:
        """
        Find all <KeyLOV> elements and extract id -> values mapping.

        Handles two formats:
        - Legacy: name as XML attribute, <Values><Value>text</Value></Values>
        - DictionaryAttribute style: <Name> child element,
          <Values> with interleaved <Key>/<Value> siblings

        Populates self.keylovs keyed by BOTH the element's id attribute AND
        its keyLOVId attribute so lookups work regardless of which one is
        referenced by FormatKeyLOV.keyLOVId.

        Entry structure:
            { "keyLOVId": "LOV_23991", "name": "Material LOV",
              "values": ["StainlessSteel", "CarbonSteel"] }
        """
        print("[PARSE] Scanning for KeyLOV elements...")
        count = 0
        for lov_elem in self.root.iter("KeyLOV"):
            lov_id = lov_elem.get("id", "")
            lov_key_id = lov_elem.get("keyLOVId", "")

            # Name: prefer child <Name> element, fall back to XML attribute
            name_elem = lov_elem.find("Name")
            if name_elem is not None and name_elem.text:
                lov_name = name_elem.text.strip()
            else:
                lov_name = lov_elem.get("name", "")

            # Values: handle both formats
            values = []
            values_container = lov_elem.find("Values")
            if values_container is not None:
                # New format: interleaved <Key>/<Value> siblings — take Value text
                val_elems = values_container.findall("Value")
                if val_elems:
                    for val_elem in val_elems:
                        if val_elem.text:
                            values.append(val_elem.text.strip())
                else:
                    # Legacy format: <Value>text</Value> only (same tag, covered above)
                    # Key-only fallback: use <Key> text if no <Value> found
                    for key_elem in values_container.findall("Key"):
                        if key_elem.text:
                            values.append(key_elem.text.strip())

            entry = {
                "keyLOVId": lov_key_id,
                "name": lov_name,
                "values": values,
            }

            # Index by element id AND keyLOVId so FormatKeyLOV refs resolve either way
            if lov_id:
                self.keylovs[lov_id] = entry
            if lov_key_id and lov_key_id != lov_id:
                self.keylovs[lov_key_id] = entry

            count += 1

        print(f"[PARSE] Found {count} KeyLOV(s)")

    def _parse_formats(self) -> None:
        """
        Find all <Format> elements and build format_id -> metadata mapping.

        Populates self.formats with structure:
            { "fmt_23990": { "keyLOVRef": "lov_001", "minValue": "0", "maxValue": "100" } }
        """
        print("[PARSE] Scanning for Format elements...")
        count = 0
        for fmt_elem in self.root.iter("Format"):
            fmt_id = fmt_elem.get("id", "")
            lov_ref = fmt_elem.get("keyLOVRef", "")
            # Strip leading '#' from refs
            if lov_ref.startswith("#"):
                lov_ref = lov_ref[1:]

            min_val = fmt_elem.get("minValue")
            max_val = fmt_elem.get("maxValue")

            self.formats[fmt_id] = {
                "keyLOVRef": lov_ref,
                "minValue": min_val,
                "maxValue": max_val,
            }
            count += 1

        print(f"[PARSE] Found {count} Format(s)")

    def _parse_attributes(self) -> None:
        """
        Find classification attribute definitions and build attribute dict.

        Searches for <ClassificationAttribute>, <Attribute>, and <AttributeDefinition>
        tags for version compatibility. For each attribute, resolves formatRef -> Format
        -> KeyLOV chain to get LOV values and ranges.

        Populates self.attributes keyed by attribute id.
        """
        print("[PARSE] Scanning for attribute definitions...")
        count = 0

        tag_names = ["ClassificationAttribute", "Attribute", "AttributeDefinition"]
        seen_ids: set[str] = set()

        for tag in tag_names:
            for attr_elem in self.root.iter(tag):
                attr_id = attr_elem.get("id", "")
                if not attr_id or attr_id in seen_ids:
                    continue
                seen_ids.add(attr_id)

                name = attr_elem.get("name", "")
                short_name = attr_elem.get("shortName", "")
                unit_base = attr_elem.get("unitBase", "")
                format_ref = attr_elem.get("formatRef", "")
                if format_ref.startswith("#"):
                    format_ref = format_ref[1:]

                # Extract description from child element
                desc_elem = attr_elem.find("Description")
                description = ""
                if desc_elem is not None and desc_elem.text:
                    description = desc_elem.text.strip()

                # Resolve format -> LOV and range
                lov_values: list[str] = []
                key_lov_id = ""
                range_info: Optional[dict] = None

                if format_ref and format_ref in self.formats:
                    fmt = self.formats[format_ref]

                    # Range
                    if fmt["minValue"] is not None or fmt["maxValue"] is not None:
                        range_info = {}
                        if fmt["minValue"] is not None:
                            try:
                                range_info["min"] = float(fmt["minValue"])
                                if range_info["min"] == int(range_info["min"]):
                                    range_info["min"] = int(range_info["min"])
                            except ValueError:
                                range_info["min"] = fmt["minValue"]
                        if fmt["maxValue"] is not None:
                            try:
                                range_info["max"] = float(fmt["maxValue"])
                                if range_info["max"] == int(range_info["max"]):
                                    range_info["max"] = int(range_info["max"])
                            except ValueError:
                                range_info["max"] = fmt["maxValue"]

                    # LOV
                    lov_ref = fmt["keyLOVRef"]
                    if lov_ref and lov_ref in self.keylovs:
                        lov_data = self.keylovs[lov_ref]
                        lov_values = lov_data["values"]
                        key_lov_id = lov_data["keyLOVId"]

                units = [unit_base] if unit_base else []

                self.attributes[attr_id] = {
                    "id": attr_id,
                    "name": name,
                    "shortname": short_name,
                    "description": description,
                    "aliases": [],
                    "unitOfMeasure": units,
                    "range": range_info,
                    "lov": lov_values,
                    "keyLOVID": key_lov_id,
                }
                count += 1

        print(f"[PARSE] Found {count} attribute definition(s)")

    def _parse_dictionary_attributes(self) -> None:
        """
        Parse <DictionaryAttribute> elements which embed their LOV inline.

        Structure (after namespace stripping):

            DictionaryAttribute
              Name                       ← attribute display name (child element)
              Format
                FormatKeyLOV             ← keyLOVId attribute → references a KeyLOV section

            ... (separate section, not nested inside DictionaryAttribute) ...

            KeyLOV                       ← keyed by id or keyLOVId
              Name                       ← LOV display name
              Values
                Key                      ← LOV key (code)
                Value                    ← LOV display value
                Key
                Value
                ...

        Populates self.attributes, adding lovName field when present.
        """
        print("[PARSE] Scanning for DictionaryAttribute elements...")
        count = 0

        for attr_elem in self.root.iter("DictionaryAttribute"):
            attr_id = attr_elem.get("id", "")
            if not attr_id or attr_id in self.attributes:
                continue

            # Name is a child element, not an XML attribute
            name_elem = attr_elem.find("Name")
            name = name_elem.text.strip() if name_elem is not None and name_elem.text else attr_elem.get("name", "")
            short_name = attr_elem.get("shortName", "")
            unit_base = attr_elem.get("unitBase", "")

            # keyLOVId comes from Format > FormatKeyLOV attribute;
            # the actual LOV data lives in a separate top-level KeyLOV section.
            lov_values: list[str] = []
            key_lov_id = ""
            lov_name = ""

            fmt_elem = attr_elem.find("Format")
            if fmt_elem is not None:
                fklov_elem = fmt_elem.find("FormatKeyLOV")
                if fklov_elem is not None:
                    key_lov_id = fklov_elem.get("keyLOVId", "")
                    # Resolve against the separately-parsed KeyLOV section
                    if key_lov_id and key_lov_id in self.keylovs:
                        lov_data = self.keylovs[key_lov_id]
                        lov_values = lov_data["values"]
                        lov_name = lov_data["name"]

            self.attributes[attr_id] = {
                "id": attr_id,
                "name": name,
                "shortname": short_name,
                "description": "",
                "aliases": [],
                "unitOfMeasure": [unit_base] if unit_base else [],
                "range": None,
                "lov": lov_values,
                "keyLOVID": key_lov_id,
                "lovName": lov_name,
            }
            count += 1

        print(f"[PARSE] Found {count} DictionaryAttribute(s)")

    def _parse_classes(self) -> None:
        """
        Find all <AdminClass> elements and build a flat dict of classid -> class data.

        Each class entry includes classid, name, parent classid, and list of
        directly assigned attribute IDs.
        """
        print("[PARSE] Scanning for AdminClass elements...")
        count = 0

        for cls_elem in self.root.iter("AdminClass"):
            cls_id = cls_elem.get("classid", "")
            xml_id = cls_elem.get("id", "")
            if not cls_id:
                cls_id = xml_id

            # Name from child element
            name_elem = cls_elem.find("name")
            name = ""
            if name_elem is not None and name_elem.text:
                name = name_elem.text.strip()

            # Parent from child element
            parent_elem = cls_elem.find("parent")
            parent = ""
            if parent_elem is not None and parent_elem.text:
                parent = parent_elem.text.strip()

            # Attribute refs
            attr_list: list[str] = []
            attrs_container = cls_elem.find("attributes")
            if attrs_container is not None:
                for attr_ref_elem in attrs_container.findall("attribute"):
                    ref = attr_ref_elem.get("ref", "")
                    if ref:
                        attr_list.append(ref)

            self.flat_classes[cls_id] = {
                "id": cls_id,
                "classid": cls_id,
                "name": name,
                "parent": parent,
                "aliases": [],
                "attributeslist": attr_list,
            }
            count += 1

        if count == 0:
            print("[WARN] No <AdminClass> elements found. Trying alternative tags...")
            for alt_tag in ["Class", "ClassDefinition", "ClassNode"]:
                for cls_elem in self.root.iter(alt_tag):
                    cls_id = cls_elem.get("classid", cls_elem.get("id", ""))
                    if not cls_id:
                        continue
                    name_elem = cls_elem.find("name")
                    name = name_elem.text.strip() if name_elem is not None and name_elem.text else ""
                    parent_elem = cls_elem.find("parent")
                    parent = parent_elem.text.strip() if parent_elem is not None and parent_elem.text else ""
                    attr_list = []
                    attrs_container = cls_elem.find("attributes")
                    if attrs_container is not None:
                        for attr_ref_elem in attrs_container.findall("attribute"):
                            ref = attr_ref_elem.get("ref", "")
                            if ref:
                                attr_list.append(ref)
                    self.flat_classes[cls_id] = {
                        "id": cls_id,
                        "classid": cls_id,
                        "name": name,
                        "parent": parent,
                        "aliases": [],
                        "attributeslist": attr_list,
                    }
                    count += 1

            if count == 0:
                print("[WARN] No classification classes found in any known tag format.")

        print(f"[PARSE] Found {count} class(es)")

    def _build_tree(self, flat_classes: dict[str, dict]) -> list[dict]:
        """
        Reconstruct the class hierarchy tree from flat parent->classid mappings.

        Root classes are those with no parent or whose parent is not in the dict.

        Args:
            flat_classes: Dict of classid -> class_data with 'parent' field.

        Returns:
            List of root-level class dicts with nested 'children' arrays.
        """
        print("[BUILD] Reconstructing class hierarchy tree...")

        # Group children by parent
        children_map: dict[str, list[str]] = {}
        for cls_id, cls_data in flat_classes.items():
            parent = cls_data.get("parent", "")
            if parent not in children_map:
                children_map[parent] = []
            children_map[parent].append(cls_id)

        def build_node(cls_id: str) -> dict:
            cls = flat_classes[cls_id]
            child_ids = children_map.get(cls_id, [])
            child_ids.sort()
            return {
                "id": cls["id"],
                "classid": cls["classid"],
                "name": cls["name"],
                "aliases": cls["aliases"],
                "attributeslist": cls["attributeslist"],
                "children": [build_node(cid) for cid in child_ids],
            }

        # Find roots: parent is empty or parent not in flat_classes
        roots = []
        for cls_id, cls_data in flat_classes.items():
            parent = cls_data.get("parent", "")
            if not parent or parent not in flat_classes:
                roots.append(cls_id)

        roots.sort()
        tree = [build_node(rid) for rid in roots]

        depth_count = _count_tree_depth(tree)
        print(f"[BUILD] Tree built: {len(roots)} root(s), max depth {depth_count}")
        return tree

    def _merge_sml(self) -> None:
        """
        Parse optional SML file for additional attribute metadata.

        SML files use a simpler XML structure and may provide aliases or LOV
        overrides for attributes already parsed from PLMXML.
        """
        if not self.sml_path:
            return

        print(f"[SML] Parsing SML file: {self.sml_path}")
        try:
            sml_tree = ET.parse(self.sml_path)
            sml_root = sml_tree.getroot()
        except ET.ParseError as e:
            print(f"[WARN] Malformed SML file: {e}")
            return
        except FileNotFoundError:
            print(f"[WARN] SML file not found: {self.sml_path}")
            return

        self._strip_namespaces(sml_root)

        count = 0
        for attr_elem in sml_root.iter("Attribute"):
            attr_id = attr_elem.get("id", "")
            if not attr_id:
                continue

            # If this attribute exists, merge additional metadata
            if attr_id in self.attributes:
                existing = self.attributes[attr_id]

                # Merge aliases
                alias_elem = attr_elem.find("Aliases")
                if alias_elem is not None:
                    for a in alias_elem.findall("Alias"):
                        if a.text and a.text.strip() not in existing["aliases"]:
                            existing["aliases"].append(a.text.strip())

                # LOV override
                lov_elem = attr_elem.find("LOV")
                if lov_elem is not None:
                    vals = []
                    for v in lov_elem.findall("Value"):
                        if v.text:
                            vals.append(v.text.strip())
                    if vals:
                        existing["lov"] = vals

                count += 1
            else:
                # New attribute from SML
                name = attr_elem.get("name", "")
                short_name = attr_elem.get("shortName", "")
                unit = attr_elem.get("unitBase", "")

                aliases = []
                alias_elem = attr_elem.find("Aliases")
                if alias_elem is not None:
                    for a in alias_elem.findall("Alias"):
                        if a.text:
                            aliases.append(a.text.strip())

                lov_values = []
                lov_elem = attr_elem.find("LOV")
                if lov_elem is not None:
                    for v in lov_elem.findall("Value"):
                        if v.text:
                            lov_values.append(v.text.strip())

                self.attributes[attr_id] = {
                    "id": attr_id,
                    "name": name,
                    "shortname": short_name,
                    "description": "",
                    "aliases": aliases,
                    "unitOfMeasure": [unit] if unit else [],
                    "range": None,
                    "lov": lov_values,
                    "keyLOVID": "",
                }
                count += 1

        print(f"[SML] Processed {count} attribute(s) from SML")

    def _validate(self, classes_json: dict, attrs_json: dict) -> None:
        """
        Validate output: warn if class attributeslist references unknown attribute IDs.

        Args:
            classes_json: The assembled classes JSON structure.
            attrs_json: The assembled attributes JSON structure.
        """
        print("[VALIDATE] Checking attribute references...")
        known_attr_ids = {a["id"] for a in attrs_json["attributes"]}
        warnings = 0

        def check_node(node: dict) -> None:
            nonlocal warnings
            for attr_id in node.get("attributeslist", []):
                if attr_id not in known_attr_ids:
                    print(f"  [WARN] Class '{node['name']}' ({node['classid']}) references unknown attribute: {attr_id}")
                    warnings += 1
            for child in node.get("children", []):
                check_node(child)

        for root_node in classes_json.get("tree", []):
            check_node(root_node)

        if warnings:
            print(f"[VALIDATE] {warnings} warning(s) — some attribute refs not found in definitions")
        else:
            print("[VALIDATE] All attribute references valid")

    def parse(self) -> tuple[dict, dict]:
        """
        Orchestrate full parsing pipeline: keylovs -> formats -> attributes -> classes -> tree.

        Returns:
            Tuple of (classes_json, attrs_json) dicts ready for JSON serialization.
        """
        print("\n" + "=" * 60)
        print("  PLMXML -> JSON Conversion")
        print("=" * 60)

        self._parse_keylovs()
        self._parse_formats()
        self._parse_attributes()
        self._parse_dictionary_attributes()
        self._merge_sml()
        self._parse_classes()
        tree = self._build_tree(self.flat_classes)

        source_name = os.path.basename(self.plmxml_path)

        classes_json = {
            "version": "1.0",
            "description": "Generated from Teamcenter PLMXML export",
            "source": source_name,
            "tree": tree,
        }

        # Build attributes list sorted by id
        attrs_list = sorted(self.attributes.values(), key=lambda a: a["id"])
        # Remove internal 'description' field from output if empty, keep structure clean
        clean_attrs = []
        for attr in attrs_list:
            entry: dict[str, Any] = {
                "id": attr["id"],
                "name": attr["name"],
                "shortname": attr["shortname"],
                "aliases": attr["aliases"],
                "unitOfMeasure": attr["unitOfMeasure"],
            }
            if attr["range"] is not None:
                entry["range"] = attr["range"]
            if attr["lov"]:
                entry["lov"] = attr["lov"]
            if attr["keyLOVID"]:
                entry["keyLOVID"] = attr["keyLOVID"]
            if attr.get("lovName"):
                entry["lovName"] = attr["lovName"]
            clean_attrs.append(entry)

        attrs_json = {
            "version": "1.0",
            "description": "Generated from Teamcenter PLMXML export",
            "attributes": clean_attrs,
        }

        self._validate(classes_json, attrs_json)

        total_classes = _count_tree_nodes(tree)
        print(f"\n[DONE] Parsed {total_classes} classes, {len(clean_attrs)} attributes")
        return classes_json, attrs_json


def _count_tree_nodes(tree: list[dict]) -> int:
    """Count total nodes in a nested tree."""
    count = 0
    for node in tree:
        count += 1
        count += _count_tree_nodes(node.get("children", []))
    return count


def _count_tree_depth(tree: list[dict], depth: int = 1) -> int:
    """Return the maximum depth of a nested tree."""
    if not tree:
        return depth - 1
    max_d = depth
    for node in tree:
        child_depth = _count_tree_depth(node.get("children", []), depth + 1)
        if child_depth > max_d:
            max_d = child_depth
    return max_d


def merge_json_files(
    new_classes: dict,
    new_attrs: dict,
    output_dir: str,
) -> tuple[dict, dict]:
    """
    Merge new PLMXML data with existing Classes.json and Attributes.json.

    - New classes: added to tree at correct position.
    - Existing classes: attributeslist updated, existing aliases kept.
    - New attributes: added to list.
    - Existing attributes: LOV/range updated, existing aliases kept.

    Args:
        new_classes: Newly parsed classes JSON.
        new_attrs: Newly parsed attributes JSON.
        output_dir: Directory containing existing JSON files.

    Returns:
        Merged (classes_json, attrs_json).
    """
    classes_path = os.path.join(output_dir, "Classes.json")
    attrs_path = os.path.join(output_dir, "Attributes.json")

    # Load existing or start fresh
    existing_classes: dict = {"version": "1.0", "tree": []}
    existing_attrs: dict = {"version": "1.0", "attributes": []}

    if os.path.exists(classes_path):
        print(f"[MERGE] Loading existing {classes_path}")
        with open(classes_path, "r", encoding="utf-8") as f:
            existing_classes = json.load(f)
    else:
        print(f"[MERGE] No existing Classes.json found, creating new")

    if os.path.exists(attrs_path):
        print(f"[MERGE] Loading existing {attrs_path}")
        with open(attrs_path, "r", encoding="utf-8") as f:
            existing_attrs = json.load(f)
    else:
        print(f"[MERGE] No existing Attributes.json found, creating new")

    # Merge attributes
    existing_attr_map = {a["id"]: a for a in existing_attrs.get("attributes", [])}
    for new_attr in new_attrs.get("attributes", []):
        aid = new_attr["id"]
        if aid in existing_attr_map:
            # Update LOV/range, keep existing aliases
            existing = existing_attr_map[aid]
            if new_attr.get("lov"):
                existing["lov"] = new_attr["lov"]
            if new_attr.get("range"):
                existing["range"] = new_attr["range"]
            if new_attr.get("keyLOVID"):
                existing["keyLOVID"] = new_attr["keyLOVID"]
            # Merge aliases without duplicates
            for alias in new_attr.get("aliases", []):
                if alias not in existing.get("aliases", []):
                    existing.setdefault("aliases", []).append(alias)
        else:
            existing_attr_map[aid] = new_attr

    merged_attrs = deepcopy(existing_attrs)
    merged_attrs["attributes"] = sorted(existing_attr_map.values(), key=lambda a: a["id"])
    merged_attrs["description"] = existing_attrs.get("description", "Merged from Teamcenter PLMXML export")

    # Merge classes - flatten both trees, merge, rebuild
    def flatten_tree(tree: list[dict], parent: str = "") -> dict[str, dict]:
        result = {}
        for node in tree:
            cid = node["classid"]
            result[cid] = {
                "id": node["id"],
                "classid": cid,
                "name": node["name"],
                "aliases": node.get("aliases", []),
                "attributeslist": node.get("attributeslist", []),
                "parent": parent,
            }
            child_flat = flatten_tree(node.get("children", []), cid)
            result.update(child_flat)
        return result

    existing_flat = flatten_tree(existing_classes.get("tree", []))
    new_flat = flatten_tree(new_classes.get("tree", []))

    for cid, new_cls in new_flat.items():
        if cid in existing_flat:
            existing = existing_flat[cid]
            # Update attributeslist (union)
            for attr_id in new_cls["attributeslist"]:
                if attr_id not in existing["attributeslist"]:
                    existing["attributeslist"].append(attr_id)
            # Merge aliases
            for alias in new_cls.get("aliases", []):
                if alias not in existing.get("aliases", []):
                    existing.setdefault("aliases", []).append(alias)
        else:
            existing_flat[cid] = new_cls

    # Rebuild tree
    children_map: dict[str, list[str]] = {}
    for cid, cls in existing_flat.items():
        parent = cls.get("parent", "")
        children_map.setdefault(parent, []).append(cid)

    def build_node(cid: str) -> dict:
        cls = existing_flat[cid]
        child_ids = sorted(children_map.get(cid, []))
        return {
            "id": cls["id"],
            "classid": cls["classid"],
            "name": cls["name"],
            "aliases": cls.get("aliases", []),
            "attributeslist": cls["attributeslist"],
            "children": [build_node(c) for c in child_ids],
        }

    roots = []
    for cid, cls in existing_flat.items():
        parent = cls.get("parent", "")
        if not parent or parent not in existing_flat:
            roots.append(cid)
    roots.sort()

    merged_classes = deepcopy(existing_classes)
    merged_classes["tree"] = [build_node(r) for r in roots]
    merged_classes["description"] = existing_classes.get("description", "Merged from Teamcenter PLMXML export")

    total = _count_tree_nodes(merged_classes["tree"])
    print(f"[MERGE] Result: {total} classes, {len(merged_attrs['attributes'])} attributes")

    return merged_classes, merged_attrs


def generate_demo_plmxml(output_path: str = "sample_plmxml.xml") -> str:
    """
    Generate a sample PLMXML file with realistic classification data for demo/testing.

    Creates:
    - 3 root categories (Mechanical, Electrical, Vacuum)
    - 10 classes total with hierarchy
    - 8 attribute definitions
    - 2 KeyLOVs (Material LOV, Finish LOV)
    - 2 Formats linking attrs to LOVs

    Args:
        output_path: Where to write the sample XML.

    Returns:
        The output_path written.
    """
    xml_content = """\
<?xml version="1.0" encoding="UTF-8"?>
<PLMXML xmlns="http://www.plmxml.org/Schemas/PLMXMLSchema"
        schemaVersion="6.0"
        author="plmxml_to_json.py demo generator">

  <!-- ============ KeyLOVs ============ -->
  <KeyLOV id="lov_mat" keyLOVId="LOV_MATERIAL" name="Material LOV">
    <Values>
      <Value key="1">StainlessSteel</Value>
      <Value key="2">CarbonSteel</Value>
      <Value key="3">Aluminum</Value>
      <Value key="4">Brass</Value>
      <Value key="5">Titanium</Value>
    </Values>
  </KeyLOV>

  <KeyLOV id="lov_fin" keyLOVId="LOV_FINISH" name="Finish LOV">
    <Values>
      <Value key="1">Zinc</Value>
      <Value key="2">BlackOxide</Value>
      <Value key="3">Passivated</Value>
      <Value key="4">Anodized</Value>
    </Values>
  </KeyLOV>

  <!-- ============ Formats ============ -->
  <Format id="fmt_diam" keyLOVRef="#lov_mat" minValue="0" maxValue="500"/>
  <Format id="fmt_hard" keyLOVRef="#lov_fin" minValue="10" maxValue="70"/>

  <!-- ============ Attributes ============ -->
  <ClassificationAttribute id="23990" name="Inner Diameter" shortName="ID" unitBase="mm" formatRef="#fmt_diam">
    <Description>Inner diameter measurement</Description>
  </ClassificationAttribute>

  <ClassificationAttribute id="23991" name="Outer Diameter" shortName="OD" unitBase="mm">
    <Description>Outer diameter measurement</Description>
  </ClassificationAttribute>

  <ClassificationAttribute id="23992" name="Material" shortName="MAT" formatRef="#fmt_diam">
    <Description>Material composition</Description>
  </ClassificationAttribute>

  <ClassificationAttribute id="23993" name="Hardness" shortName="HRC" unitBase="HRC" formatRef="#fmt_hard">
    <Description>Rockwell hardness C scale</Description>
  </ClassificationAttribute>

  <ClassificationAttribute id="23994" name="Voltage Rating" shortName="V" unitBase="V">
    <Description>Maximum operating voltage</Description>
  </ClassificationAttribute>

  <ClassificationAttribute id="23995" name="Thread Size" shortName="THR" unitBase="mm">
    <Description>Thread diameter and pitch</Description>
  </ClassificationAttribute>

  <ClassificationAttribute id="23996" name="Length" shortName="LEN" unitBase="mm">
    <Description>Overall length</Description>
  </ClassificationAttribute>

  <ClassificationAttribute id="23997" name="Vacuum Level" shortName="VAC" unitBase="mbar">
    <Description>Operating vacuum pressure</Description>
  </ClassificationAttribute>

  <!-- ============ Classes (flat, hierarchy via parent) ============ -->

  <!-- Root: Mechanical -->
  <AdminClass id="id_mech" classid="ICM001">
    <name>Mechanical</name>
    <parent></parent>
    <attributes>
      <attribute ref="23992"/>
    </attributes>
  </AdminClass>

  <!-- Mechanical > Fastener -->
  <AdminClass id="id_fast" classid="ICM001001">
    <name>Fastener</name>
    <parent>ICM001</parent>
    <attributes>
      <attribute ref="23992"/>
      <attribute ref="23993"/>
      <attribute ref="23996"/>
    </attributes>
  </AdminClass>

  <!-- Mechanical > Fastener > Bolt -->
  <AdminClass id="id_bolt" classid="ICM001001001">
    <name>Bolt</name>
    <parent>ICM001001</parent>
    <attributes>
      <attribute ref="23995"/>
      <attribute ref="23996"/>
      <attribute ref="23992"/>
    </attributes>
  </AdminClass>

  <!-- Mechanical > Fastener > Washer -->
  <AdminClass id="id_wash" classid="ICM001001002">
    <name>Washer</name>
    <parent>ICM001001</parent>
    <attributes>
      <attribute ref="23990"/>
      <attribute ref="23991"/>
      <attribute ref="23992"/>
    </attributes>
  </AdminClass>

  <!-- Mechanical > Fastener > Washer > Flat Washer -->
  <AdminClass id="id_flat" classid="ICM001001002001">
    <name>Flat Washer</name>
    <parent>ICM001001002</parent>
    <attributes>
      <attribute ref="23990"/>
      <attribute ref="23991"/>
      <attribute ref="23993"/>
    </attributes>
  </AdminClass>

  <!-- Mechanical > Bearing -->
  <AdminClass id="id_bear" classid="ICM001002">
    <name>Bearing</name>
    <parent>ICM001</parent>
    <attributes>
      <attribute ref="23990"/>
      <attribute ref="23991"/>
      <attribute ref="23992"/>
    </attributes>
  </AdminClass>

  <!-- Root: Electrical -->
  <AdminClass id="id_elec" classid="ICM002">
    <name>Electrical</name>
    <parent></parent>
    <attributes>
      <attribute ref="23994"/>
    </attributes>
  </AdminClass>

  <!-- Electrical > Sensor -->
  <AdminClass id="id_sens" classid="ICM002001">
    <name>Sensor</name>
    <parent>ICM002</parent>
    <attributes>
      <attribute ref="23994"/>
      <attribute ref="23992"/>
    </attributes>
  </AdminClass>

  <!-- Electrical > Connector -->
  <AdminClass id="id_conn" classid="ICM002002">
    <name>Connector</name>
    <parent>ICM002</parent>
    <attributes>
      <attribute ref="23994"/>
      <attribute ref="23992"/>
    </attributes>
  </AdminClass>

  <!-- Root: Vacuum -->
  <AdminClass id="id_vacu" classid="ICM003">
    <name>Vacuum</name>
    <parent></parent>
    <attributes>
      <attribute ref="23997"/>
    </attributes>
  </AdminClass>

</PLMXML>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    print(f"[DEMO] Generated sample PLMXML: {output_path}")
    return output_path


def write_json(data: dict, filepath: str) -> None:
    """Write dict as formatted JSON file."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[WRITE] {filepath} ({os.path.getsize(filepath)} bytes)")


def print_summary(classes_json: dict, attrs_json: dict) -> None:
    """Print a human-readable summary of the parsed data."""
    print("\n" + "-" * 60)
    print("  Summary")
    print("-" * 60)

    total = _count_tree_nodes(classes_json.get("tree", []))
    print(f"  Classes:    {total}")
    print(f"  Attributes: {len(attrs_json.get('attributes', []))}")

    def print_tree(nodes: list[dict], indent: int = 0) -> None:
        for node in nodes:
            prefix = "  " + "    " * indent + "|- "
            attr_count = len(node.get("attributeslist", []))
            print(f"{prefix}{node['name']} [{node['classid']}] ({attr_count} attrs)")
            print_tree(node.get("children", []), indent + 1)

    print("\n  Class Hierarchy:")
    print_tree(classes_json.get("tree", []))

    print("\n  Attributes:")
    for attr in attrs_json.get("attributes", []):
        units = ", ".join(attr.get("unitOfMeasure", [])) or "n/a"
        lov_count = len(attr.get("lov", []))
        lov_str = f", {lov_count} LOV values" if lov_count else ""
        range_str = ""
        if attr.get("range"):
            r = attr["range"]
            range_str = f", range [{r.get('min', '?')}-{r.get('max', '?')}]"
        print(f"    {attr['id']:>8s}  {attr['name']:<25s}  unit={units}{range_str}{lov_str}")

    print("-" * 60)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert Teamcenter PLMXML classification exports to JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python plmxml_to_json.py --plmxml export.xml
  python plmxml_to_json.py --plmxml export.xml --sml attrs.sml
  python plmxml_to_json.py --plmxml export.xml --output input/ --merge
  python plmxml_to_json.py --plmxml export.xml --dry-run
  python plmxml_to_json.py --demo
""",
    )

    parser.add_argument("--plmxml", type=str, help="Path to the PLMXML XML file (required unless --demo)")
    parser.add_argument("--sml", type=str, default=None, help="Optional SML file for additional attribute metadata")
    parser.add_argument("--output", type=str, default="output/", help="Output directory for JSON files (default: output/)")
    parser.add_argument("--dry-run", action="store_true", help="Preview parsing results without writing files")
    parser.add_argument("--merge", action="store_true", help="Merge with existing Classes.json and Attributes.json")
    parser.add_argument("--demo", action="store_true", help="Generate sample PLMXML and convert it")

    args = parser.parse_args()

    # Validate args
    if not args.demo and not args.plmxml:
        parser.error("--plmxml is required unless using --demo")

    # Demo mode
    if args.demo:
        sample_path = generate_demo_plmxml("sample_plmxml.xml")
        args.plmxml = sample_path
        if args.output == "output/":
            args.output = "demo_output/"

    # Parse
    p = PLMXMLParser(args.plmxml, sml_path=args.sml)
    classes_json, attrs_json = p.parse()

    # Print summary
    print_summary(classes_json, attrs_json)

    # Merge mode
    if args.merge:
        classes_json, attrs_json = merge_json_files(classes_json, attrs_json, args.output)

    # Write or dry-run
    if args.dry_run:
        print("\n[DRY-RUN] Would write the following files:")
        print(f"  {os.path.join(args.output, 'Classes.json')}")
        print(f"  {os.path.join(args.output, 'Attributes.json')}")
        print("\n[DRY-RUN] Classes.json preview:")
        print(json.dumps(classes_json, indent=2)[:2000])
        print("\n[DRY-RUN] Attributes.json preview:")
        print(json.dumps(attrs_json, indent=2)[:2000])
    else:
        classes_path = os.path.join(args.output, "Classes.json")
        attrs_path = os.path.join(args.output, "Attributes.json")
        write_json(classes_json, classes_path)
        write_json(attrs_json, attrs_path)
        print(f"\n[COMPLETE] Files written to {args.output}")


if __name__ == "__main__":
    main()
