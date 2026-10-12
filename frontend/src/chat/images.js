export async function preparePhoto(file) {
  if (file.size > 20 * 1024 * 1024)
    throw new Error("请选择小于 20 MB 的图片。");
  const url = URL.createObjectURL(file),
    img = new Image();
  try {
    img.src = url;
    await img.decode();
    const scale = Math.min(
        1,
        2048 / Math.max(img.naturalWidth, img.naturalHeight),
      ),
      canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) =>
      canvas.toBlob(
        resolve,
        file.type === "image/png" ? "image/png" : "image/jpeg",
        0.9,
      ),
    );
    if (!blob || blob.size > 5 * 1024 * 1024)
      throw new Error("图片过大，请尝试截图后发送。");
    return { blob, url: URL.createObjectURL(blob) };
  } finally {
    URL.revokeObjectURL(url);
  }
}
