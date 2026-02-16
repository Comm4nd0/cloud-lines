from django.urls import path
from . import tabledata
from . import views
from . import pedigree_charging

urlpatterns = [
    path('search', views.search, name='pedigree_search'),
    path('<int:pedigree_id>', views.ShowPedigree.as_view(), name='pedigree'),
    path('new_pedigree/', views.new_pedigree_form, name='new_pedigree_form'),
    path('<int:id>/edit_pedigree/', views.edit_pedigree_form, name='edit_pedigree_form'),
    path('<int:id>/image_upload_pedigree/', views.image_upload, name='image_upload'),
    path('<int:pedigree_id>/add_existing', views.add_existing, name='add_existing'),
    path('<int:pedigree_id>/add_existing_parent', views.add_existing_parent, name='add_existing_parent'),
    path('<int:pedigree_id>/certificate/<str:type>', views.GenerateCert.as_view(), name='cert'),
    path('get-pedigrees', tabledata.get_pedigrees, name="get_pedigrees"),
    path('get_pedigree_details', views.get_pedigree_details, name="get_pedigree_details"),
    path('<int:pedigree_id>/ancestors/', views.get_ancestors, name='get_ancestors'),
    path('get-ta-pedigrees/<str:sex>/<str:state>/<str:avoid>', tabledata.get_ta_pedigrees, name="get_ta_pedigrees"),
    path('pedigree_payment_settings', pedigree_charging.PedigreePaymentSettings.as_view(), name="pedigree_payment_settings"),
    path('pedigree_price_edit', pedigree_charging.pedigree_price_edit, name="pedigree_price_edit"),
    path('pedigree_checkout/<int:id>/<str:price>', views.pedigree_checkout, name="pedigree_checkout"),
    path('pedigree_checkout_session/<int:id>/<str:price>', pedigree_charging.pedigree_charging_session, name="pedigree_charging_session"),
    path('pedigree_paid', pedigree_charging.pedigree_paid, name="pedigree_paid"),
]
