"""Pure XML parser for TikTok Android UI hierarchies dumped via uiautomator2."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from tiktok_streak.models import ScannedRow

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
STREAK_NUMBER_RE = re.compile(r"(?:🔥|chuỗi|streak)?\s*(\d{1,4})\s*(?:🔥|ngày|days?)?", re.IGNORECASE)

# System notification entries inside TikTok Inbox that are not user DMs
SYSTEM_ROW_NAMES = {
    "new followers",
    "follower mới",
    "người follow mới",
    "activity",
    "hoạt động",
    "hoạt động mới",
    "system notifications",
    "thông báo hệ thống",
    "tiktok",
    "tin nhắn từ tiktok",
    "messages from tiktok",
    "shop",
    "tiktok shop",
}

CAPTCHA_KEYWORDS = (
    "slide to verify",
    "kéo thanh trượt",
    "verify you are human",
    "xác minh bảo mật",
    "verification",
    "captcha",
    "chọn 2 hình",
    "select 2 objects",
    "account suspended",
    "tài khoản bị đình chỉ",
)

LOGIN_REQUIRED_KEYWORDS = (
    "log in to tiktok",
    "đăng nhập vào tiktok",
    "use phone / email / username",
    "sử dụng số điện thoại / email / tên người dùng",
    "enter 6-digit code",
    "enter 4-digit code",
    "nhập mã gồm",
)

SAFE_POPUP_DISMISS_LABELS = (
    "không phải bây giờ",
    "not now",
    "để sau",
    "later",
    "maybe later",
    "bỏ qua",
    "skip",
    "không, cảm ơn",
    "no thanks",
    "không cho phép",
    "don't allow",
    "từ chối",
    "deny",
    "cập nhật sau",
    "update later",
    "tôi đã hiểu",
    "tôi hiểu",
    "got it",
    "đóng",
    "close",
    "dismiss",
)

DIALOG_ONLY_DISMISS_LABELS = (
    "hủy",
    "cancel",
    "không",
    "no",
    "ok",
)

CLOSE_ICON_LABELS = ("×", "✕", "x")

POPUP_CONTEXT_HINTS = (
    "cho phép",
    "allow",
    "cập nhật",
    "update",
    "thêm số điện thoại",
    "add phone",
    "nhập email",
    "danh bạ",
    "contacts",
    "đồng bộ",
    "sync",
    "thông báo",
    "notifications",
    "alertdialog",
    "isn't responding",
    "không phản hồi",
    "khuyến mãi",
    "quà tặng",
)


def parse_bounds(bounds_str: str) -> tuple[int, int, int, int]:
    """Convert Android UI bounds string `[x1,y1][x2,y2]` into an integer tuple."""
    match = BOUNDS_RE.search(bounds_str or "")
    if not match:
        return (0, 0, 0, 0)
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def bounds_center(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    """Return the `(x, y)` center point of a bounding box."""
    x1, y1, x2, y2 = bounds
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def detect_captcha_or_block(xml_text: str) -> str | None:
    """Return matched anomaly keyword if the current screen shows CAPTCHA or account warning."""
    if not xml_text:
        return None
    lowered = xml_text.lower()
    for kw in CAPTCHA_KEYWORDS:
        if kw in lowered:
            return kw
    return None


def detect_login_required(xml_text: str) -> str | None:
    """Return matched keyword if TikTok is asking the user to log in or enter OTP."""
    if not xml_text:
        return None
    lowered = xml_text.lower()
    for kw in LOGIN_REQUIRED_KEYWORDS:
        if kw in lowered:
            return kw
    return None


def find_dismiss_popup_bounds(
    xml_text: str,
) -> tuple[str, tuple[int, int, int, int]] | None:
    """Locate a safe button to close an interrupting popup, permission prompt, or dialog."""
    if not xml_text.strip():
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    # Tier 1: Unambiguous dismiss/skip/later/close labels
    for label in SAFE_POPUP_DISMISS_LABELS:
        bounds = find_node_bounds_by_labels(xml_text, (label,))
        if bounds:
            return (label, bounds)

    # Check small clickable close icons (× / ✕ / X)
    icon_targets = set(CLOSE_ICON_LABELS)
    for elem in root.iter("node"):
        if elem.attrib.get("clickable") != "true":
            continue
        txt = (elem.attrib.get("text") or "").strip().lower()
        desc = (elem.attrib.get("content-desc") or "").strip().lower()
        if txt in icon_targets or desc in icon_targets:
            bounds = parse_bounds(elem.attrib.get("bounds", ""))
            if bounds != (0, 0, 0, 0) and (bounds[2] - bounds[0]) <= 220 and (bounds[3] - bounds[1]) <= 220:
                return (txt or desc, bounds)

    # Tier 2: Generic Cancel/No/OK only when an interrupting prompt/dialog context is visible
    lowered_xml = xml_text.lower()
    has_popup_context = any(hint in lowered_xml for hint in POPUP_CONTEXT_HINTS)
    if has_popup_context:
        for label in DIALOG_ONLY_DISMISS_LABELS:
            bounds = find_node_bounds_by_labels(xml_text, (label,))
            if bounds:
                return (label, bounds)

    return None


def _collect_texts(node: ET.Element) -> list[tuple[str, str, tuple[int, int, int, int]]]:
    """Collect `(text, content_desc, bounds)` from all descendants in document order."""
    items: list[tuple[str, str, tuple[int, int, int, int]]] = []
    for elem in node.iter("node"):
        txt = (elem.attrib.get("text") or "").strip()
        desc = (elem.attrib.get("content-desc") or "").strip()
        if txt or desc:
            items.append((txt, desc, parse_bounds(elem.attrib.get("bounds", ""))))
    return items


def _extract_streak_badge(texts: list[tuple[str, str, tuple[int, int, int, int]]]) -> str:
    """Identify streak count or fire badge from row text/content-desc."""
    for txt, desc, _ in texts:
        combined = f"{txt} {desc}".strip()
        if "🔥" in combined or "streak" in combined.lower() or "chuỗi" in combined.lower():
            m = STREAK_NUMBER_RE.search(combined)
            if m:
                return f"🔥 {m.group(1)}"
            return "🔥"
    return ""


def _is_row_container(elem: ET.Element) -> bool:
    """Check whether an XML node looks like a clickable chat item inside a list."""
    cls = elem.attrib.get("class", "")
    clickable = elem.attrib.get("clickable") == "true"
    x1, y1, x2, y2 = parse_bounds(elem.attrib.get("bounds", ""))
    width = x2 - x1
    height = y2 - y1
    # Chat rows span most of the screen width and have reasonable row height
    return clickable and ("Layout" in cls or "ViewGroup" in cls) and width >= 400 and 80 <= height <= 450


def parse_inbox_conversations(xml_text: str) -> list[ScannedRow]:
    """Parse TikTok Inbox conversation rows from an Android UI XML dump."""
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    results: list[ScannedRow] = []
    seen_names: set[str] = set()

    # Prefer iterating list containers (RecyclerView / ListView) if present, else scan root
    list_containers = [
        el
        for el in root.iter("node")
        if el.attrib.get("class", "").endswith(("RecyclerView", "ListView"))
    ]
    search_roots = list_containers if list_containers else [root]

    for container in search_roots:
        # Check direct children first when scanning RecyclerView, or all clickable row containers
        candidates = list(container) if list_containers else list(container.iter("node"))
        for elem in candidates:
            if not list_containers and not _is_row_container(elem):
                continue
            bounds = parse_bounds(elem.attrib.get("bounds", ""))
            x1, y1, x2, y2 = bounds
            if (x2 - x1) < 350 or (y2 - y1) < 70 or (y2 - y1) > 480:
                continue

            texts = _collect_texts(elem)
            visible_strings = [t for t, _, _ in texts if t]
            if not visible_strings:
                continue

            display_name = visible_strings[0]
            if display_name in seen_names:
                continue
            seen_names.add(display_name)

            # Skip obvious header/tab labels
            if display_name.lower() in {"inbox", "hộp thư", "messages", "tin nhắn", "search", "tìm kiếm"}:
                continue

            streak_info = _extract_streak_badge(texts)
            preview_parts = [
                s for s in visible_strings[1:] if s != streak_info and "🔥" not in s
            ]
            last_preview = " · ".join(preview_parts[:2])
            is_system = display_name.lower() in SYSTEM_ROW_NAMES

            results.append(
                ScannedRow(
                    display_name=display_name,
                    last_preview=last_preview,
                    streak_info=streak_info,
                    bounds=bounds,
                    is_system=is_system,
                )
            )

    return results


def find_node_bounds_by_labels(
    xml_text: str,
    labels: tuple[str, ...],
    *,
    class_suffix: str | None = None,
    clickable_only: bool = False,
) -> tuple[int, int, int, int] | None:
    """Find the first UI node matching any text or content-desc (case-insensitive)."""
    if not xml_text.strip():
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    lowered_targets = {lbl.lower() for lbl in labels}
    for elem in root.iter("node"):
        if clickable_only and elem.attrib.get("clickable") != "true":
            continue
        if class_suffix and not elem.attrib.get("class", "").endswith(class_suffix):
            continue
        txt = (elem.attrib.get("text") or "").strip().lower()
        desc = (elem.attrib.get("content-desc") or "").strip().lower()
        if txt in lowered_targets or desc in lowered_targets:
            bounds = parse_bounds(elem.attrib.get("bounds", ""))
            if bounds != (0, 0, 0, 0):
                return bounds
    return None


def find_chat_input_bounds(xml_text: str) -> tuple[int, int, int, int] | None:
    """Locate the message EditText box inside a TikTok DM screen."""
    if not xml_text.strip():
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    # TikTok DM input is an EditText near the bottom of the screen
    edit_candidates: list[tuple[int, tuple[int, int, int, int]]] = []
    for elem in root.iter("node"):
        if elem.attrib.get("class", "").endswith("EditText"):
            bounds = parse_bounds(elem.attrib.get("bounds", ""))
            if bounds != (0, 0, 0, 0):
                edit_candidates.append((bounds[1], bounds))

    if not edit_candidates:
        return None
    edit_candidates.sort(key=lambda item: item[0], reverse=True)
    return edit_candidates[0][1]
