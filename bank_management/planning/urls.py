from django.urls import path

from . import recurring_views, staff_views, views

urlpatterns = [
    path("goals/", views.my_goals, name="my_goals"),
    path("goals/new/", views.goal_create, name="goal_create"),
    path("goals/<int:goal_id>/edit/", views.goal_edit, name="goal_edit"),
    path("goals/<int:goal_id>/archive/", views.goal_archive, name="goal_archive"),
    path("staff/recurring/", staff_views.run_recurring_page, name="run_recurring_page"),
    path("recurring/", recurring_views.my_recurring, name="my_recurring"),
    path("recurring/new/", recurring_views.recurring_create, name="recurring_create"),
]