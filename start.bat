@echo off
REM Texel Studio - one-command setup & start (Windows). Same steps as start.sh.
cd /d "%~dp0"

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate.bat

echo Installing Python dependencies...
pip install -q -r requirements.txt

if not exist .env (
    copy .env.example .env >nul
    echo.
    echo Created .env from .env.example
    echo Edit .env with your API keys before generating. Painting with Claude Code needs no key.
    echo.
)

if not exist static\_next (
    echo Building frontend...
    pushd frontend
    call npm install --silent
    call npm run build
    popd
)

echo.
echo Starting Texel Studio on http://localhost:8500
echo.
python -m texel_paint serve
