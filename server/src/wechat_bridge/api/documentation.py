"""Anonymous, build-time public documentation only; no Store or configuration exports."""

from pathlib import PurePosixPath
import zipfile

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from wechat_bridge.config import WEB


def mount_documentation(app):
    @app.get("/docs", include_in_schema=False)
    def slash():
        return RedirectResponse("docs/")

    @app.get("/docs/", include_in_schema=False)
    @app.get("/docs/{path:path}", include_in_schema=False)
    def documentation(path: str = "index.html"):
        path = path or "index.html"
        parts = PurePosixPath(path).parts
        if (
            not path
            or "\\" in path
            or any(p.startswith(".") for p in parts)
            or path.startswith("/")
        ):
            raise HTTPException(404)
        if path == "download.zip":
            if not (WEB / "admin/developer-kit.zip").is_file():
                raise HTTPException(503, "public_documentation_unavailable")
            return FileResponse(
                WEB / "admin/developer-kit.zip",
                media_type="application/zip",
                filename="notify-bridge-public-docs.zip",
            )
        media = {
            ".html": "text/html",
            ".md": "text/markdown",
            ".json": "application/json",
            ".py": "text/plain",
            ".css": "text/css",
        }.get(PurePosixPath(path).suffix)
        if media is None:
            raise HTTPException(404)
        try:
            with zipfile.ZipFile(WEB / "admin/public-docs.zip") as archive:
                content = archive.read(path)
        except KeyError:
            raise HTTPException(404) from None
        except (OSError, zipfile.BadZipFile):
            raise HTTPException(503, "public_documentation_unavailable") from None
        return Response(content, media_type=media)
