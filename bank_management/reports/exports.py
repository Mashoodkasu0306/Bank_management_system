"""The export layer. Every report builds (headers, rows) and hands them to a function
here. CSV is first; a PDF function can be added next to csv_response later and use the
same headers and rows."""
import csv

from django.http import HttpResponse

_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _safe(value):
    """Stops Excel from running text such as '=1+1' as a formula."""
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value
    return value


def csv_response(filename, headers, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_safe(value) for value in row])
    return response