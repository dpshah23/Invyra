import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output

from django.shortcuts import redirect, render
from django.test import Client
from django.urls import reverse

from .models import invoices, blockchain_records
from .blockchain_utils import record_invoice_on_blockchain

# Configure pytesseract to find tesseract binary
import os
possible_tesseract_paths = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Users\dpsha\AppData\Local\Tesseract-OCR\tesseract.exe",
]

for path in possible_tesseract_paths:
    if os.path.exists(path):
        pytesseract.pytesseract.tesseract_cmd = path
        break


def _sorted_lines(tokens, y_tolerance=12):
    lines = []
    for token in sorted(tokens, key=lambda item: (item["y"], item["x"])):
        attached = False
        for line in lines:
            if abs(line["y"] - token["y"]) <= y_tolerance:
                line["tokens"].append(token)
                attached = True
                break
        if not attached:
            lines.append({"y": token["y"], "tokens": [token]})

    for line in lines:
        line["tokens"] = sorted(line["tokens"], key=lambda item: item["x"])
        line["text"] = " ".join(item["text"] for item in line["tokens"])

    return sorted(lines, key=lambda item: item["y"])


def _ocr_extract_with_coordinates(uploaded_file):
    image = Image.open(uploaded_file)
    image = ImageOps.grayscale(image)

    data = pytesseract.image_to_data(image, output_type=Output.DICT)
    tokens = []
    confidences = []

    for idx, raw_text in enumerate(data.get("text", [])):
        text = (raw_text or "").strip()
        if not text:
            continue

        try:
            conf = float(data.get("conf", ["-1"])[idx])
        except (TypeError, ValueError):
            conf = -1

        token = {
            "text": text,
            "x": int(data.get("left", [0])[idx]),
            "y": int(data.get("top", [0])[idx]),
            "w": int(data.get("width", [0])[idx]),
            "h": int(data.get("height", [0])[idx]),
            "conf": conf,
        }
        tokens.append(token)

        if conf >= 0:
            confidences.append(conf)

    avg_confidence = (sum(confidences) / len(confidences) / 100) if confidences else 0.0
    full_text = "\n".join(line["text"] for line in _sorted_lines(tokens))
    return {
        "tokens": tokens,
        "full_text": full_text,
        "avg_confidence": round(avg_confidence, 4),
    }


def _find_line_value(lines, keywords):
    for line in lines:
        lowered = line["text"].lower()
        for keyword in keywords:
            key = keyword.lower()
            if key in lowered:
                match = re.search(rf"{re.escape(key)}\s*[:#\-]?\s*(.+)$", lowered)
                if match and match.group(1).strip():
                    return match.group(1).strip()
                split_parts = re.split(r"[:#\-]", line["text"], maxsplit=1)
                if len(split_parts) == 2 and split_parts[1].strip():
                    return split_parts[1].strip()
    return ""


def _parse_amount(value):
    if value is None:
        return Decimal("0.00")

    candidate = str(value)
    candidate = candidate.replace(",", "")
    candidate = candidate.replace(" ", "")
    candidate = candidate.replace("O", "0").replace("o", "0")
    candidate = candidate.replace("l", "1")

    match = re.search(r"(\d+(?:\.\d{1,2})?)", candidate)
    if not match:
        return Decimal("0.00")

    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return Decimal("0.00")


def _parse_date(value):
    if not value:
        return None

    candidate = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


def _detect_invoice_fields(ocr_result):
    tokens = ocr_result["tokens"]
    lines = _sorted_lines(tokens)
    full_text = ocr_result["full_text"]

    invoice_number = _find_line_value(lines, ["invoice no", "invoice number", "invoice #", "inv no"])
    if not invoice_number:
        pattern = re.search(r"(?:invoice\s*(?:no|number|#)?\s*[:#\-]?\s*)([a-zA-Z0-9\-/]+)", full_text, re.I)
        invoice_number = pattern.group(1) if pattern else ""

    total_raw = _find_line_value(lines, ["grand total", "total amount", "total", "amount due"])
    if not total_raw:
        total_match = re.search(r"(?:total(?:\s+amount)?|amount\s+due)\s*[:#\-]?\s*([$€£₹]?[\d,]+(?:\.\d{1,2})?)", full_text, re.I)
        total_raw = total_match.group(1) if total_match else ""

    vendor_name = _find_line_value(lines, ["vendor", "supplier", "bill from", "from"])
    if not vendor_name and lines:
        # Use first non-empty line as fallback vendor hint.
        vendor_name = lines[0]["text"][:255]

    invoice_date_raw = _find_line_value(lines, ["invoice date", "date"])
    due_date_raw = _find_line_value(lines, ["due date", "payment due", "due"])
    bank_account_raw = _find_line_value(lines, ["bank account", "account number", "iban", "a/c"])

    currency = "USD"
    if re.search(r"₹|\bINR\b", full_text, re.I):
        currency = "INR"
    elif re.search(r"€|\bEUR\b", full_text, re.I):
        currency = "EUR"
    elif re.search(r"£|\bGBP\b", full_text, re.I):
        currency = "GBP"

    amount = _parse_amount(total_raw)
    normalized = {
        "invoice_number": invoice_number.strip(),
        "vendor_name": vendor_name.strip(),
        "invoice_date": _parse_date(invoice_date_raw),
        "due_date": _parse_date(due_date_raw),
        "total_amount": amount,
        "currency": currency,
        "bank_account": bank_account_raw.strip(),
        "ocr_confidence": ocr_result["avg_confidence"],
        "raw_text": full_text,
    }
    return normalized


def _call_detect_risk_api(request, payload):
    client = Client(HTTP_HOST=request.get_host())
    response = client.post(
        reverse("detect_risk"),
        data=json.dumps(payload),
        content_type="application/json",
    )

    if response.status_code >= 400:
        try:
            error_data = response.json()
        except Exception:
            error_data = {"error": response.content.decode("utf-8", errors="ignore")}
        return {"ok": False, "status_code": response.status_code, "data": error_data}

    return {"ok": True, "status_code": response.status_code, "data": response.json()}


def invoice_upload(request):
    username = request.session.get("username", "")
    guest_session_id = request.session.get("guest_session_id", "")
    is_guest = not username
    
    if request.method == "GET":
        context = {
            "is_guest": is_guest,
            "guest_upload_limit_reached": False
        }
        # Show plan limit info to logged-in users
        if not is_guest:
            plan_limit = request.session.get("plan_limit", 10)
            user_invoice_count = invoices.objects.filter(username=username).count()
            context["plan_limit"] = plan_limit
            context["invoice_count"] = user_invoice_count
            context["remaining_uploads"] = max(0, plan_limit - user_invoice_count)
        return render(request, "invoice_upload.html", context)
    
    # Guest upload limit: max 1 invoice per guest session
    if is_guest:
        guest_invoice_count = invoices.objects.filter(guest_session_id=guest_session_id).count()
        if guest_invoice_count >= 1:
            return render(request, "invoice_upload.html", {
                "error": "Guest users can upload a maximum of 1 invoice. Please sign in to upload more.",
                "guest_upload_limit_reached": True,
                "is_guest": is_guest
            })
    else:
        # Logged-in user: check plan limit
        plan_limit = request.session.get("plan_limit", 10)
        user_invoice_count = invoices.objects.filter(username=username).count()
        
        if user_invoice_count >= plan_limit:
            return render(request, "invoice_upload.html", {
                "error": f"You have reached your plan limit of {plan_limit} invoices. Please upgrade your plan to upload more.",
                "plan_limit_reached": True,
                "is_guest": is_guest,
                "plan_limit": plan_limit,
                "invoice_count": user_invoice_count,
                "remaining_uploads": 0
            })

    file = request.FILES.get("invoice")
    if not file:
        return render(request, "invoice_upload.html", {
            "error": "Please upload an invoice image.",
            "is_guest": is_guest
        })

    if file.content_type not in ["image/jpeg", "image/png", "image/jpg"]:
        return render(
            request,
            "invoice_upload.html",
            {
                "error": "Only JPG/PNG image invoices are supported in this OCR flow.",
                "is_guest": is_guest
            },
        )

    try:
        ocr_result = _ocr_extract_with_coordinates(file)
    except Exception as exc:
        return render(request, "invoice_upload.html", {
            "error": f"OCR failed: {str(exc)}",
            "is_guest": is_guest
        })

    extracted = _detect_invoice_fields(ocr_result)

    invoice_number = extracted["invoice_number"] or f"AUTO-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    # For guest users, store guest_session_id; for logged-in users, store username
    invoice_obj = invoices.objects.create(
        username=username if not is_guest else "",
        guest_session_id=guest_session_id if is_guest else "",
        invoice_number=invoice_number,
        vendor_name=extracted["vendor_name"],
        invoice_date=extracted["invoice_date"],
        due_date=extracted["due_date"],
        amount=extracted["total_amount"],
        currency=extracted["currency"],
        bank_account=extracted["bank_account"],
        raw_text=extracted["raw_text"],
        extracted_json={
            "invoice_number": invoice_number,
            "vendor_name": extracted["vendor_name"],
            "invoice_date": extracted["invoice_date"].isoformat() if extracted["invoice_date"] else None,
            "due_date": extracted["due_date"].isoformat() if extracted["due_date"] else None,
            "total_amount": str(extracted["total_amount"]),
            "currency": extracted["currency"],
            "bank_account": extracted["bank_account"],
        },
        ocr_confidence=extracted["ocr_confidence"],
        status="parsed",
    )

    fraud_payload = {
        "invoice_id": invoice_obj.id,
        "username": username,
        "invoice_number": invoice_number,
        "vendor_name": extracted["vendor_name"],
        "invoice_date": extracted["invoice_date"].isoformat() if extracted["invoice_date"] else None,
        "due_date": extracted["due_date"].isoformat() if extracted["due_date"] else None,
        "total_amount": str(extracted["total_amount"]),
        "currency": extracted["currency"],
        "bank_account": extracted["bank_account"],
        "ocr_confidence": extracted["ocr_confidence"],
    }

    risk_call = _call_detect_risk_api(request, fraud_payload)
    if risk_call["ok"]:
        risk_data = risk_call["data"]
        invoice_obj.risk_score = risk_data.get("risk_score")
        invoice_obj.risk_label = risk_data.get("risk_label", "unknown")
        invoice_obj.fraud_reason = risk_data.get("reason", "")
        invoice_obj.status = "flagged" if risk_data.get("is_fraud") else "processed"
        invoice_obj.save(update_fields=["risk_score", "risk_label", "fraud_reason", "status", "updated_at"])
    else:
        invoice_obj.status = "risk_failed"
        invoice_obj.save(update_fields=["status", "updated_at"])

    # Record invoice on blockchain
    blockchain_result = None
    blockchain_error = None
    try:
        blockchain_data = {
            'invoice_number': invoice_number,
            'vendor_name': extracted["vendor_name"],
            'total_amount': str(extracted["total_amount"]),
            'risk_score': str(invoice_obj.risk_score) if invoice_obj.risk_score else '0.0',
            'invoice_date': extracted["invoice_date"].isoformat() if extracted["invoice_date"] else '',
            'raw_text': extracted["raw_text"],
        }
        
        blockchain_result = record_invoice_on_blockchain(blockchain_data)
        
        if blockchain_result['success']:
            # Save blockchain transaction record
            blockchain_records.objects.create(
                invoice_id=invoice_obj,
                transaction_hash=blockchain_result['tx_hash'],
                invoice_hash=blockchain_result['document_hash'],
                network='ganache',
                block_number=blockchain_result['block_number']
            )
            invoice_obj.status = "blockchain_recorded"
            invoice_obj.save(update_fields=["status", "updated_at"])
        else:
            blockchain_error = blockchain_result.get('error', 'Unknown blockchain error')
    except Exception as e:
        blockchain_error = str(e)

    context = {
        "ocr_text": extracted["raw_text"],
        "extracted_json": json.dumps(
            {
                "invoice_number": invoice_number,
                "vendor_name": extracted["vendor_name"],
                "invoice_date": extracted["invoice_date"].isoformat() if extracted["invoice_date"] else None,
                "due_date": extracted["due_date"].isoformat() if extracted["due_date"] else None,
                "total_amount": str(extracted["total_amount"]),
                "currency": extracted["currency"],
                "bank_account": extracted["bank_account"],
                "ocr_confidence": extracted["ocr_confidence"],
            },
            indent=2,
        ),
        "risk_result": risk_call["data"],
        "invoice_obj": invoice_obj,
        "risk_error": None if risk_call["ok"] else risk_call["data"],
        "blockchain_result": blockchain_result,
        "blockchain_error": blockchain_error,
        "is_guest": is_guest,
    }
    
    # Add plan limit info for logged-in users
    if not is_guest:
        plan_limit = request.session.get("plan_limit", 10)
        user_invoice_count = invoices.objects.filter(username=username).count()
        context["plan_limit"] = plan_limit
        context["invoice_count"] = user_invoice_count
        context["remaining_uploads"] = max(0, plan_limit - user_invoice_count)
    
    return render(request, "invoice_upload.html", context)
        
