"""Download public model assets once, with pinned SHA256 verification."""
from pathlib import Path
import hashlib
import os
import urllib.request
import ssl
import certifi

from _bootstrap import ROOT
from model_manifest import MODELS

def main():
    root=Path(__file__).resolve().parent.parent/'models';root.mkdir(exist_ok=True)
    for name,(version,task,digest) in MODELS.items():
        path=root/name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==digest:
            print(f'已验证：{name}');continue
        url=f'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/{version}/{task}/{name}'
        print(f'下载公开模型：{name}',flush=True)
        tmp=path.with_suffix('.download')
        with urllib.request.urlopen(url,timeout=120,context=ssl.create_default_context(cafile=certifi.where())) as response,tmp.open('wb') as f:
            for chunk in iter(lambda:response.read(1024*1024),b''):f.write(chunk)
        if hashlib.sha256(tmp.read_bytes()).hexdigest()!=digest:
            tmp.unlink();raise ValueError(f'模型校验失败：{name}')
        os.replace(tmp,path)
    print('模型准备完成。识别视频时无需联网。')

if __name__=='__main__':main()
