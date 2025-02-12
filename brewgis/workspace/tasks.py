from celery import shared_task
from django.utils import timezone
from pydoc import locate

from .models import UserDefinedViews


@shared_task()
def execute_user_define_views(udf_id: int):
    udf = UserDefinedViews.objects.get(pk=udf_id)
    module = locate(udf.module)
    result = module(udf.config)
    udf.processed = timezone.now()
    udf.db_view_result = result
    udf.save()
