from django.urls import path
from . import views

urlpatterns = [
    path("", views.article_list, name="article_list"),
    path("mine/", views.my_articles, name="my_articles"),
    path("new/", views.article_create, name="article_create"),
    path("edit/<int:pk>/", views.article_edit, name="article_edit"),
    path("submit/<int:pk>/", views.article_submit, name="article_submit"),
    path("<str:slug>/", views.article_detail, name="article_detail"),
]
