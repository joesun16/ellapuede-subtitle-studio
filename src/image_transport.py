"""Lossless local IPC; avoid PNG compression for bounded subtitle crops."""
import io

def encode_image(image):
    image=image.convert('RGB');buffer=io.BytesIO()
    # Large calibration frames stay compressed to bound JSON/pipe allocations.
    if image.width*image.height*3<=4*1024*1024:image.save(buffer,format='BMP')
    else:image.save(buffer,format='PNG',compress_level=1)
    return buffer.getvalue()
