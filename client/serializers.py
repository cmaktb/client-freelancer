from rest_framework import serializers

from rest_framework import serializers

from client.models import Project
from common.serializers import BaseModelSerializer
from content.models import Skill


class SkillSerializer(BaseModelSerializer):
    class Meta:
        model = Skill
        fields = (
            'id',
            'title'
        )


class ProjectSerializer(BaseModelSerializer):
    status = serializers.CharField(read_only=True)
    skills = SkillSerializer(
        read_only=True,
        many=True
    )

    class Meta:
        model = Project
        fields = (
            'id',
            'title',
            'status',
            'rejection_reason',
            'created_at',
            'fee',
            'contract_type',
            'skills',
            'num_time_units',
            'total_amount',
            'project_due_date',
            'is_private',
            'bids_count',
            'expired',
            'remain_time_to_expire',
            'remain_time_of_five_days_rule'
        )
