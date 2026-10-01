from .models import AuditLog


def _client_ip(request):
    """Uses REMOTE_ADDR only. Headers like X-Forwarded-For can be faked by the caller."""
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def log_action(action, request=None, actor=None, target_type="", target_id=None,
               details="", username=""):
    """Write one line in the audit notebook.

    - request: if given, we record the IP, and the logged-in user as the actor.
    - actor: pass the user explicitly when there is no request (or it is not logged in yet).
    - username: for cases with no real user, such as a failed login attempt.
    """
    if actor is None and request is not None:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            actor = user

    if actor is not None and not username:
        username = actor.get_username()

    return AuditLog.objects.create(
        actor=actor,
        actor_username=(username or "")[:150],
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=(details or "")[:500],
        ip_address=_client_ip(request),
    )