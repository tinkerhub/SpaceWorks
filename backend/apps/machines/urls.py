from django.urls import path

from apps.machines.own_request_history import OwnMachineServiceRequestsView
from apps.machines.views_public import PublicMachineListView
from apps.machines.views_public_service import PublicMachineServiceSubmitView
from apps.machines.views_public_service_types import (
    PublicMachineServiceTypesView, PublicMachineServiceUploadView, PublicMachineServiceStatusView,
)
from apps.machines.views_public_printer_service import (
    PublicPrinterPoolsView, PublicPrinterQueuesView, PublicPrinterRequestView,
    PublicPrinterStatusView, PublicPrinterUploadView,
)


urlpatterns = [
    path(
        'public/<slug:makerspace_slug>/machine-service-requests/mine',
        OwnMachineServiceRequestsView.as_view(),
        name='public-own-machine-service-requests',
    ),
    path('public/<slug:makerspace_slug>/machine-service/types', PublicMachineServiceTypesView.as_view(), name='public-machine-service-types'),
    path('public/<slug:makerspace_slug>/machine-service/uploads', PublicMachineServiceUploadView.as_view(), name='public-machine-service-upload'),
    path('public/machine-service/requests/<uuid:public_token>/status', PublicMachineServiceStatusView.as_view(), name='public-machine-service-status'),
    path(
        'public/<slug:makerspace_slug>/machines',
        PublicMachineListView.as_view(),
        name='public-machines',
    ),
    path(
        'public/<slug:makerspace_slug>/machine-service-requests',
        PublicMachineServiceSubmitView.as_view(),
        name='public-machine-service-request-submit',
    ),
    path('public/<slug:makerspace_slug>/machine-service/3d-printer/queues', PublicPrinterQueuesView.as_view(), name='public-printer-service-queues'),
    path('public/<slug:makerspace_slug>/machine-service/3d-printer/consumable-pools', PublicPrinterPoolsView.as_view(), name='public-printer-service-pools'),
    path('public/<slug:makerspace_slug>/machine-service/3d-printer/uploads', PublicPrinterUploadView.as_view(), name='public-printer-service-upload'),
    path('public/<slug:makerspace_slug>/machine-service/3d-printer/requests', PublicPrinterRequestView.as_view(), name='public-printer-service-request'),
    path('public/machine-service/3d-printer/requests/<uuid:public_token>/status', PublicPrinterStatusView.as_view(), name='public-printer-service-status'),
]
