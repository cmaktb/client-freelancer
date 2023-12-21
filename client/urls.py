from django.urls import path

from client import views

urlpatterns = [
    path('projects/', views.ProjectViewSet.as_view({
        'get': 'list',
        'post': 'create',
    })),
    path('projects/<int:pk>', views.ProjectViewSet.as_view({
        'get': 'retrieve',
        'put': 'update',
        'patch': 'partial_update',
    })),
]
