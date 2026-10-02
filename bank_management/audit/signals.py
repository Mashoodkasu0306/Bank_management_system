from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .alerts import check_failed_logins
from .helpers import log_action
from .models import Actions


@receiver(user_logged_in)
def record_login(sender, request, user, **kwargs):
    log_action(Actions.LOGIN_SUCCESS, request=request, actor=user)


@receiver(user_logged_out)
def record_logout(sender, request, user, **kwargs):
    if user is not None:
        log_action(Actions.LOGOUT, request=request, actor=user)


@receiver(user_login_failed)
def record_failed_login(sender, credentials, request=None, **kwargs):
    # Only the username is kept. The password in `credentials` is never stored.
    attempted = str(credentials.get("username", ""))[:150]
    log_action(Actions.LOGIN_FAILED, request=request, username=attempted)
    # Too many failures in a short time? Raise an alert.
    check_failed_logins(attempted)