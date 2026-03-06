import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pytesseract
from PIL import Image, ImageOps
from pytesseract import Output

from django.shortcuts import redirect, render, get_object_or_404
from django.test import Client
from django.urls import reverse

from .models import invoices, blockchain_records
from .blockchain_utils import record_invoice_on_blockchain, calculate_document_hash, load_contract

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


from PIL import Image, ImageOps, ImageEnhance, ImageFilter

def _ocr_extract_with_coordinates(uploaded_file):
    image = Image.open(uploaded_file)
    
    # Standardize image mode
    if image.mode != 'RGB':
        image = image.convert('RGB')
        
    # Convert to grayscale
    image = ImageOps.grayscale(image)
    
    # Increase image contrast to make text stand out against background
    enhancer_contrast = ImageEnhance.Contrast(image)
    image = enhancer_contrast.enhance(2.0)
    
    # Increase image sharpness
    enhancer_sharpness = ImageEnhance.Sharpness(image)
    image = enhancer_sharpness.enhance(1.5)
    
    # Apply a manual threshold to binarize the image (remove gray shadows)
    # Any pixel > 140 becomes pure white, <= 140 becomes pure black
    image = image.point(lambda p: 255 if p > 140 else 0, mode='1')

    # Use Page Segmentation Mode 6 (Assume a single uniform block of text)
    # which performs much better on sparse tables/invoices than the default PSM 3.
    custom_config = r'--oem 3 --psm 6'
    data = pytesseract.image_to_data(image, output_type=Output.DICT, config=custom_config)
    
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


from django_ratelimit.decorators import ratelimit

@ratelimit(key='ip', rate='5/m', block=True)
def invoice_upload(request):
    username = request.session.get("username", "")
    guest_session_id = request.session.get("guest_session_id", "")
    is_guest = not username
    
    if request.method == "GET":
        if not is_guest:
            from auth1.views import get_dashboard_context
            dashboard_context = get_dashboard_context(username)
            plan_limit = int(request.session.get("plan_limit", 10))
            user_invoice_count = dashboard_context["total_invoices"]
            dashboard_context["plan_limit"] = plan_limit
            dashboard_context["invoice_count"] = user_invoice_count
            dashboard_context["remaining_uploads"] = max(0, plan_limit - user_invoice_count)
            dashboard_context["name"] = request.session.get('name', '')
            dashboard_context["active_tab"] = "upload"
            return render(request, "dashboard.html", dashboard_context)
            
        context = {
            "is_guest": is_guest,
            "guest_upload_limit_reached": False
        }
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
        MAXINT = 2**31 - 1
        from auth1.views import get_dashboard_context
        if request.session.get(plan_limit)=="unlimited":
            plan_limit=MAXINT
        else:
            plan_limit = int(request.session.get("plan_limit", 10))
        user_invoice_count = invoices.objects.filter(username=username).count()
        
        if user_invoice_count >= plan_limit:
            dashboard_context = get_dashboard_context(username)
            dashboard_context["error"] = f"You have reached your plan limit of {plan_limit} invoices. Please upgrade your plan to upload more."
            dashboard_context["plan_limit_reached"] = True
            dashboard_context["active_tab"] = "upload"
            dashboard_context["plan_limit"] = plan_limit
            dashboard_context["invoice_count"] = user_invoice_count
            dashboard_context["remaining_uploads"] = 0
            dashboard_context["name"] = request.session.get('name', '')
            return render(request, "dashboard.html", dashboard_context)

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

    # Prepare blockchain data for MetaMask frontend signing
    blockchain_pending_data = None
    blockchain_error = None
    blockchain_result = None
    
    if invoice_obj.status != "flagged" and invoice_obj.status != "risk_failed" and invoice_obj.status != "rejected":
        try:
            blockchain_data = {
                'invoice_number': invoice_number,
                'vendor_name': extracted["vendor_name"],
                'total_amount': str(extracted["total_amount"]),
                'risk_score': str(invoice_obj.risk_score) if invoice_obj.risk_score else '0.0',
                'invoice_date': extracted["invoice_date"].isoformat() if extracted["invoice_date"] else '',
                'raw_text': extracted["raw_text"],
            }
            
            # Instead of backend signing, calculate hash and pass to frontend
            doc_hash = calculate_document_hash(blockchain_data)
            invoice_obj.status = "blockchain_pending"
            invoice_obj.save(update_fields=["status", "updated_at"])
            
            # Fetch Contract info for JS
            contract, w3 = load_contract()
            
            blockchain_pending_data = {
                'invoice_id': invoice_obj.id,
                'invoice_number': blockchain_data['invoice_number'],
                'vendor_name': blockchain_data['vendor_name'],
                'total_amount': blockchain_data['total_amount'],
                'risk_score': blockchain_data['risk_score'],
                'document_hash': doc_hash,
                'contract_address': contract.address,
                'contract_abi': json.dumps(contract.abi)
            }
            
        except Exception as e:
            blockchain_error = str(e)
            invoice_obj.status = "blockchain_failed"
            invoice_obj.save(update_fields=["status", "updated_at"])

    # UPDATE VENDOR ML HISTORY
    if not is_guest and invoice_obj.status in ["processed", "blockchain_recorded", "blockchain_failed"] and invoice_obj.vendor_name:
        try:
            from invoices.models import Vendor
            amount_val = float(invoice_obj.amount)
            vendor_obj, created = Vendor.objects.get_or_create(
                username=username,
                name=invoice_obj.vendor_name,
                defaults={
                    'total_invoices': 0,
                    'total_amount_processed': 0,
                    'average_amount': 0,
                    'risk_score': 50.0,
                }
            )
            vendor_obj.total_invoices += 1
            vendor_obj.total_amount_processed = float(vendor_obj.total_amount_processed) + amount_val
            vendor_obj.average_amount = vendor_obj.total_amount_processed / vendor_obj.total_invoices
            
            if invoice_obj.invoice_date:
                vendor_obj.last_invoice_date = invoice_obj.invoice_date
            elif not vendor_obj.last_invoice_date:
                vendor_obj.last_invoice_date = datetime.now().date()
            
            # Reduce risk score for successful invoices, raising trust in the vendor over time
            vendor_obj.risk_score = max(10.0, vendor_obj.risk_score - 2.0)
            vendor_obj.is_trusted = vendor_obj.risk_score <= 20.0
            vendor_obj.save()
        except Exception:
            pass

    # Add plan limit info for logged-in users
    if not is_guest:
        from auth1.views import get_dashboard_context
        # Render the dashboard with upload results
        dashboard_context = get_dashboard_context(username)
        dashboard_context.update({
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
            "blockchain_pending_data": blockchain_pending_data,
            "blockchain_error": blockchain_error,
            "is_guest": is_guest,
            "active_tab": "upload"
        })
        
        plan_limit = int(request.session.get("plan_limit", 10))
        user_invoice_count = dashboard_context["total_invoices"]
        dashboard_context["plan_limit"] = plan_limit
        dashboard_context["invoice_count"] = user_invoice_count
        dashboard_context["remaining_uploads"] = max(0, plan_limit - user_invoice_count)
        dashboard_context["name"] = request.session.get('name', '')
        
        return render(request, "dashboard.html", dashboard_context)
    else:
        # Fallback for guests: still render the standalone page
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
        return render(request, "invoice_upload.html", context)

def invoice_detail(request, invoice_id):
    username = request.session.get("username", "")
    is_guest = not username
    
    if is_guest:
        guest_session_id = request.session.get("guest_session_id", "")
        if not guest_session_id:
            return redirect('/auth/login/')
        invoice_obj = get_object_or_404(invoices, id=invoice_id, guest_session_id=guest_session_id)
    else:
        invoice_obj = get_object_or_404(invoices, id=invoice_id, username=username)

    bc_record = blockchain_records.objects.filter(invoice_id=invoice_obj).first()

    context = {
        'invoice': invoice_obj,
        'blockchain_record': bc_record,
        'extracted_json': json.dumps(invoice_obj.extracted_json, indent=2) if invoice_obj.extracted_json else None
    }
    return render(request, 'invoice_details.html', context)


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@ratelimit(key='ip', rate='10/m', block=True)
def save_blockchain_record(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            invoice_id = data.get("invoice_id")
            tx_hash = data.get("tx_hash")
            document_hash = data.get("document_hash")
            
            username = request.session.get("username", "")
            guest_session_id = request.session.get("guest_session_id", "")
            
            if username:
                invoice_obj = get_object_or_404(invoices, id=invoice_id, username=username)
            else:
                invoice_obj = get_object_or_404(invoices, id=invoice_id, guest_session_id=guest_session_id)
            
            # Save blockchain transaction record
            blockchain_records.objects.create(
                invoice_id=invoice_obj,
                transaction_hash=tx_hash,
                invoice_hash=document_hash,
                network='MetaMask',
                block_number=0 # Could be passed from frontend if needed
            )
            
            invoice_obj.status = "blockchain_recorded"
            invoice_obj.save(update_fields=["status", "updated_at"])
            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})
    return JsonResponse({"status": "error", "message": "Invalid request"})
