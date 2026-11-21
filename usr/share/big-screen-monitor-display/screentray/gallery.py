# -*- coding: utf-8 -*-
"""
Janela Flutuante (Flyout / Galeria Visual) para seleção de temas e ajustes rápidos.
"""

import os
from pathlib import Path
from typing import Callable, Optional

try:
    from .qt import (
        QWidget, QFrame, QLabel, QPushButton, QSlider, QVBoxLayout,
        QHBoxLayout, QGridLayout, QScrollArea, QPixmap, QIcon, QColor,
        Qt, pyqtSignal, ALIGN_CENTER, ALIGN_LEFT, ORIENT_HORIZ,
        SMOOTH_PIXMAP
    )
    from .config import THEMES, THUMBNAILS_DIR
    from .i18n import tr
except ImportError:
    from qt import (
        QWidget, QFrame, QLabel, QPushButton, QSlider, QVBoxLayout,
        QHBoxLayout, QGridLayout, QScrollArea, QPixmap, QIcon, QColor,
        Qt, pyqtSignal, ALIGN_CENTER, ALIGN_LEFT, ORIENT_HORIZ,
        SMOOTH_PIXMAP
    )
    from config import THEMES, THUMBNAILS_DIR
    from i18n import tr


class ThemeCard(QFrame):
    """Card individual com miniatura, título e clique para aplicar."""
    clicked = pyqtSignal(str, str)  # theme_id, scheme_id

    def __init__(self, theme_data: dict, current_theme: str, current_scheme: str, parent=None):
        super().__init__(parent)
        self.theme_id = theme_data["id"]
        self.scheme_id = theme_data.get("schemes", [("", "")])[0][0] if theme_data.get("schemes") else ""

        # Verifica se é o tema ativo
        self.is_active = (current_theme == self.theme_id)
        if self.is_active and self.theme_id == "standard":
            # Para o standard, confere se o scheme bate
            current_scheme_check = current_scheme or "cyberpunk"
            # Se for do card principal, selecionamos o esquema padrão
            self.scheme_id = current_scheme_check

        self.setFixedSize(166, 154)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Imagem de miniatura
        self.img_lbl = QLabel()
        self.img_lbl.setFixedSize(152, 94)
        self.img_lbl.setScaledContents(True)
        self.img_lbl.setStyleSheet("border-radius: 4px; border: 1px solid #30363d;")

        thumb_name = theme_data.get("thumb", "theme-standard-cyberpunk.png")
        thumb_path = THUMBNAILS_DIR / thumb_name
        if thumb_path.exists():
            pm = QPixmap(str(thumb_path)).scaled(
                152, 94, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            self.img_lbl.setPixmap(pm)
        else:
            pm = QPixmap(152, 94)
            pm.fill(QColor(33, 38, 45))
            self.img_lbl.setPixmap(pm)

        layout.addWidget(self.img_lbl)

        # Título
        self.title_lbl = QLabel()
        if self.is_active:
            self.title_lbl.setText(f"✓ <b>{theme_data['name']}</b>")
            self.title_lbl.setStyleSheet("color: #58a6ff; font-size: 11px;")
        else:
            self.title_lbl.setText(f"<b>{theme_data['name']}</b>")
            self.title_lbl.setStyleSheet("color: #e6edf3; font-size: 11px;")
        self.title_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.title_lbl)

        # Descrição curta
        desc = theme_data.get("desc", "")
        if len(desc) > 34:
            desc = desc[:31] + "..."
        self.desc_lbl = QLabel(desc)
        self.desc_lbl.setStyleSheet("color: #8b949e; font-size: 10px;")
        layout.addWidget(self.desc_lbl)

    def update_style(self):
        if self.is_active:
            self.setStyleSheet("""
                ThemeCard {
                    background-color: #1f2937;
                    border: 2px solid #58a6ff;
                    border-radius: 8px;
                }
                ThemeCard:hover {
                    background-color: #243245;
                }
            """)
        else:
            self.setStyleSheet("""
                ThemeCard {
                    background-color: #21262d;
                    border: 1px solid #30363d;
                    border-radius: 8px;
                }
                ThemeCard:hover {
                    background-color: #2b333e;
                    border: 1px solid #58a6ff;
                }
            """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.theme_id, self.scheme_id)
        super().mousePressEvent(event)


class ScreenGalleryWindow(QWidget):
    """Janela Pop-up flutuante contendo os cards de temas e controles rápidos."""

    theme_changed = pyqtSignal(str, str)  # theme_id, scheme_id
    brightness_changed = pyqtSignal(int)
    rotate_requested = pyqtSignal()
    toggle_black_screen = pyqtSignal()
    open_settings_requested = pyqtSignal()
    restart_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Galeria de Temas — Monitor 3.5\"")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(580, 640)

        self.current_theme = "standard"
        self.current_scheme = "cyberpunk"
        self.current_brightness = 100
        self.current_orientation = "horizontal"
        self.is_black_screen = False

        self.init_ui()

    def init_ui(self):
        # Frame de fundo estilo cartão escuro
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        bg_frame = QFrame()
        bg_frame.setStyleSheet("""
            QFrame#bgFrame {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 12px;
            }
        """)
        bg_frame.setObjectName("bgFrame")

        card_layout = QVBoxLayout(bg_frame)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        # Header: Título e Botão Fechar
        header_row = QHBoxLayout()
        header_lbl = QLabel(f"<b>{tr('app_name')}</b>  •  <span style='color: #3fb950;'>● {tr('connected')}</span>")
        header_lbl.setTextFormat(Qt.TextFormat.RichText)
        header_lbl.setStyleSheet("font-size: 14px; color: #f0f6fc;")
        header_row.addWidget(header_lbl)

        header_row.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #8b949e;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                color: #f85149;
            }
        """)
        close_btn.clicked.connect(self.hide)
        header_row.addWidget(close_btn)
        card_layout.addLayout(header_row)

        # Sub-barra com informações e Slider de Brilho
        top_bar = QFrame()
        top_bar.setStyleSheet("background-color: #21262d; border-radius: 8px; padding: 4px;")
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(10, 4, 10, 4)

        info_lbl = QLabel("Turing 3.5\" (480x320) • USB ACM")
        info_lbl.setStyleSheet("color: #8b949e; font-size: 12px;")
        tb_layout.addWidget(info_lbl)
        tb_layout.addStretch()

        b_lbl = QLabel(f"{tr('brightness')}:")
        b_lbl.setStyleSheet("color: #e6edf3; font-size: 12px;")
        tb_layout.addWidget(b_lbl)

        self.slider = QSlider(ORIENT_HORIZ)
        self.slider.setRange(10, 100)
        self.slider.setValue(100)
        self.slider.setFixedWidth(100)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #30363d;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #58a6ff;
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
        """)
        self.slider.valueChanged.connect(self._on_slider_changed)
        tb_layout.addWidget(self.slider)

        self.b_val_lbl = QLabel("100%")
        self.b_val_lbl.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 12px;")
        tb_layout.addWidget(self.b_val_lbl)

        card_layout.addWidget(top_bar)

        # Título da Seção de Temas
        sec_lbl = QLabel(f"🎨 <b>{tr('choose_theme')}</b>")
        sec_lbl.setTextFormat(Qt.TextFormat.RichText)
        sec_lbl.setStyleSheet("font-size: 13px; color: #f0f6fc; margin-top: 4px;")
        card_layout.addWidget(sec_lbl)

        # Área de Rolagem com Grid de Cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #161b22;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #30363d;
                min-height: 20px;
                border-radius: 4px;
            }
        """)

        grid_widget = QWidget()
        grid_widget.setStyleSheet("background-color: transparent;")
        self.grid_layout = QGridLayout(grid_widget)
        self.grid_layout.setContentsMargins(2, 2, 2, 2)
        self.grid_layout.setSpacing(10)

        self.cards = []
        self._populate_cards()

        scroll.setWidget(grid_widget)
        card_layout.addWidget(scroll)

        # Rodapé com Botões de Ação Rápida
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.btn_rotate = QPushButton(tr("rotate"))
        self.btn_rotate.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 12px;
                color: #c9d1d9;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
        """)
        self.btn_rotate.clicked.connect(self.rotate_requested.emit)
        footer.addWidget(self.btn_rotate)

        self.btn_black = QPushButton(tr("black_screen"))
        self.btn_black.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 12px;
                color: #c9d1d9;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
        """)
        self.btn_black.clicked.connect(self._toggle_black)
        footer.addWidget(self.btn_black)

        self.btn_restart = QPushButton("Reiniciar")
        self.btn_restart.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 10px;
                color: #c9d1d9;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
        """)
        self.btn_restart.clicked.connect(self.restart_requested.emit)
        footer.addWidget(self.btn_restart)

        footer.addStretch()

        self.btn_cfg = QPushButton(f"⚙ {tr('settings')}")
        self.btn_cfg.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                border: 1px solid #2ea043;
                border-radius: 6px;
                padding: 6px 14px;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
        """)
        self.btn_cfg.clicked.connect(self.open_settings_requested.emit)
        footer.addWidget(self.btn_cfg)

        card_layout.addLayout(footer)

        main_layout.addWidget(bg_frame)

    def _populate_cards(self):
        # Limpa layout anterior se houver
        for card in self.cards:
            self.grid_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()

        # Cria os cards com base nos dados
        # Inclui variações populares do Standard (Cyberpunk, Dark, Neon) e os demais temas
        gallery_items = [
            {"id": "standard", "name": "Standard (Cyberpunk)", "desc": "Dashboard Neon (Ciano/Amarelo)", "thumb": "theme-standard-cyberpunk.png", "scheme": "cyberpunk"},
            {"id": "standard", "name": "Standard (Dark)", "desc": "Preto Clássico com Telemetria", "thumb": "theme-standard-dark.png", "scheme": "dark"},
            {"id": "standard", "name": "Standard (Neon)", "desc": "Ciano & Roxo Estilizado", "thumb": "theme-standard-neon.png", "scheme": "neon"},
            {"id": "kojiro", "name": "Kojiro", "desc": "Wallpaper com Widgets Livres", "thumb": "kojiro-cyberpunk.png", "scheme": "cyberpunk"},
            {"id": "planet", "name": "Planet", "desc": "Terra Orbital em Tempo Real", "thumb": "theme-planet.png", "scheme": ""},
            {"id": "brother_away", "name": "Brother Away", "desc": "Ilha Pixel Art Animada", "thumb": "ba-coconut-away.png", "scheme": ""},
            {"id": "old_computer", "name": "Old Computer", "desc": "Visual Retrô Windows 95", "thumb": "theme-old_computer.png", "scheme": "classic"},
            {"id": "gkrellm", "name": "GKrellM", "desc": "Linux Clássico Modular", "thumb": "theme-gkrellm.png", "scheme": ""},
            {"id": "big_media_player", "name": "Big Media Player", "desc": "Player de Música Retrô", "thumb": "bmp-bigamp.png", "scheme": ""},
        ]

        for idx, item in enumerate(gallery_items):
            row = idx // 3
            col = idx % 3
            card = ThemeCard(item, self.current_theme, self.current_scheme, self)
            card.clicked.connect(self._on_card_clicked)
            self.grid_layout.addWidget(card, row, col)
            self.cards.append(card)

    def _on_card_clicked(self, theme_id: str, scheme_id: str):
        self.current_theme = theme_id
        if scheme_id:
            self.current_scheme = scheme_id
        self._populate_cards()
        self.theme_changed.emit(theme_id, scheme_id)

    def _on_slider_changed(self, value: int):
        self.b_val_lbl.setText(f"{value}%")
        self.brightness_changed.emit(value)

    def _toggle_black(self):
        self.is_black_screen = not self.is_black_screen
        if self.is_black_screen:
            self.btn_black.setText(tr("wake_screen"))
            self.btn_black.setStyleSheet("""
                QPushButton {
                    background-color: #8957e5;
                    border: 1px solid #a371f7;
                    border-radius: 6px;
                    padding: 6px 12px;
                    color: white;
                    font-size: 12px;
                    font-weight: bold;
                }
            """)
        else:
            self.btn_black.setText(tr("black_screen"))
            self.btn_black.setStyleSheet("""
                QPushButton {
                    background-color: #21262d;
                    border: 1px solid #30363d;
                    border-radius: 6px;
                    padding: 6px 12px;
                    color: #c9d1d9;
                    font-size: 12px;
                }
            """)
        self.toggle_black_screen.emit()

    def update_state(self, theme: str, scheme: str, brightness: int, orientation: str):
        self.current_theme = theme
        self.current_scheme = scheme
        self.current_brightness = brightness
        self.current_orientation = orientation
        self.slider.blockSignals(True)
        self.slider.setValue(brightness)
        self.slider.blockSignals(False)
        self.b_val_lbl.setText(f"{brightness}%")
        self._populate_cards()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        super().keyPressEvent(event)
