from django.urls import path

from . import staff_views, views

urlpatterns = [
    # Customer
    path("cases/", views.my_cases, name="support_my_cases"),
    path("cases/new/", views.raise_case, name="support_raise_case"),
    path("cases/<int:case_id>/", views.case_detail, name="support_case_detail"),
    path("cases/<int:case_id>/reply/", views.reply_to_case, name="support_case_reply"),

    # Staff (Customer Support and admins)
    path("staff/cases/", staff_views.staff_cases, name="support_staff_cases"),
    path("staff/cases/<int:case_id>/", staff_views.staff_case_detail, name="support_staff_case"),
    path("staff/cases/<int:case_id>/pick-up/", staff_views.staff_pick_up, name="support_staff_pick_up"),
    path("staff/cases/<int:case_id>/reply/", staff_views.staff_reply, name="support_staff_reply"),
    path("staff/cases/<int:case_id>/decide/", staff_views.staff_decide, name="support_staff_decide"),
]