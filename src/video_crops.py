"""Convert only the subtitle band to RGB, retaining chroma interpolation context."""
import av


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
