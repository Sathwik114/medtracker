from django.urls import path
from . import views

urlpatterns = [

    # ─────────────────────────────────────────
    # DASHBOARD
    # ─────────────────────────────────────────
    path('', views.dashboard, name='dashboard'),

    # ─────────────────────────────────────────
    # MEDICINE MANAGEMENT
    # ─────────────────────────────────────────
    path('add/', views.add_medicine, name='add_medicine'),
    path('edit/<int:pk>/', views.edit_medicine, name='edit_medicine'),
    path('delete/<int:pk>/', views.delete_medicine, name='delete_medicine'),
    path('take/<int:pk>/', views.take_emergency, name='take_emergency'),

    # ─────────────────────────────────────────
    # HISTORY
    # ─────────────────────────────────────────
    path('history/', views.history_view, name='history'),
    path('history/clear/', views.clear_history, name='clear_history'),

    # ─────────────────────────────────────────
    # EXPENSES
    # ─────────────────────────────────────────
    path('expenses/', views.expenses_view, name='expenses'),
    path('expenses/add/', views.add_expense, name='add_expense'),
    path('expenses/delete/<int:pk>/', views.delete_expense, name='delete_expense'),
    path('expenses/download-pdf/', views.download_expenses_pdf, name='download_expenses_pdf'),  # ← ADDED
    path('history/download-pdf/', views.download_history_pdf, name='download_history_pdf'),
    # ─────────────────────────────────────────
    # AI CHATBOT
    # ─────────────────────────────────────────
    path('ai-chatbot/', views.ai_chatbot, name='ai_chatbot'),
]