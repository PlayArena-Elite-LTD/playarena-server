from django.urls import path
from . import views

urlpatterns = [
    path('create/', views.create_match, name='create_match'),
    path('join/', views.join_match, name='join_match'),
    path('detail/<int:match_id>/', views.match_detail, name='match_detail'),
    path('my-matches/', views.my_matches, name='my_matches'),
    path('available/', views.available_matches, name='available_matches'),
    path('cancel/<int:match_id>/', views.cancel_match, name='cancel_match'),
    path('<int:match_id>/submit-result/', views.submit_match_result, name='submit_match_result'),
    path('<int:match_id>/query-result/', views.query_unanswered_result, name='query_unanswered_result'),
    path('<int:match_id>/upload-evidence/', views.upload_evidence, name='upload_evidence'),
    # Day 8 UI: Evidence gallery view
    path('<int:match_id>/evidence-gallery/', views.evidence_gallery, name='evidence_gallery'),
    # Evidence retrieval endpoints (from remote)
    path('evidence/<int:evidence_id>/', views.get_evidence, name='get_evidence'),
    path('evidence/<int:evidence_id>/download/', views.download_evidence, name='download_evidence'),
    path('evidence/<int:evidence_id>/delete/', views.delete_evidence, name='delete_evidence'),
    path('evidence/match/<int:match_id>/', views.list_evidence, name='list_evidence'),
]
