# quick_start.ps1 - quick start script for Windows PowerShell
param()
if (-Not (Test-Path -Path "unq_img")) {
    python -m venv unq_img
}
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
.\unq_img\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
