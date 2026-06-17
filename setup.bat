@echo off
cd /d "%~dp0"
echo ============================================
echo  Setup: install packages, prepare data, train
echo ============================================

echo [1/4] Installing packages...
pip install kaggle mediapipe opencv-python-headless tqdm pandas
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install timm onnx insightface onnxruntime fastapi uvicorn python-multipart
echo Done.

echo [2/4] Checking kaggle.json...
if not exist "%USERPROFILE%\.kaggle" mkdir "%USERPROFILE%\.kaggle"
if not exist "%USERPROFILE%\.kaggle\kaggle.json" (
    echo ERROR: kaggle.json not found.
    echo Please download it from https://www.kaggle.com/settings
    echo and place it at: %USERPROFILE%\.kaggle\kaggle.json
    pause
    exit /b 1
)
echo kaggle.json OK.

echo [3/4] Checking CelebA...
if exist "celeba_raw\img_align_celeba" (
    echo CelebA found, skipping download.
) else (
    kaggle datasets download -d jessicali9530/celeba-dataset -p celeba_raw --unzip
)

echo [4/4] Preparing dataset...
python prepare_data.py

echo Training eyelid model...
python Traineyelid.py

echo ============================================
echo  Done! eyelid_model.onnx is ready.
echo ============================================
pause
