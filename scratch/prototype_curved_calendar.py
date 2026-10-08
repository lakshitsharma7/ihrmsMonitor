import os
import sys
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen

app = QApplication.instance() or QApplication(sys.argv)

class CurvedCalendarCard(QFrame):
    """Container with lavender sidebar on left and a sweeping white circular curve on right."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CurvedCalendarCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(440)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        if rect.width() <= 0 or rect.height() <= 0:
            return

        # 1. Base outer rounded rect (light lavender)
        outer_path = QPainterPath()
        outer_path.addRoundedRect(rect, 24, 24)
        painter.fillPath(outer_path, QColor("#F4F2FA"))

        # Clip so white arc stays inside rounded corners
        painter.setClipPath(outer_path)

        # 2. Sweeping curved white body for the right calendar area
        w = rect.width()
        h = rect.height()
        split_x = 175.0
        curve_apex_x = 110.0

        white_path = QPainterPath()
        white_path.moveTo(w, 0)
        white_path.lineTo(split_x + 50, 0)
        white_path.cubicTo(
            QPointF(curve_apex_x, h * 0.18),
            QPointF(curve_apex_x, h * 0.82),
            QPointF(split_x + 50, h),
        )
        white_path.lineTo(w, h)
        white_path.closeSubpath()

        painter.fillPath(white_path, QColor("#FFFFFF"))

        # Outer border
        painter.setClipping(False)
        painter.setPen(QPen(QColor("#E5E3F0"), 1))
        painter.drawPath(outer_path)

# Build a test window
test_win = QWidget()
test_win.setStyleSheet("background-color: #F8FAFC;")
test_win.resize(920, 520)

root_layout = QVBoxLayout(test_win)
root_layout.setContentsMargins(20, 20, 20, 20)

card = CurvedCalendarCard(test_win)
card_layout = QHBoxLayout(card)
card_layout.setContentsMargins(0, 0, 0, 0)
card_layout.setSpacing(0)

# Left sidebar
left_side = QWidget(card)
left_side.setFixedWidth(175)
left_layout = QVBoxLayout(left_side)
left_layout.setContentsMargins(24, 24, 12, 24)
left_layout.setSpacing(14)

cal_title = QLabel("Calendar", left_side)
cal_title.setStyleSheet("font-size: 19px; font-weight: 800; color: #1E1B4B; border: none; background: transparent;")
left_layout.addWidget(cal_title)

# Year row
year_row = QHBoxLayout()
year_row.setSpacing(8)
year_prev = QPushButton("‹", left_side)
year_prev.setStyleSheet("border: none; background: transparent; font-size: 16px; font-weight: 700; color: #4338CA; max-width: 16px;")
year_prev.setCursor(Qt.CursorShape.PointingHandCursor)
year_lbl = QLabel("2026", left_side)
year_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #1E1B4B; border: none; background: transparent;")
year_next = QPushButton("›", left_side)
year_next.setStyleSheet("border: none; background: transparent; font-size: 16px; font-weight: 700; color: #4338CA; max-width: 16px;")
year_next.setCursor(Qt.CursorShape.PointingHandCursor)
year_row.addWidget(year_prev)
year_row.addWidget(year_lbl)
year_row.addWidget(year_next)
year_row.addStretch(1)
left_layout.addLayout(year_row)

left_layout.addSpacing(10)

# Months
months = [
    ("August", "#94A3B8", 13, 500),
    ("September", "#94A3B8", 13, 500),
    ("October", "#1E1B4B", 16, 800),
    ("November", "#CBD5E1", 13, 500),
    ("December", "#CBD5E1", 13, 500),
]
for m_name, col, sz, wt in months:
    btn = QPushButton(m_name, left_side)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ border: none; background: transparent; color: {col}; "
        f"font-size: {sz}px; font-weight: {wt}; text-align: left; padding: 3px 0; }}"
        f"QPushButton:hover {{ color: #4F46E5; }}"
    )
    left_layout.addWidget(btn)

left_layout.addStretch(1)
card_layout.addWidget(left_side)

# Right calendar
right_side = QWidget(card)
right_layout = QVBoxLayout(right_side)
right_layout.setContentsMargins(30, 22, 24, 20)
right_layout.setSpacing(12)

# Top row: date + nav
top_row = QHBoxLayout()
date_lbl = QLabel("Oct 08, Thu", right_side)
date_lbl.setStyleSheet("font-size: 20px; font-weight: 800; color: #1E1B4B; border: none; background: transparent;")
top_row.addWidget(date_lbl)
top_row.addStretch(1)

nav_box = QHBoxLayout()
nav_box.setSpacing(6)
for arrow in ["‹", "›"]:
    ab = QPushButton(arrow, right_side)
    ab.setCursor(Qt.CursorShape.PointingHandCursor)
    ab.setFixedSize(28, 28)
    ab.setStyleSheet(
        "QPushButton { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 14px; "
        "color: #334155; font-size: 13px; font-weight: 700; } "
        "QPushButton:hover { background: #EEF2FF; border-color: #818CF8; color: #4F46E5; }"
    )
    nav_box.addWidget(ab)
top_row.addLayout(nav_box)
right_layout.addLayout(top_row)

# Weekday headers
wd_row = QHBoxLayout()
wd_row.setSpacing(4)
for wd in ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]:
    hdr = QLabel(wd, right_side)
    hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hdr.setFixedWidth(52)
    hdr.setStyleSheet("color: #4F46E5; font-size: 11px; font-weight: 800; letter-spacing: 0.8px; border: none; background: transparent;")
    wd_row.addWidget(hdr)
wd_row.addStretch(1)
right_layout.addLayout(wd_row)

# Sample grid with compact cells
grid_wrap = QWidget(right_side)
grid = QGridLayout(grid_wrap)
grid.setContentsMargins(0, 0, 0, 0)
grid.setSpacing(4)

# Create 5 rows x 7 cols
for r in range(5):
    for c in range(7):
        day_num = r * 7 + c - 3
        cell = QFrame()
        cell.setFixedSize(52, 50)
        cl = QVBoxLayout(cell)
        cl.setContentsMargins(2, 4, 2, 4)
        cl.setSpacing(2)
        cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        if day_num < 1:
            lbl = QLabel(str(30 + day_num))
            lbl.setStyleSheet("color: #CBD5E1; font-size: 13px; font-weight: 600; border: none; background: transparent;")
            cl.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
            cell.setStyleSheet("background: transparent; border: none;")
        elif day_num > 31:
            lbl = QLabel(str(day_num - 31))
            lbl.setStyleSheet("color: #CBD5E1; font-size: 13px; font-weight: 600; border: none; background: transparent;")
            cl.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
            cell.setStyleSheet("background: transparent; border: none;")
        else:
            lbl = QLabel(f"{day_num:02d}")
            dot = QLabel()
            dot.setFixedSize(6, 6)
            
            if day_num == 8: # Today
                lbl.setStyleSheet("background: #4F46E5; color: #FFFFFF; font-size: 12px; font-weight: 800; border-radius: 12px; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                dot.setStyleSheet("background: #16A34A; border-radius: 3px;")
                cell.setStyleSheet("background: #F0FDF4; border: 1.5px solid #2563EB; border-radius: 12px;")
            elif day_num == 25: # Selected
                lbl.setStyleSheet("background: #3B82F6; color: #FFFFFF; font-size: 12px; font-weight: 800; border-radius: 12px; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px;")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                dot.setStyleSheet("background: #16A34A; border-radius: 3px;")
                cell.setStyleSheet("background: #EFF6FF; border: 2px solid #3B82F6; border-radius: 12px;")
            elif day_num in (5, 12, 19, 26): # Absent
                lbl.setStyleSheet("color: #1E293B; font-size: 13px; font-weight: 700; border: none; background: transparent;")
                dot.setStyleSheet("background: #EF4444; border-radius: 3px;")
                cell.setStyleSheet("background: #FEF2F2; border: 1px solid #FECACA; border-radius: 12px;")
            elif day_num in (6, 7, 13, 14, 20, 21, 27, 28): # Week off
                lbl.setStyleSheet("color: #1E293B; font-size: 13px; font-weight: 700; border: none; background: transparent;")
                dot.setStyleSheet("background: #7C3AED; border-radius: 3px;")
                cell.setStyleSheet("background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 12px;")
            else: # Present
                lbl.setStyleSheet("color: #1E293B; font-size: 13px; font-weight: 700; border: none; background: transparent;")
                dot.setStyleSheet("background: #16A34A; border-radius: 3px;")
                cell.setStyleSheet("background: #F0FDF4; border: 1px solid #86EFAC; border-radius: 12px;")
            
            cl.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(dot, alignment=Qt.AlignmentFlag.AlignCenter)
        
        grid.addWidget(cell, r, c)

right_layout.addWidget(grid_wrap)

# Summary / Legend
leg_row = QHBoxLayout()
leg_row.setSpacing(12)
summary_note = QLabel("Monthly Attendance · 23 Working Days · 18 Present")
summary_note.setStyleSheet("font-size: 11px; font-weight: 600; color: #64748B; border: none; background: transparent;")
leg_row.addWidget(summary_note)
leg_row.addStretch(1)
for lbl_t, col in [("Present", "#16A34A"), ("Absent", "#EF4444"), ("Week Off", "#7C3AED")]:
    dt = QLabel(f"<span style='color:{col}; font-size:12px;'>●</span> <span style='color:#64748B; font-size:10.5px;'>{lbl_t}</span>")
    dt.setStyleSheet("border: none; background: transparent;")
    leg_row.addWidget(dt)

right_layout.addLayout(leg_row)
card_layout.addWidget(right_side)
root_layout.addWidget(card)

test_win.show()
app.processEvents()

out_path = r"C:\Users\Dell\.gemini\antigravity-ide\brain\bebd6e1c-f684-4fd4-8acc-1c68cd8d7722\scratch\prototype_curved_calendar_test.png"
pix = test_win.grab()
pix.save(out_path)
print("Saved prototype to", out_path)
