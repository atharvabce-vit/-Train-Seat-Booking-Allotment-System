import base64
from io import BytesIO

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BLUE = colors.HexColor("#12355b")
LIGHT = colors.HexColor("#eef2f7")


def qr_png(text, box_size=6):
    image = qrcode.make(text, box_size=box_size, border=2)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def qr_data_uri(text):
    buffer = qr_png(text, box_size=8)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_ticket_pdf(record, verify_url, class_names=None, berth_names=None):
    class_names = class_names or {}
    berth_names = berth_names or {}
    booking = record["booking"]
    passengers = record["passengers"]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"E-Ticket {booking['pnr']}",
    )

    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title2", parent=styles["Title"], fontSize=18, textColor=BLUE)
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=9, textColor=colors.grey)

    story = [
        Paragraph("RailYatra - Electronic Reservation Slip", title),
        Paragraph("This is a computer generated ticket. Carry a valid photo ID.", small),
        Spacer(1, 6 * mm),
    ]

    header = Table(
        [
            ["PNR", booking["pnr"], "Status", str(booking["status"]).upper()],
            ["Train", f"{booking['train_number']} - {booking['train_name']}", "Class", class_names.get(booking["class_code"], booking["class_code"])],
            ["From", f"{booking['from_name']} ({booking['from_city']})", "To", f"{booking['to_name']} ({booking['to_city']})"],
            ["Boarding", f"{booking['depart_time'] or '--'} (+{booking['from_day']}d)", "Arrival", f"{booking['arrive_time'] or '--'} (+{booking['to_day']}d)"],
            ["Travel date", booking["travel_date"], "Quota", "Tatkal" if booking["quota"] == "TQ" else "General"],
            ["Distance", f"{booking['distance_km']} km", "Fare", f"INR {booking['total_fare']}"],
        ],
        colWidths=[26 * mm, 68 * mm, 22 * mm, 60 * mm],
    )
    header.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (1, 0), BLUE),
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story += [header, Spacer(1, 6 * mm)]

    rows = [["#", "Name", "Age", "Gender", "Coach", "Seat", "Berth"]]
    for index, passenger in enumerate(passengers, start=1):
        rows.append(
            [
                str(index),
                passenger["name"],
                str(passenger["age"]),
                passenger["gender"],
                passenger["coach_name"] or "-",
                str(passenger["seat_number"] or "-"),
                berth_names.get(passenger["berth_type"] or "", passenger["berth_type"] or "-"),
            ]
        )
    table = Table(rows, colWidths=[10 * mm, 50 * mm, 14 * mm, 20 * mm, 22 * mm, 18 * mm, 40 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story += [table, Spacer(1, 8 * mm)]

    qr_image = Image(qr_png(verify_url), width=34 * mm, height=34 * mm)
    footer = Table(
        [[qr_image, Paragraph(
            f"Scan the QR code or visit:<br/><b>{verify_url}</b><br/>"
            "to verify this ticket online.", styles["Normal"])]],
        colWidths=[40 * mm, 140 * mm],
    )
    footer.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(footer)

    doc.build(story)
    buffer.seek(0)
    return buffer
