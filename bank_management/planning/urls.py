from django.urls import path

from . import views

urlpatterns = [
    path("goals/", views.my_goals, name="my_goals"),
    path("goals/new/", views.goal_create, name="goal_create"),
    path("goals/<int:goal_id>/edit/", views.goal_edit, name="goal_edit"),
    path("goals/<int:goal_id>/archive/", views.goal_archive, name="goal_archive"),
]