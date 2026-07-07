@echo off
cd /d "%~dp0"
echo ============================================
echo  Setup: install BASIC/PRO backend packages
echo ============================================

echo Installing packages...
pip install mediapipe opencv-python-headless tqdm pandas
pip install insightface fastapi uvicorn python-multipart pydantic requests Pillow google-cloud-firestore
echo Done.

echo ============================================
echo  Done! BASIC/PRO face analysis dependencies are ready.
echo ============================================
pause
