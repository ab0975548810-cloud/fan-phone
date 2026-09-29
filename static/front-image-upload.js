(() => {
  'use strict';

  const MIB = 1024 * 1024;
  const PNG_TIFF_MAX_BYTES = 50 * MIB;
  const OTHER_IMAGE_MAX_BYTES = 20 * MIB;
  const MAX_DECODED_PIXELS = 32_000_000;
  const MAX_IMAGE_EDGE = 8192;
  const TIFF_SCRIPTS = [
    '/static/vendor/pako-inflate-2.1.0.min.js',
    '/static/vendor/utif-5883510.js'
  ];
  const ACCEPT = '.png,.tif,.tiff,image/png,image/tiff,image/jpeg,image/webp';
  let tiffDecoderPromise = null;

  function extensionOf(file) {
    const match = String(file?.name || '').toLowerCase().match(/\.([^.]+)$/);
    return match ? match[1] : '';
  }

  function imageKind(file) {
    const ext = extensionOf(file);
    const type = String(file?.type || '').toLowerCase().split(';', 1)[0].trim();
    if (ext === 'tif' || ext === 'tiff' || type === 'image/tiff' || type === 'image/tif') return 'tiff';
    if (ext === 'png' || type === 'image/png') return 'png';
    if (ext === 'jpg' || ext === 'jpeg' || type === 'image/jpeg') return 'jpeg';
    if (ext === 'webp' || type === 'image/webp') return 'webp';
    return '';
  }

  function isSupportedUploadImage(file) {
    return Boolean(file && imageKind(file));
  }

  function assertFileSize(file, kind) {
    const maxBytes = kind === 'png' || kind === 'tiff' ? PNG_TIFF_MAX_BYTES : OTHER_IMAGE_MAX_BYTES;
    if (file.size > maxBytes) {
      const limit = Math.round(maxBytes / MIB);
      throw new Error(`圖片超過 ${limit}MB 上限`);
    }
  }

  function assertSafeDimensions(width, height) {
    const w = Number(width);
    const h = Number(height);
    if (!Number.isSafeInteger(w) || !Number.isSafeInteger(h) || w < 1 || h < 1) {
      throw new Error('無法讀取圖片尺寸');
    }
    if (w > MAX_IMAGE_EDGE || h > MAX_IMAGE_EDGE || w * h > MAX_DECODED_PIXELS) {
      throw new Error('圖片像素過大（上限 3,200 萬像素、單邊 8192px）');
    }
    return { width: w, height: h };
  }

  async function pngDimensions(file) {
    const bytes = new Uint8Array(await file.slice(0, 24).arrayBuffer());
    const signature = [137, 80, 78, 71, 13, 10, 26, 10];
    const validSignature = bytes.length >= 24 && signature.every((value, index) => bytes[index] === value);
    const validHeader = validSignature && String.fromCharCode(...bytes.slice(12, 16)) === 'IHDR';
    if (!validHeader) throw new Error('PNG 檔案無效或已損壞');
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    return assertSafeDimensions(view.getUint32(16, false), view.getUint32(20, false));
  }

  function loadScript(src) {
    const existing = document.querySelector(`script[data-image-decoder="${src}"]`);
    if (existing?.dataset.loaded === 'true') return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = existing || document.createElement('script');
      const onLoad = () => {
        script.dataset.loaded = 'true';
        resolve();
      };
      const onError = () => reject(new Error('TIFF 解碼器載入失敗，請重新整理後再試'));
      script.addEventListener('load', onLoad, { once: true });
      script.addEventListener('error', onError, { once: true });
      if (!existing) {
        script.src = src;
        script.async = true;
        script.dataset.imageDecoder = src;
        document.head.appendChild(script);
      }
    });
  }

  function loadTiffDecoder() {
    if (window.UTIF?.decode && window.UTIF?.decodeImage && window.UTIF?.toRGBA8) {
      return Promise.resolve(window.UTIF);
    }
    if (!tiffDecoderPromise) {
      tiffDecoderPromise = TIFF_SCRIPTS.reduce(
        (pending, src) => pending.then(() => loadScript(src)),
        Promise.resolve()
      ).then(() => {
        if (!window.UTIF?.decode || !window.UTIF?.decodeImage || !window.UTIF?.toRGBA8) {
          throw new Error('TIFF 解碼器無法使用');
        }
        return window.UTIF;
      }).catch(error => {
        tiffDecoderPromise = null;
        throw error;
      });
    }
    return tiffDecoderPromise;
  }

  async function decodeTiffToPng(file) {
    const UTIF = await loadTiffDecoder();
    const buffer = await file.arrayBuffer();
    let frames;
    try {
      frames = UTIF.decode(buffer, { parseMN: false, debug: false });
    } catch (error) {
      throw new Error('TIFF 檔案無效或已損壞');
    }
    const frame = (frames || []).find(item => Number(item?.t256?.[0]) > 0 && Number(item?.t257?.[0]) > 0);
    if (!frame) throw new Error('TIFF 找不到可讀取的圖片頁面');
    const expected = assertSafeDimensions(Number(frame.t256[0]), Number(frame.t257[0]));
    try {
      UTIF.decodeImage(buffer, frame, frames);
    } catch (error) {
      throw new Error('TIFF 圖片內容解碼失敗');
    }
    const actual = assertSafeDimensions(frame.width, frame.height);
    if (actual.width !== expected.width || actual.height !== expected.height) {
      throw new Error('TIFF 圖片尺寸資料不一致');
    }
    let rgba;
    try {
      rgba = UTIF.toRGBA8(frame);
    } catch (error) {
      throw new Error('TIFF 色彩資料轉換失敗');
    }
    const expectedBytes = actual.width * actual.height * 4;
    if (!rgba || rgba.byteLength !== expectedBytes) throw new Error('TIFF 圖片資料不完整');
    const canvas = document.createElement('canvas');
    canvas.width = actual.width;
    canvas.height = actual.height;
    const context = canvas.getContext('2d', { alpha: true });
    if (!context) throw new Error('瀏覽器無法建立 TIFF 畫布');
    const pixels = new Uint8ClampedArray(rgba.buffer, rgba.byteOffset, rgba.byteLength);
    context.putImageData(new ImageData(pixels, actual.width, actual.height), 0, 0);
    try {
      return canvas.toDataURL('image/png');
    } finally {
      canvas.width = 1;
      canvas.height = 1;
    }
  }

  function loadBrowserImage(file) {
    const url = URL.createObjectURL(file);
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve({ image, url });
      image.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error('圖片無法解碼'));
      };
      image.src = url;
    });
  }

  async function prepareImageDataURL(file, maxDimension = 1800) {
    const kind = imageKind(file);
    if (!kind) throw new Error('僅支援 PNG、JPG、WEBP、TIF、TIFF');
    assertFileSize(file, kind);
    if (kind === 'png') {
      await pngDimensions(file);
      return window.fileToDataURL(file);
    }
    if (kind === 'tiff') return decodeTiffToPng(file);

    const loaded = await loadBrowserImage(file);
    try {
      const width = loaded.image.naturalWidth || loaded.image.width;
      const height = loaded.image.naturalHeight || loaded.image.height;
      assertSafeDimensions(width, height);
      const ratio = Math.min(1, maxDimension / Math.max(width, height));
      if (ratio === 1 && file.size < 2.5 * MIB) return window.fileToDataURL(file);
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(width * ratio));
      canvas.height = Math.max(1, Math.round(height * ratio));
      const context = canvas.getContext('2d', { alpha: false });
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = 'high';
      context.drawImage(loaded.image, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL(kind === 'webp' ? 'image/webp' : 'image/jpeg', 0.9);
    } finally {
      URL.revokeObjectURL(loaded.url);
    }
  }

  document.querySelectorAll('#photo-input,#slot-input').forEach(input => input.setAttribute('accept', ACCEPT));
  window.isSupportedUploadImage = isSupportedUploadImage;
  window.prepareImageDataURL = prepareImageDataURL;
  window.BenfuwanImageUpload = Object.freeze({
    ACCEPT,
    PNG_TIFF_MAX_BYTES,
    MAX_DECODED_PIXELS,
    MAX_IMAGE_EDGE,
    imageKind,
    isSupportedUploadImage,
    pngDimensions,
    loadTiffDecoder,
    decodeTiffToPng,
    prepareImageDataURL
  });
})();
