from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404

from bank.views import is_admin_or_employee
from core.private_files import serve_private_file

from .models import KYCDocument


@login_required
def kyc_document_download(request, document_id):
    document = get_object_or_404(
        KYCDocument.objects.select_related("kyc_verification__customer__user"),
        id=document_id,
    )
    owner_id = document.kyc_verification.customer.user_id
    allowed = (
        request.user.id == owner_id
        or request.user.is_superuser
        or is_admin_or_employee(request.user)
    )
    if not allowed:
        raise Http404("Document not found")
    return serve_private_file(document.file)
