"""Bounded, normalized and encrypted owner-uploaded image attachments."""
import io
import time
import uuid
from PIL import Image, ImageOps, UnidentifiedImageError
from wechat_bridge.storage.client_registry import ClientError

MAX_UPLOAD = 5 * 1024 * 1024
MAX_STORAGE = 250 * 1024 * 1024


def normalize(raw):
    if not raw or len(raw)>MAX_UPLOAD:
        raise ClientError('image_too_large',413)
    try:
        with Image.open(io.BytesIO(raw),formats=['JPEG','PNG','WEBP']) as source:
            if source.width*source.height>8_000_000 or getattr(source,'n_frames',1)!=1:
                raise ClientError('image_dimensions_unsupported',422)
            source.load()
            image=ImageOps.exif_transpose(source)
            image.thumbnail((2048,2048))
            mode='RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB'
            pixels=image.convert(mode)
            clean=Image.frombytes(mode,pixels.size,pixels.tobytes())
            out=io.BytesIO()
            fmt='PNG' if mode=='RGBA' else 'JPEG'
            clean.save(out,format=fmt,**({'quality':90} if fmt=='JPEG' else {}))
            content=out.getvalue()
            if len(content)>MAX_UPLOAD:raise ClientError('image_too_large',413)
            return content,'image/png' if fmt=='PNG' else 'image/jpeg',clean.width,clean.height
    except ClientError:raise
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):
        raise ClientError('invalid_image',422) from None


class Images:
    def __init__(self,store):
        self.store,self.db=store,store.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS image_attachments(
            id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,mime TEXT NOT NULL,
            width INTEGER NOT NULL,height INTEGER NOT NULL,size INTEGER NOT NULL,
            encrypted BLOB NOT NULL,created_at REAL NOT NULL,inbox_id INTEGER)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS images_conversation ON image_attachments(conversation_id)')
        self.cleanup()

    def cleanup(self):
        self.db.execute('DELETE FROM image_attachments WHERE inbox_id IS NULL AND created_at<?',(time.time()-86400,))

    def public(self,row):
        return {k:row[k] for k in ('id','mime','width','height','size')}

    def save(self,cid,normalized):
        self.store.portal.owner_chat(cid,writable=True)
        self.cleanup()
        content,mime,width,height=normalized
        used=self.db.execute('SELECT coalesce(sum(size),0) FROM image_attachments').fetchone()[0]
        if used+len(content)>MAX_STORAGE:raise ClientError('image_storage_full',507)
        if self.db.execute('SELECT count(*) FROM image_attachments WHERE conversation_id=? AND inbox_id IS NULL',(cid,)).fetchone()[0]>=12:
            raise ClientError('too_many_pending_images',429)
        id=uuid.uuid4().hex
        self.db.execute('INSERT INTO image_attachments VALUES (?,?,?,?,?,?,?,?,NULL)',
            (id,cid,mime,width,height,len(content),self.store.cipher.encrypt(content),time.time()))
        return self.public(self.db.execute('SELECT * FROM image_attachments WHERE id=?',(id,)).fetchone())

    def get(self,cid,id,pending=False):
        self.store.portal.owner_chat(cid)
        row=self.db.execute('SELECT * FROM image_attachments WHERE id=? AND conversation_id=?',(id,cid)).fetchone()
        if not row or (not pending and row['inbox_id'] is None):raise ClientError('image_not_found',404)
        return row
