import os
from pathlib import Path
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QLinearGradient, QBrush, QFont, QFontMetrics
from core.FontManager import FontManager
from config.app_config import (
    COMPANY_NAME_UPPER,
    COMPANY_COPYRIGHT,
    LOGO_SPLASH_PATH
)

def create_splash_screen(
    app: QApplication,
    app_name: str | None = None,
    version: str | None = None,
    loading_message: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> QSplashScreen:
    
    # 設定ファイルからデフォルト値を取得
    from config.app_config import (
        SPLASH_APP_NAME,
        SPLASH_VERSION,
        SPLASH_LOADING_MESSAGE,
        SPLASH_WIDTH,
        SPLASH_HEIGHT
    )
    
    app_name = app_name or SPLASH_APP_NAME
    version = version or SPLASH_VERSION
    loading_message = loading_message or SPLASH_LOADING_MESSAGE
    width = width or SPLASH_WIDTH
    height = height or SPLASH_HEIGHT
    
    splash_pixmap = QPixmap(width, height)
    painter = QPainter(splash_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # 1. 背景描画
    bg_gradient = QLinearGradient(0, 0, 0, height)
    bg_gradient.setColorAt(0, QColor("#1A1A1A"))
    bg_gradient.setColorAt(1, QColor("#0D0D0D"))
    painter.fillRect(splash_pixmap.rect(), QBrush(bg_gradient))

    # 2. ブランドライン (左端アクセント)
    painter.fillRect(0, 0, 4, height, QColor("#BB86FC"))

    # 左上にブランドロゴ (BrandLogo.png) を表示
    project_root = Path(__file__).parent.parent.parent
    
    # BrandLogo.pngのパス（gui/splash/内を優先）
    brand_logo_path = Path(__file__).parent / "BrandLogo.png"
    
    # 見つからない場合は他の候補を試す
    if not brand_logo_path.exists():
        brand_logo_candidates = [
            project_root / "assets" / "images" / "BrandLogo.png",
            project_root / "assets" / "BrandLogo.png",
        ]
        for candidate in brand_logo_candidates:
            if candidate.exists():
                brand_logo_path = candidate
                break
    
    if brand_logo_path.exists():
        brand_pixmap = QPixmap(str(brand_logo_path))
        # アイコン的に小さめに配置（高さ40px程度）
        scaled_brand = brand_pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
        # 左上に配置（左マージン40px、上マージン35px）
        painter.drawPixmap(40, 35, scaled_brand)

    # 3. アプリケーション名 (メインタイトル)
    title_font = FontManager.get_font(46, 800)
    title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98)
    painter.setFont(title_font)
    
    available_width = width - 80
    font_metrics = QFontMetrics(title_font)
    text_width = font_metrics.horizontalAdvance(app_name)
    
    if text_width > available_width:
        scale_factor = available_width / text_width * 0.95
        new_size = int(46 * scale_factor)
        title_font = FontManager.get_font(new_size, 800)
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98)
        painter.setFont(title_font)
    
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(QRect(40, 110, width - 80, 100), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, app_name)

    # 4. バージョン表記
    painter.setFont(FontManager.get_font(10, 400))
    painter.setPen(QColor("#666666"))
    painter.drawText(QRect(44, 200, width, 20), Qt.AlignmentFlag.AlignLeft, version)

    # 5. ステータスメッセージ (右下寄り)
    painter.setFont(FontManager.get_font(11, 500))
    painter.setPen(QColor("#BB86FC"))
    painter.drawText(QRect(0, height - 110, width - 40, 30), Qt.AlignmentFlag.AlignRight, loading_message.upper())

    # 6. 右下に namelogo.png を配置
    logo_path = project_root / LOGO_SPLASH_PATH
    if logo_path.exists():
        logo_pixmap = QPixmap(str(logo_path))
        scaled_logo = logo_pixmap.scaledToHeight(32, Qt.TransformationMode.SmoothTransformation)
        logo_x = width - scaled_logo.width() - 40
        logo_y = height - scaled_logo.height() - 45
        painter.drawPixmap(logo_x, logo_y, scaled_logo)
    
    # 7. コピーライト
    painter.setFont(FontManager.get_font(8, 400))
    painter.setPen(QColor("#333333"))
    painter.drawText(QRect(0, height - 25, width - 40, 20), Qt.AlignmentFlag.AlignRight, COMPANY_COPYRIGHT)

    painter.end()

    splash = QSplashScreen(splash_pixmap, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
    splash.show()
    app.processEvents()

    return splash