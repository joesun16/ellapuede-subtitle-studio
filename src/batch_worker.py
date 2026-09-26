"""A queue-lifetime process keeps OCR models loaded between compatible episodes."""
import json,sys
import subtitle_ocr as core

def main():
    cache={}
    try:
        for line in sys.stdin:
            request=json.loads(line)
            if request.get('shutdown'):break
            try:code=core.main(request['args'],pool_cache=cache)
            except SystemExit as e:code=int(e.code or 0)
            except Exception as e:
                from friendly_errors import describe
                core.control.emit('error',message=describe(e));code=1
            core.control.CONTROL=None
            core.control.emit('job_done',code=code)
    finally:
        if cache.get('pool'):cache['pool'].close()
    return 0
if __name__=='__main__':raise SystemExit(main())
