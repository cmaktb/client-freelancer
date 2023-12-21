import datetime
from datetime import timedelta
from typing import List

from django.db import models
from django.db.models import Q, Count
from django.db.transaction import atomic
from django.utils import timezone
from sdks.chat import chat_connector

from client import const
from common import tasks
from common.models import BaseModel
from common.pagination import PaginationFilterable, PaginationSortable, PaginationSearchable
from common.utils import subtract_two_times
from service import const as service_const
from service.models import ChatNotificationText
from winatalent import settings


class Project(BaseModel, PaginationFilterable, PaginationSortable, PaginationSearchable):
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name='projects'
    )
    client_user = models.ForeignKey(
        'client.ClientUser',
        on_delete=models.PROTECT,
        blank=True,
        null=True
    )
    country = models.ForeignKey(
        'content.Country',
        related_name="%(class)s_country",
        blank=True,
        null=True,
        on_delete=models.SET_NULL
    )
    status = models.CharField(
        max_length=255,
        choices=const.PROJECT_STATUS_CHOICES,
        default=const.PROJECT_STATUS_DRAFT
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True
    )
    skills = models.ManyToManyField(
        'content.Skill',
    )
    about_client = models.TextField(
        null=True,
        blank=True
    )
    title = models.CharField(
        max_length=255
    )
    contract_type = models.CharField(
        max_length=255,
        choices=const.CONTRACT_TYPE_CHOICES
    )
    english_proficiency = models.CharField(
        max_length=255,
        choices=const.LANGUAGE_GRADE_CHOICES,
        null=True,
    )
    budget = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        blank=True,
        null=True
    )

    duties = models.TextField()

    rejection_reason = models.TextField(blank=True, null=True)

    num_time_units = models.PositiveIntegerField(blank=True, null=True)

    project_due_date = models.DateField(blank=True, null=True)

    is_private = models.BooleanField(default=False)

    custom_text = models.TextField(null=True, blank=True)  # just for admin matters

    expired = models.BooleanField(default=False)

    expire_datetime = models.DateTimeField(blank=True, null=True, default=None)
    project_type = models.CharField(
        max_length=255,
        choices=const.PROJECT_TYPE_CHOICES,
        default=const.PROJECT_TYPE_NORMAL
    )
    evaluator = models.ForeignKey("evaluator.Evaluator", on_delete=models.SET_NULL, blank=True, null=True,
                                  related_name='projects')
    shortlist_status = models.CharField(max_length=50, choices=const.ProjectShortlistStatus.choices,
                                        default=const.ProjectShortlistStatus.WAITING)
    created_by_admin = models.BooleanField(default=False)

    class Meta:
        permissions = [
            ('can_login_as_client', 'Can login as client')
        ]

    @property
    def client_user_detail(self):
        return '{} | full name: {} {}'.format(self.client_user.email,
                                              self.client_user.first_name,
                                              self.client_user.last_name)

    @property
    def descriptions(self):
        return self.descriptions.all()

    def has_pending_description(self):
        num = self.descriptions.filter(status=const.PROJECT_DESCRIPTION_STATUS_PENDING).count()
        return True if num > 0 else False

    @property
    def referer(self):
        if not self.is_private or not self.client.referer_uuid:
            return None
        return self.client.referer.email

    @property
    def bids_count(self):
        return self.bids.all().count()

    @property
    def time_of_expire(self):
        if self.expire_datetime:
            return self.expire_datetime
        if self.published_at:
            return self.published_at + timedelta(days=90)

    @property
    def remain_time_of_five_days_rule(self):
        ZERO_TIME = {
            'days': "0",
            'time': datetime.datetime.strptime('00:00', '%H:%M').time()
        }
        now = timezone.now()
        if not self.five_days_rule_due_date:
            return 'The project is not published yet'
        datetime_left = self.five_days_rule_due_date - now
        hours, minutes, seconds = subtract_two_times(now.time(), self.five_days_rule_due_date.time())
        if datetime_left.days <= 0:
            return ZERO_TIME
        return {
            'days': "{}".format(datetime_left.days),
            'time': "{}:{}".format(hours, minutes)
        }

    @property
    def is_open_for_bidding(self) -> bool:
        return self.status == const.PROJECT_STATUS_OPEN

    @property
    def fee(self):
        return self.budget

    @property
    def total_amount(self):
        if self.contract_type == const.CONTRACT_TYPE_FULL_PROJECT:
            return self.fee
        if self.fee and self.num_time_units and self.fee > 0 and self.num_time_units > 0:
            return self.fee * self.num_time_units
        else:
            return None

    def can_update(self) -> bool:
        return self.status in (const.PROJECT_STATUS_DRAFT, const.PROJECT_STATUS_REJECTED)

    def expire(self):
        self.expired = True
        self.expire_datetime = timezone.now()
        self.save()

    def is_five_days_rule_applies(self):
        now = timezone.now()
        rule_day = self.time_of_expire + timedelta(days=settings.EXPIRE_DAYS_RULE_FOR_HIRE)
        remain_time_to_hire = rule_day - now
        if remain_time_to_hire.days > 0:
            return True
        return False  # client can not send Offer or they can not chat anymore

    def can_freelancer_bid(self, freelancer) -> bool:
        if not self.is_private or self.client.referer_uuid == freelancer.user_uuid:
            return True

        return False

    def get_filtered_bids(self, list_filter):
        return self.bids.all().filter(group=list_filter)

    def get_bid_list_counts(self):
        return self.bids.all().values('group').annotate(count=Count('group'))

    def close(self):
        self.status = const.PROJECT_STATUS_APPLICATION_CLOSED
        self.save()

    def get_bid(self, freelancer) -> 'Bid' or None:
        return self.bids.filter(freelancer=freelancer).first()

    def reject(self, rejection_reason):
        self.status = const.PROJECT_STATUS_REJECTED
        self.rejection_reason = rejection_reason
        self.is_private = False
        self.save()
        self.send_reject_email()
        self.client.send_reject_project_notification_to_client()

    def expire_chatrooms(self):
        for bid in self.bids.all():
            if bid.reference:
                chat_connector.expire_room(bid.reference)

    @atomic
    def accept(self):
        self.status = const.PROJECT_STATUS_OPEN
        self.published_at = timezone.now()
        if self.is_private:
            self.client.use_referer()

        self.save()
        self.send_accept_email()
        self.send_accept_notification()

    @atomic
    def submit_for_review(self, country_id):
        self.status = const.PROJECT_STATUS_PENDING
        self.country_id = country_id
        self.save()
        self.send_project_submitted_email()
        self.send_project_submit_admin_notification_email()

    @classmethod
    def get_filterable_fields(cls):
        return ['skills__id', 'country__id', 'title', 'contract_type']

    @classmethod
    def get_sortable_fields(cls):
        return ['published_at', 'id', 'status']

    @classmethod
    def get_searchable_fields(cls):
        return ['title', 'skills__title']

    @classmethod
    def get_public_projects(cls, client=None, freelancer=None) -> List['Project'] or 'models.QuerySet':
        if client:
            return cls.objects.filter(
                client__users__deactivated=False,
            ).filter(
                Q(
                    status__in=(
                        const.PROJECT_STATUS_APPLICATION_CLOSED,
                        const.PROJECT_STATUS_OPEN
                    )
                ) | Q(
                    client=client
                )
            ).exclude(
                project_type=const.PROJECT_TYPE_AUTO_BUILD_MANUAL_OFFER
            )
        if freelancer:
            return cls.objects.filter(client__users__deactivated=False).filter(
                Q(
                    status__in=(
                        const.PROJECT_STATUS_APPLICATION_CLOSED,
                        const.PROJECT_STATUS_OPEN
                    )
                ) | Q(
                    bids__freelancer_id=freelancer.pk
                )
            ).exclude(
                project_type=const.PROJECT_TYPE_AUTO_BUILD_MANUAL_OFFER
            )
        return cls.objects.filter(
            client__users__deactivated=False,
            is_private=False
        ).filter(
            status__in=(
                const.PROJECT_STATUS_APPLICATION_CLOSED,
                const.PROJECT_STATUS_OPEN
            )
        ).exclude(
            project_type=const.PROJECT_TYPE_AUTO_BUILD_MANUAL_OFFER
        )

    @fee.setter
    def fee(self, fee):
        self.budget = fee

    @tasks.async_function
    def send_project_submitted_email(self):
        for user in self.client.users.all():  # type: ClientUser
            user.send_email_to_user(service_const.SYSTEM_TEXT_CLIENT_PROJECT_SUBMITTED_EMAIL, project=self)

    @tasks.async_function
    def send_periodic_draft_project_email(self, text_type):
        for user in self.client.users.all():  # type: ClientUser
            user.send_email_to_user(
                text_type,
                project=self
            )

    @tasks.async_function
    def send_accept_email(self):
        for user in self.client.users.all():  # type: ClientUser
            user.send_email_to_user(service_const.SYSTEM_TEXT_CLIENT_ACCEPT_PROJECT_EMAIL)

    @tasks.async_function
    def send_accept_notification(self):
        notification = ChatNotificationText.get_by_topic(
            service_const.CHAT_NOTIFICATION_TEXT_PROJECT_APPROVE
        )
        if not notification:
            print("Project Approval notification text is not set !")
            return

        for user in self.client.users.all():  # type: ClientUser
            user.send_chat_notification(notification.text)

    @tasks.async_function
    def send_reject_email(self):
        for user in self.client.users.all():  # type: ClientUser
            user.send_email_to_user(service_const.SYSTEM_TEXT_CLIENT_REJECT_PROJECT_EMAIL)

    def __str__(self):
        return self.title
