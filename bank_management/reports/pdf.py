"""The PDF version of the report. Uses ReportLab, like the statement PDFs.

build_sections() prepares the table contents (plain text rows). The layout code below
only draws them, so the numbers always come from the same queries as the page."""
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from bank.models import Bank

from . import loan_services, services

HEADER_COLOR = colors.HexColor("#1f3a5f")
STRIPE_COLOR = colors.HexColor("#f2f5f9")


def _money(value):
    if value is None or value == "":
        return ""
    return f"{Decimal(value):,.2f}"


def _date(value):
    return value.strftime("%d %b %Y")


def build_sections(start, end, branch, role):
    """The tables that go in the PDF, as plain text. Branch summary is for admins only."""
    sections = []

    days, grand = services.totals_by_day(start, end, branch)
    rows = [
        [_date(d["day"]), str(d["deposit_count"]), _money(d["deposit_total"]),
         str(d["withdraw_count"]), _money(d["withdraw_total"]),
         str(d["transfer_count"]), _money(d["transfer_total"])]
        for d in days
    ]
    if rows:
        rows.append([
            "Total", str(grand["deposit_count"]), _money(grand["deposit_total"]),
            str(grand["withdraw_count"]), _money(grand["withdraw_total"]),
            str(grand["transfer_count"]), _money(grand["transfer_total"]),
        ])
    sections.append({
        "title": "Transactions by day",
        "note": "Successful deposits, withdrawals and transfers only. Loan payouts and loan "
                "repayments are in the loans section.",
        "headers": ["Date", "Deposits\ncount", "Deposits\namount", "Withdrawals\ncount",
                    "Withdrawals\namount", "Transfers\ncount", "Transfers\namount"],
        "rows": rows,
        "empty_text": "No successful transactions in this period.",
        "right_cols": (1, 2, 3, 4, 5, 6),
        "bold_last": True,
    })

    sections.append({
        "title": "New customers and accounts",
        "note": "A customer is counted if they have an account in this branch." if branch is not None else "",
        "headers": ["Measure", "Count"],
        "rows": [
            ["New customers", str(services.new_customers(start, end, branch).count())],
            ["New accounts", str(services.new_accounts(start, end, branch).count())],
        ],
        "widths": [4.5, 1.2],
        "right_cols": (1,),
    })

    loan_rows = [
        [measure, str(count), _money(amount)]
        for measure, count, amount in loan_services.loan_summary_rows(start, end, branch)
    ]
    sections.append({
        "title": "Loans",
        "note": "Loan counts and balances are as of the day this report was made. "
                "Payouts and repayments follow the dates above.",
        "headers": ["Measure", "Count", "Amount"],
        "rows": loan_rows,
        "widths": [3.9, 0.9, 1.9],
        "right_cols": (1, 2),
    })

    overdue_rows = [
        [label, str(installments), str(loans), _money(amount)]
        for label, installments, loans, amount in loan_services.overdue_summary_rows(branch)
    ]
    sections.append({
        "title": "Overdue installments by age",
        "note": "Unpaid installments past their due date on active EMI loans, as of today.",
        "headers": ["Age", "Installments", "Loans", "Amount overdue"],
        "rows": overdue_rows,
        "widths": [2.4, 1.3, 1.0, 2.0],
        "right_cols": (1, 2, 3),
        "bold_last": True,
    })

    if role == "admin":
        branch_rows = [
            [f"{r['branch'].name} ({r['branch'].branch_code})", str(r["txn_count"]),
             _money(r["deposit_total"]), _money(r["withdraw_total"]), _money(r["transfer_total"]),
             str(r["new_accounts"]), str(r["new_customers"]),
             str(r["active_loans"]), _money(r["overdue_amount"])]
            for r in loan_services.branch_summary_with_loans(start, end)
        ]
        sections.append({
            "title": "Branch-wise summary",
            "note": "All branches, whatever branch is chosen.",
            "headers": ["Branch", "Txns", "Deposits", "Withdrawals", "Transfers",
                        "New\naccts", "New\ncust.", "Active\nloans", "Overdue\namount"],
            "rows": branch_rows,
            "empty_text": "No branches yet.",
            "widths": [1.4, 0.6, 0.8, 0.8, 0.75, 0.5, 0.5, 0.5, 0.9],
            "right_cols": (1, 2, 3, 4, 5, 6, 7, 8),
            "wrap_first": True,
            "font_size": 7,
        })

    return sections


class NumberedCanvas(canvas.Canvas):
    """Draws 'Page x of y' on every page (the total is only known at the end)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.grey)
            self.drawRightString(A4[0] - 0.75 * inch, 0.5 * inch, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def _styles():
    base = getSampleStyleSheet()
    body = base["BodyText"]
    return {
        "title": base["Title"],
        "h2": base["Heading2"],
        "body": body,
        "note": ParagraphStyle("note", parent=body, fontSize=8, leading=10, textColor=colors.HexColor("#555555")),
        "cell": ParagraphStyle("cell", parent=body, fontSize=7, leading=9),
    }


def _section_flowables(section, styles):
    items = [Paragraph(escape(section["title"]), styles["h2"])]
    if section.get("note"):
        items.append(Paragraph(escape(section["note"]), styles["note"]))
        items.append(Spacer(1, 4))

    rows = section["rows"]
    if not rows:
        items.append(Paragraph(escape(section.get("empty_text", "Nothing to show for this period.")), styles["body"]))
    else:
        data = [section["headers"]]
        for row in rows:
            row = list(row)
            if section.get("wrap_first"):
                row[0] = Paragraph(escape(str(row[0])), styles["cell"])
            data.append(row)
        widths = [w * inch for w in section["widths"]] if section.get("widths") else None
        font_size = section.get("font_size", 8)

        table = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_COLOR),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, STRIPE_COLOR]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for col in section.get("right_cols", ()):
            style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
        if section.get("bold_last"):
            style.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
        table.setStyle(TableStyle(style))
        items.append(table)

    items.append(Spacer(1, 14))
    return items


def pdf_response(start, end, branch, role):
    if branch is not None:
        bank_name = branch.bank.name
    else:
        bank_name = " / ".join(Bank.objects.order_by("name").values_list("name", flat=True)) or "Bank"
    branch_label = branch.name if branch is not None else "All branches"
    generated = timezone.localtime().strftime("%d %b %Y, %H:%M")

    styles = _styles()
    story = [
        Paragraph(escape(bank_name), styles["title"]),
        Paragraph("Bank report", styles["h2"]),
        Paragraph(f"Period: {_date(start)} to {_date(end)}", styles["body"]),
        Paragraph(f"Branch: {escape(branch_label)}", styles["body"]),
        Paragraph(f"Generated: {generated}", styles["note"]),
        Spacer(1, 12),
    ]
    for section in build_sections(start, end, branch, role):
        story.extend(_section_flowables(section, styles))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=f"{bank_name} - Bank report",
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.8 * inch,
    )
    doc.build(story, canvasmaker=NumberedCanvas)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="bank_report_{start}_{end}.pdf"'
    return response