"""
Application Configuration
アプリケーション全体の設定情報を一元管理

企業ソフトウェアとして、アプリ名、バージョン、会社情報などを
コードに直接書かず、この設定ファイルから参照する設計。
"""

from typing import Final

# ============ Application Information ============
APP_NAME: Final[str] = "📑 Bookmark Studio"
APP_NAME_SHORT: Final[str] = "Bookmark Studio"
APP_NAME_BRAND: Final[str] = "CHANTORUS"  # ブランド名（必要に応じて使用）

VERSION: Final[str] = "v2.0.0"
VERSION_BUILD: Final[str] = "BUILD 2026.1"  # ビルド情報

# ============ Company Information ============
COMPANY_NAME: Final[str] = "Tantal R.D. Bower"
COMPANY_NAME_UPPER: Final[str] = "TANTAL R.D. BOWER"  # 大文字表記
COMPANY_COPYRIGHT: Final[str] = "© 2026 TANTAL R.D. BOWER. ALL RIGHTS RESERVED."

# ============ Splash Screen Configuration ============
SPLASH_APP_NAME: Final[str] = APP_NAME  # スプラッシュ画面にはアプリ名を表示
SPLASH_VERSION: Final[str] = VERSION  # スプラッシュ画面にはバージョンを表示
SPLASH_LOADING_MESSAGE: Final[str] = "Initializing Core Engine..."
SPLASH_WIDTH: Final[int] = 600
SPLASH_HEIGHT: Final[int] = 360

# ============ Logo Paths ============
LOGO_SPLASH_PATH: Final[str] = "gui/splash/namelogo.png"  # スプラッシュ画面用ロゴ

# ============ Application Metadata ============
APP_DESCRIPTION: Final[str] = "Advanced Bookmark Management System"
APP_AUTHOR: Final[str] = COMPANY_NAME
APP_LICENSE: Final[str] = "Proprietary"
