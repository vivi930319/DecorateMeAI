self.onmessage = async (event) => {
    const { id, file, role, maxEdge, quality, outputName } = event.data || {};
    try {
        if (!file || !file.type || !file.type.startsWith('image/')) {
            self.postMessage({ id, ok: false, error: '不是圖片檔案' });
            return;
        }

        const bitmap = await createImageBitmap(file);
        const originalWidth = bitmap.width;
        const originalHeight = bitmap.height;
        const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
        const width = Math.max(1, Math.round(bitmap.width * scale));
        const height = Math.max(1, Math.round(bitmap.height * scale));
        const canvas = new OffscreenCanvas(width, height);
        const ctx = canvas.getContext('2d');
        ctx.drawImage(bitmap, 0, 0, width, height);

        const blob = await canvas.convertToBlob({ type: 'image/jpeg', quality });
        const dataUrl = await blobToDataUrl(blob);
        bitmap.close();

        self.postMessage({
            id,
            ok: true,
            role,
            blob,
            dataUrl,
            outputName,
            originalWidth,
            originalHeight,
            compressedWidth: width,
            compressedHeight: height,
        });
    } catch (err) {
        self.postMessage({ id, ok: false, error: err.message || '圖片 Worker 壓縮失敗' });
    }
};

async function blobToDataUrl(blob) {
    const buffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    return `data:${blob.type};base64,${btoa(binary)}`;
}
