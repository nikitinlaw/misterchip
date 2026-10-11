from django.urls import path
from . import views

urlpatterns = [
    path("", views.project_list, name="project_list"),
    path("mine/", views.my_projects, name="my_projects"),
    path("new/", views.project_create, name="project_create"),
    path("edit/<int:pk>/", views.project_edit, name="project_edit"),
    path("submit/<int:pk>/", views.project_submit, name="project_submit"),
    path("<str:slug>/", views.project_detail, name="project_detail"),
]
