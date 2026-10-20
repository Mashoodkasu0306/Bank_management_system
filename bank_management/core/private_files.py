import os

from django.http import FileResponse, Http404

# Only these types open in the browser. Anything else is downloaded.
INLINE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


def serve_private_file(field_file):
    # Send a stored file. Call this only AFTER the permission check.
    if not field_file:
        raise Http404("No file")
    try:
        handle = field_file.open("rb")
    except (OSError, ValueError):
        raise Http404("File not found")
    name = os.path.basename(field_file.name)
    inline = os.path.splitext(name)[1].lower() in INLINE_EXTENSIONS
    response = FileResponse(handle, as_attachment=not inline, filename=name)
    response["Cache-Control"] = "private, no-store"
    return response
