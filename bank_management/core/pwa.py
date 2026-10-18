from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_GET

APP_NAME = "Apex Core Banking"


@require_GET
def manifest(request):
    """The file that lets a browser install the site as an app."""
    data = {
        "name": APP_NAME,
        "short_name": "Apex Bank",
        "description": "Online banking for customers and bank staff.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#0f1b2d",
        "theme_color": "#0f1b2d",
        "icons": [
            {"src": static("pwa/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": static("pwa/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


@require_GET
def service_worker(request):
    """Served from /sw.js so it can cover the whole site. It is never cached by the browser."""
    response = render(request, "pwa/sw.js", {"dev": settings.DEBUG}, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@require_GET
def offline(request):
    """A public page with no personal details. The service worker keeps one copy for when there is no network."""
    return render(request, "offline.html")