# SPDX-License-Identifier: GPL-2.0-or-later
"""Helpers that turn QGIS XML (QDomElement) into plain, JSON-ready data.

Used where QGIS exposes settings only through XML (labeling, raster renderers, renderer
attributes). Values stay strings, exactly as QGIS writes them.
"""

MAX_DEPTH = 8


def _children(el):
    nodes = el.childNodes()
    for i in range(nodes.count()):
        child = nodes.at(i).toElement()
        if not child.isNull():
            yield child


def attributes(el):
    attrs = el.attributes()
    return {attrs.item(i).toAttr().name(): attrs.item(i).toAttr().value() for i in range(attrs.count())}


def option_value(el, depth=0):
    """Decode QGIS's <Option type="Map|List|..."> serialisation into dict/list/str."""
    kind = el.attribute("type")
    if depth > MAX_DEPTH:
        return None
    if kind == "Map":
        return {c.attribute("name"): option_value(c, depth + 1) for c in _children(el) if c.tagName() == "Option"}
    if kind in ("List", "StringList"):
        return [option_value(c, depth + 1) for c in _children(el) if c.tagName() == "Option"]
    if kind == "invalid" or not el.hasAttribute("value"):
        return None
    return el.attribute("value")


def flatten(el, prefix="", skip=(), depth=0, out=None):
    """Flatten an element's attributes into {"child.grandchild.attr": value}.

    <Option> trees are decoded and stored under their path; tags in `skip` are ignored.
    """
    out = {} if out is None else out
    if depth > MAX_DEPTH:
        return out
    for name, value in attributes(el).items():
        out[f"{prefix}{name}"] = value
    seen = {}
    for child in _children(el):
        tag = child.tagName()
        if tag in skip:
            continue
        if tag == "Option":
            out[f"{prefix}{child.attribute('name') or 'options'}"] = option_value(child)
            continue
        seen[tag] = seen.get(tag, 0) + 1
        key = tag if seen[tag] == 1 else f"{tag}[{seen[tag]}]"
        flatten(child, f"{prefix}{key}.", skip, depth + 1, out)
    return out


def active_data_defined(option_map):
    """From a decoded dd_properties Option map, keep only active properties."""
    props = (option_map or {}).get("properties") or {}
    out = []
    for name, spec in sorted(props.items()):
        if not isinstance(spec, dict) or str(spec.get("active", "")).lower() not in ("true", "1"):
            continue
        out.append({
            "name": name,
            "type": spec.get("type"),
            "expression": spec.get("expression") or None,
            "field": spec.get("field") or None,
            "value": spec.get("val") or None,
        })
    return out


def _redact_embedded_xml(value, depth):
    """Redact XML held in an attribute value. Returns (value, Counter); unparsable text is
    scanned as plain text instead, so a secret is never skipped."""
    from collections import Counter

    from qgis.PyQt.QtXml import QDomDocument

    from .redact import redact_text

    doc = QDomDocument()
    result = doc.setContent(value)
    ok = result[0] if isinstance(result, tuple) else bool(result)
    if not ok:
        return redact_text(value)
    kinds = Counter(redact_dom(doc, depth + 1))
    if not kinds:
        return value, kinds
    return doc.toString(-1), kinds


def _list_items(el):
    out, children = [], el.childNodes()
    for i in range(children.count()):
        c = children.at(i).toElement()
        if not c.isNull():
            out.append(c)
    return out


def _item_value(item):
    return item.attribute("value") if item.hasAttribute("value") else item.text()


def _set_item_value(item, value):
    if item.hasAttribute("value"):
        item.setAttribute("value", value)
        return
    children = item.childNodes()
    for i in reversed(range(children.count())):
        item.removeChild(children.at(i))
    item.appendChild(item.ownerDocument().createTextNode(value))


def _redact_variable_lists(el):
    """Variables (project, layer, layout) are stored as two parallel lists, variableNames and
    variableValues, so a value never sits next to its name. Pair them and hide a value whose
    variable name suggests a secret, as the semantic collector does. Returns a Counter."""
    from collections import Counter

    from .redact import PLACEHOLDER, redact_named_value

    kinds = Counter()
    lists = {
        c.attribute("name"): c for c in _list_items(el) if c.attribute("name") in ("variableNames", "variableValues")
    }
    if len(lists) != 2:
        return kinds
    names = [_item_value(c) for c in _list_items(lists["variableNames"])]
    for i, item in enumerate(_list_items(lists["variableValues"])):
        name = names[i] if i < len(names) else ""
        red, sub = redact_named_value(name, _item_value(item))
        if sub:
            _set_item_value(item, PLACEHOLDER.format(kind=red["redacted"]) if isinstance(red, dict) else red)
            kinds.update(sub)
    return kinds


def redact_dom(node, depth=0):
    """Redact credentials in a QGIS XML document in place. Returns a Counter of kinds.

    Structural, never textual: running the URI redactor over raw XML would read attributes
    such as a symbol layer's pass="0" as a password and corrupt the file. Here
    - text content (datasource URIs, expressions) gets the URI redactor;
    - attribute VALUES are scanned, attribute names never act as keys;
    - <Option name="password" value="..."> style entries are hidden by name;
    - variables (parallel variableNames / variableValues lists) are hidden by variable name.
    """
    from collections import Counter

    from .redact import PLACEHOLDER, redact_text, secret_name_kind, sensitive_kind

    kinds = Counter()
    if depth > 64:
        return kinds
    el_self = node.toElement()
    if not el_self.isNull():
        kinds.update(_redact_variable_lists(el_self))
    children = node.childNodes()
    for i in range(children.count()):
        child = children.at(i)
        if child.isText() or child.isCDATASection():
            data = child.toCharacterData()
            red, sub = redact_text(data.data())
            if sub:
                data.setData(red)
                kinds.update(sub)
            continue
        el = child.toElement()
        if el.isNull():
            continue
        name_attr = el.attribute("name")
        kind = (sensitive_kind(name_attr) or secret_name_kind(name_attr)) if name_attr else None
        attrs = el.attributes()
        for j in range(attrs.count()):
            attr = attrs.item(j).toAttr()
            value = attr.value()
            if not value:
                continue
            if kind and attr.name() == "value":
                attr.setValue(PLACEHOLDER.format(kind=kind))
                kinds[kind] += 1
            elif value.lstrip().startswith("<"):
                # An attribute holding serialised XML (a label's lineSymbol, a text_format):
                # redact it structurally too. The text redactor would read pass="0" inside it
                # as a password. The value is rewritten only when something was redacted, so
                # clean values stay byte-identical.
                red, sub = _redact_embedded_xml(value, depth)
                if sub:
                    attr.setValue(red)
                    kinds.update(sub)
            elif any(c in value for c in "=@:%"):
                red, sub = redact_text(value)
                if sub:
                    attr.setValue(red)
                    kinds.update(sub)
        kinds.update(redact_dom(el, depth + 1))
    return kinds
