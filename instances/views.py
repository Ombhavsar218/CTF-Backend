from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_admin_action
from challenges.models import Challenge

from .serializers import ChallengeInstancePublicSerializer
from .services import (
    InstanceConflict,
    InstanceNotEligible,
    InstanceRuntimeFailure,
    InstanceService,
)


class InstanceStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        challenge = Challenge.objects.filter(pk=pk).first()
        if not challenge:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            instance, created = InstanceService().start(request.user, challenge)
        except InstanceNotEligible as exc:
            return Response({'detail': exc.message, 'code': exc.code},
                            status=status.HTTP_400_BAD_REQUEST)
        except InstanceConflict as exc:
            return Response({'detail': exc.message, 'code': exc.code},
                            status=status.HTTP_409_CONFLICT)
        except InstanceRuntimeFailure as exc:
            try:
                log_admin_action(
                    actor=request.user,
                    action='instance.start_failed',
                    target_type='challenge',
                    target_id=challenge.pk,
                    target_label=challenge.title,
                    metadata={'reason': exc.message[:255]},
                )
            except Exception:
                pass
            return Response(
                {'detail': exc.message, 'code': exc.code, 'status': 'failed'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            log_admin_action(
                actor=request.user,
                action='instance.start_requested' if not created else 'instance.started',
                target_type='instance',
                target_id=instance.pk,
                target_label=challenge.title,
                metadata={
                    'challenge_id': challenge.pk,
                    'result': 'existing' if not created else 'started',
                },
            )
        except Exception:
            pass

        serializer = ChallengeInstancePublicSerializer(instance)
        return Response(serializer.data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class InstanceActiveView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        instance = InstanceService().active(request.user)
        if not instance:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(ChallengeInstancePublicSerializer(instance).data)

    def delete(self, request, pk=None):
        try:
            instance = InstanceService().stop(request.user)
        except InstanceRuntimeFailure as exc:
            return Response({'detail': exc.message, 'code': exc.code},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not instance:
            return Response(status=status.HTTP_204_NO_CONTENT)

        try:
            log_admin_action(
                actor=request.user,
                action='instance.stop_requested',
                target_type='instance',
                target_id=instance.pk,
                target_label=instance.challenge.title,
                metadata={'challenge_id': instance.challenge_id, 'real_docker': True},
            )
        except Exception:
            pass
        return Response(ChallengeInstancePublicSerializer(instance).data)
