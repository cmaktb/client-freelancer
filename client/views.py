from client import serializers
from common.auth import JWTTokenAuthentication
from common.permissions import IsRegisteredClient
from common.views import PaginatedViewSet


class ProjectAttachmentsViewSet(PaginatedViewSet):
    authentication_classes = [JWTTokenAuthentication]
    permission_classes = [IsRegisteredClient]
    single_serializer_class = serializers.SingleAttachmentSerializer

    def get_queryset(self, request):
        return request.user.client.project_attachments

    def create_default_params(self, request):
        return {
            'client_id': request.user.client_id
        }
