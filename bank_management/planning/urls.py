from django.urls import path

from . import insights_views, recurring_actions, recurring_views, staff_views, views

urlpatterns = [
    path("goals/", views.my_goals, name="my_goals"),
    path("goals/new/", views.goal_create, name="goal_create"),
    path("goals/<int:goal_id>/edit/", views.goal_edit, name="goal_edit"),
    path("goals/<int:goal_id>/archive/", views.goal_archive, name="goal_archive"),
    path("staff/recurring/", staff_views.run_recurring_page, name="run_recurring_page"),
    path("recurring/", recurring_views.my_recurring, name="my_recurring"),
    path("recurring/new/", recurring_views.recurring_create, name="recurring_create"),
    path("recurring/<int:payment_id>/pause/", recurring_actions.recurring_pause, name="recurring_pause"),
    path("recurring/<int:payment_id>/resume/", recurring_actions.recurring_resume, name="recurring_resume"),
    path("recurring/<int:payment_id>/cancel/", recurring_actions.recurring_cancel, name="recurring_cancel"),
    path("insights/", insights_views.my_insights, name="my_insights"),
]