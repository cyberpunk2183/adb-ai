"""The screen as text: what is on it, and where, from ``uiautomator dump``.

A screenshot makes an agent find a button by looking at pixels and guessing
its coordinates. The view hierarchy already knows: every element's text, its
content description, whether it can be clicked, and its exact bounds. Reading
that is faster than looking at a picture and lands taps where they belong.

It cannot see everything. Games, video, maps and anything else drawn straight
onto a surface show up as one big element with nothing in it - that is what
screenshots and live view are still for.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from . import actions, adb

_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_DUMP_PATH = "/sdcard/adbai-ui.xml"


@dataclass(frozen=True)
class Element:
    text: str
    desc: str
    rid: str
    cls: str
    clickable: bool
    bounds: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def label(self) -> str:
        return self.text or self.desc

    def as_dict(self) -> dict[str, object]:
        item: dict[str, object] = {}
        if self.text:
            item["text"] = self.text
        if self.desc and self.desc != self.text:
            item["desc"] = self.desc
        if self.rid:
            # "com.app:id/save" -> "save": the package says nothing new.
            item["id"] = self.rid.split("/", 1)[-1]
        item["class"] = self.cls.rsplit(".", 1)[-1]
        item["center"] = list(self.center)
        if self.clickable:
            item["clickable"] = True
        return item


def dump_xml(serial: str | None = None) -> str:
    """The raw hierarchy as XML.

    ``uiautomator dump /dev/tty`` streams it with no temporary file, but not
    every device allows that; the fallback writes to /sdcard and reads it back.
    """
    out = adb.run(["exec-out", "uiautomator", "dump", "/dev/tty"], serial=serial,
                  timeout=30.0, check=False).stdout
    start = out.find("<?xml")
    end = out.rfind("</hierarchy>")
    if start >= 0 and end > start:
        return out[start:end + len("</hierarchy>")]

    result = adb.shell(f"uiautomator dump {_DUMP_PATH} >/dev/null 2>&1; cat {_DUMP_PATH}; "
                       f"rm -f {_DUMP_PATH}", serial=serial, timeout=30.0)
    start = result.find("<?xml")
    end = result.rfind("</hierarchy>")
    if start < 0 or end < start:
        detail = result.strip()[:200] or "no output"
        raise adb.AdbError(
            "could not read the screen's layout (uiautomator dump): " + detail +
            "\nSome screens refuse it - secure ones, or while an animation runs. "
            "Try again, or fall back to a screenshot."
        )
    return result[start:end + len("</hierarchy>")]


def parse(xml_text: str) -> list[Element]:
    """Every element worth knowing about, in screen order.

    Kept: anything with text or a description, and anything clickable. Layout
    containers with neither are what make a dump unreadable, and an agent has
    nothing to do with them.
    """
    root = ET.fromstring(xml_text)
    found: list[Element] = []
    for node in root.iter("node"):
        attrs = node.attrib
        match = _BOUNDS.match(attrs.get("bounds", ""))
        if not match:
            continue
        x1, y1, x2, y2 = (int(v) for v in match.groups())
        if x2 <= x1 or y2 <= y1:
            continue  # off screen or collapsed
        text = attrs.get("text", "").strip()
        desc = attrs.get("content-desc", "").strip()
        clickable = attrs.get("clickable") == "true" or attrs.get("long-clickable") == "true"
        if not (text or desc or clickable):
            continue
        found.append(Element(
            text=text, desc=desc, rid=attrs.get("resource-id", ""),
            cls=attrs.get("class", ""), clickable=clickable, bounds=(x1, y1, x2, y2),
        ))
    return found


def elements(serial: str | None = None) -> list[Element]:
    return parse(dump_xml(serial))


def _fold(value: str) -> str:
    return " ".join(value.casefold().split())


def find(items: list[Element], query: str) -> list[Element]:
    """Elements matching ``query``, best first.

    Exact text beats exact description beats a substring; among equals, a
    clickable element beats one that is not, since that is usually the one a
    tap was meant for.
    """
    want = _fold(query)
    if not want:
        return []
    ranked: list[tuple[int, int, Element]] = []
    for position, item in enumerate(items):
        text, desc, rid = _fold(item.text), _fold(item.desc), _fold(item.rid)
        if text == want:
            score = 0
        elif desc == want:
            score = 1
        elif rid.endswith("/" + want):
            score = 2
        elif want in text:
            score = 3
        elif want in desc:
            score = 4
        else:
            continue
        ranked.append((score * 2 + (0 if item.clickable else 1), position, item))
    ranked.sort(key=lambda entry: entry[:2])
    return [item for _, _, item in ranked]


def tap_text(query: str, serial: str | None = None, index: int = 0) -> str:
    """Tap the element whose text or description matches, by its real centre."""
    items = elements(serial)
    matches = find(items, query)
    if not matches:
        labels = [item.label for item in items if item.label][:25]
        listing = ", ".join(repr(label) for label in labels) or "no text on screen"
        raise LookupError(f"nothing on screen matches {query!r}. On screen: {listing}")
    if index >= len(matches):
        raise LookupError(f"only {len(matches)} match(es) for {query!r}, not index {index}")
    chosen = matches[index]
    x, y = chosen.center
    actions.tap(x, y, serial=serial)
    extra = f" ({len(matches)} matches, took #{index})" if len(matches) > 1 else ""
    return f"tapped {chosen.label!r} at {x},{y}{extra}"
