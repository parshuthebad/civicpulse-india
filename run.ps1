# CivicPulse — National Deepfake & Fact-Verification Portal Setup & Launch
if (-Not (Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment (.venv)..." -ForegroundColor Cyan
    python -m venv .venv
}

Write-Host "Activating .venv..." -ForegroundColor Cyan
.\.venv\Scripts\Activate.ps1

Write-Host "Installing dependencies..." -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host "Starting CivicPulse Portal at http://127.0.0.1:8000 ..." -ForegroundColor Green
uvicorn app.main:app --reload --port 8000
