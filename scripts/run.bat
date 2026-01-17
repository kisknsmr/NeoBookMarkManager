@echo off
REM 仮想環境を有効化してプログラムを実行するスクリプト（Windows用）

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
set VENV_DIR=%PROJECT_ROOT%\.venv

REM 仮想環境が存在しない場合は作成
if not exist "%VENV_DIR%" (
    echo 仮想環境が見つかりません。作成します...
    python -m venv "%VENV_DIR%"
    echo ✅ 仮想環境を作成しました
)

REM 仮想環境を有効化
call "%VENV_DIR%\Scripts\activate.bat"

REM プロジェクトディレクトリに移動
cd /d "%PROJECT_ROOT%"

REM 依存関係をインストール（必要に応じて）
if not exist "%VENV_DIR%\.installed" (
    echo 依存関係をインストールしています...
    pip install -r "%PROJECT_ROOT%\requirements.txt"
    type nul > "%VENV_DIR%\.installed"
    echo ✅ 依存関係のインストールが完了しました
)

REM プログラムを実行（main.py で __pycache__ 生成防止が設定済み）
echo プログラムを起動します...
python "%PROJECT_ROOT%\main.py"
