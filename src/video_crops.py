"""Convert only the subtitle band to RGB, retaining chroma interpolation context."""
import av
from collections import deque


def configure_decoder(stream):
    # SLICE (PyAV's default) does not parallelize single-slice H.264 streams.
    # Two frame workers bound memory while using both decoder threads. This
    # changes scheduling only, not pixels, PTS, scaling or OCR sampling.
    stream.codec_context.thread_count=2
    stream.codec_context.thread_type='AUTO'
    return stream


def requested_frames(container,stream,rows,needed,meta):
    """Decode only requested PTS windows, preserving the exact source frame.

    Sharing this path keeps all verification passes from decoding a long film
    from the beginning for a few late suspects. A failed keyframe seek falls
    back to sequential decoding; no requested check is silently skipped.
    """
    from resource_control import check
    time_base=float(stream.time_base)
    by_pts={round((rows[i]['start']+meta['origin'])/time_base):i for i in needed}
    if not by_pts:return
    remaining=deque(sorted(by_pts))
    windows=[]
    for pts in sorted(by_pts):
        if windows and (pts-windows[-1][-1])*time_base<=2.0:windows[-1].append(pts)
        else:windows.append([pts])
    for window in windows:
        container.seek(max(0,window[0]),stream=stream,backward=True)
        next_needed=remaining[0]
        for frame in container.decode(stream):
            check()
            if frame.pts is None:continue
            # Never emit a later reference before a missed earlier reference:
            # callers complete a check when its last requested frame arrives.
            if frame.pts>next_needed:break
            index=by_pts.pop(frame.pts,None)
            if index is not None:
                remaining.popleft()
                yield index,frame
            if not by_pts:return
            next_needed=remaining[0]
            if next_needed>window[-1]:break
        if by_pts and remaining[0]<=window[-1]:break
    if by_pts:
        container.seek(0,stream=stream,backward=True)
        last=max(by_pts)
        for frame in container.decode(stream):
            check()
            if frame.pts is None:continue
            if frame.pts>remaining[0]:break
            index=by_pts.pop(frame.pts,None)
            if index is not None:
                remaining.popleft()
                yield index,frame
            if not by_pts or frame.pts>last:break
        if by_pts:raise ValueError('视频复核缺少原始时间戳画面，已保留缓存，请检查视频完整性。')


class FrameCropper:
    def __init__(self, roi):
        self.roi=roi
        self.graph=None
        self.signature=None
        self.disabled=False

    def crop(self, frame):
        import subtitle_ocr as core
        if self.disabled or not isinstance(frame,av.VideoFrame) or int(frame.rotation)%360:
            return core.image_crop(core.oriented_image(frame),self.roi,1)
        try:
            signature=(frame.width,frame.height,frame.format.name)
            if self.signature!=signature:
                w,h=frame.width,frame.height
                x,y,right,bottom=[round(a*b) for a,b in zip(self.roi,(w,h,w,h))]
                # Chroma is subsampled. Align to its lattice and leave a halo for
                # interpolation, then trim RGB to the exact requested pixels.
                ax=max(0,x//8*8-8);ay=max(0,y//8*8-8)
                bx=min(w,(right+7)//8*8+8);by=min(h,(bottom+7)//8*8+8)
                self.graph=av.filter.Graph()
                self.input=self.graph.add_buffer(template=frame)
                crop=self.graph.add('crop',f'{bx-ax}:{by-ay}:{ax}:{ay}:exact=1')
                self.output=self.graph.add('buffersink')
                self.input.link_to(crop);crop.link_to(self.output);self.graph.configure()
                self.box=(x-ax,y-ay,right-ax,bottom-ay);self.signature=signature
            self.input.push(frame)
            image=self.output.pull().to_image().crop(self.box)
            image.info['ellapuede_pixel_scale']=1
            image.info['ellapuede_dialogue_crop']=True
            return image
        except (av.FFmpegError,ValueError,OverflowError):
            self.disabled=True
            return core.image_crop(core.oriented_image(frame),self.roi,1)
