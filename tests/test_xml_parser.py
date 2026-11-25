"""Unit tests for TikTok Android XML parser."""

from __future__ import annotations

from tiktok_streak.xml_parser import (
    detect_captcha_or_block,
    detect_login_required,
    find_chat_input_bounds,
    find_dismiss_popup_bounds,
    find_node_bounds_by_labels,
    parse_inbox_conversations,
)

SAMPLE_INBOX_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="androidx.recyclerview.widget.RecyclerView" bounds="[0,250][1080,2100]">
      <node class="android.view.ViewGroup" clickable="true" bounds="[0,260][1080,440]">
        <node class="android.widget.TextView" text="Hoạt động mới" bounds="[200,280][700,340]" />
        <node class="android.widget.TextView" text="Ai đó đã thích video của bạn" bounds="[200,350][850,410]" />
      </node>
      <node class="android.view.ViewGroup" clickable="true" bounds="[0,450][1080,640]">
        <node class="android.widget.TextView" text="Linh Chi" bounds="[200,470][650,530]" />
        <node class="android.widget.TextView" text="🔥 28" bounds="[860,470][1020,530]" />
        <node class="android.widget.TextView" text="Bạn đã gửi 1 tin nhắn · 3 giờ" bounds="[200,545][850,605]" />
      </node>
      <node class="android.view.ViewGroup" clickable="true" bounds="[0,650][1080,840]">
        <node class="android.widget.TextView" text="Tuấn Anh" bounds="[200,670][650,730]" />
        <node class="android.widget.TextView" text="Ok nha bro · Hôm qua" bounds="[200,745][850,805]" />
      </node>
    </node>
    <node class="android.widget.TextView" text="Hộp thư" bounds="[650,2220][850,2350]" />
  </node>
</hierarchy>
"""

SAMPLE_CHAT_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.EditText" text="Nhắn tin..." bounds="[120,2150][860,2270]" />
    <node class="android.widget.ImageView" content-desc="Gửi" clickable="true" bounds="[880,2150][1040,2270]" />
  </node>
</hierarchy>
"""


def test_parse_inbox_conversations_extracts_users_and_streaks() -> None:
    rows = parse_inbox_conversations(SAMPLE_INBOX_XML)
    assert len(rows) == 3

    assert rows[0].display_name == "Hoạt động mới"
    assert rows[0].is_system is True

    assert rows[1].display_name == "Linh Chi"
    assert rows[1].is_system is False
    assert rows[1].streak_info == "🔥 28"
    assert "Bạn đã gửi 1 tin nhắn" in rows[1].last_preview

    assert rows[2].display_name == "Tuấn Anh"
    assert rows[2].streak_info == ""
    assert "Ok nha bro" in rows[2].last_preview


def test_find_chat_elements_and_inbox_tab() -> None:
    inbox = find_node_bounds_by_labels(SAMPLE_INBOX_XML, ("Hộp thư", "Inbox"))
    assert inbox == (650, 2220, 850, 2350)

    edit_bounds = find_chat_input_bounds(SAMPLE_CHAT_XML)
    assert edit_bounds == (120, 2150, 860, 2270)

    send_bounds = find_node_bounds_by_labels(SAMPLE_CHAT_XML, ("Gửi", "Send"))
    assert send_bounds == (880, 2150, 1040, 2270)


def test_detect_captcha_or_block() -> None:
    assert detect_captcha_or_block(SAMPLE_INBOX_XML) is None
    captcha_xml = "<hierarchy><node text='Kéo thanh trượt để xác minh' /></hierarchy>"
    assert detect_captcha_or_block(captcha_xml) == "kéo thanh trượt"


def test_find_dismiss_popup_bounds_and_login_guard() -> None:
    # Normal screens should not trigger false popup dismissals
    assert find_dismiss_popup_bounds(SAMPLE_INBOX_XML) is None
    assert find_dismiss_popup_bounds(SAMPLE_CHAT_XML) is None

    # Tier 1 popup (e.g., phone/sync prompt with "Không phải bây giờ")
    popup_xml = """<hierarchy>
      <node class="android.widget.TextView" text="Thêm số điện thoại của bạn" bounds="[100,600][980,700]" />
      <node class="android.widget.EditText" text="Nhập số điện thoại" bounds="[100,720][980,820]" />
      <node class="android.widget.Button" text="Không phải bây giờ" clickable="true" bounds="[100,900][500,1000]" />
    </hierarchy>"""
    found = find_dismiss_popup_bounds(popup_xml)
    assert found is not None
    assert found[0] == "không phải bây giờ"
    assert found[1] == (100, 900, 500, 1000)

    # Small clickable close icon
    icon_popup = """<hierarchy>
      <node class="android.widget.ImageView" content-desc="×" clickable="true" bounds="[920,180][1020,280]" />
    </hierarchy>"""
    found_icon = find_dismiss_popup_bounds(icon_popup)
    assert found_icon is not None
    assert found_icon[1] == (920, 180, 1020, 280)

    # Tier 2 context-aware Cancel
    update_xml = """<hierarchy>
      <node class="android.widget.TextView" text="Cập nhật phiên bản mới" bounds="[100,500][900,600]" />
      <node class="android.widget.Button" text="Hủy" clickable="true" bounds="[100,800][400,900]" />
    </hierarchy>"""
    found_cancel = find_dismiss_popup_bounds(update_xml)
    assert found_cancel is not None
    assert found_cancel[0] == "hủy"

    # Login screen detection
    assert detect_login_required("<hierarchy><node text='Đăng nhập vào TikTok' /></hierarchy>") == "đăng nhập vào tiktok"
