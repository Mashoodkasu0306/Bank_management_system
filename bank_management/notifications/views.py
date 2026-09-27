from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Notification


@login_required
def notifications_list(request):
    tab = request.GET.get('tab', 'ALL')
    notifications = Notification.objects.filter(recipient=request.user)

    if tab != 'ALL':
        matching_ids = [n.id for n in notifications if n.group() == tab]
        notifications = notifications.filter(id__in=matching_ids)

    unread_by_group = {}
    for n in Notification.objects.filter(recipient=request.user, is_read=False):
        unread_by_group[n.group()] = unread_by_group.get(n.group(), 0) + 1

    return render(request, 'notifications/list.html', {
        'notifications': notifications,
        'active_tab': tab,
        'unread_by_group': unread_by_group,
    })


@login_required
def mark_notification_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    notification.is_read = True
    notification.save()
    if notification.link:
        return redirect(notification.link)
    return redirect('notifications_list')


@login_required
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect('notifications_list')
