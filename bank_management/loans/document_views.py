from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404

from bank.views import is_admin_or_employee
from core.private_files import serve_private_file

from .models import LoanDocument
from .views import _owns_loan


@login_required
def loan_document_download(request, document_id):
    document = get_object_or_404(
        LoanDocument.objects.select_related("loan"),
        id=document_id,
    )
    allowed = (
        _owns_loan(request.user, document.loan)
        or request.user.is_superuser
        or is_admin_or_employee(request.user)
    )
    if not allowed:
        raise Http404("Document not found")
    return serve_private_file(document.file)
