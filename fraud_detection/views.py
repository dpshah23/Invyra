import json
import os
import pickle
import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from invoices.models import invoices

from .models import fraud_analysis


DEFAULT_MODEL_BUNDLE = {
	"version": "demo-rule-v1",
	"weights": {
		"high_amount_flag": 0.45,
		"missing_vendor_flag": 0.15,
		"missing_invoice_number_flag": 0.2,
		"bank_account_suspicious_flag": 0.1,
		"low_ocr_confidence_flag": 0.1,
		"duplicate_invoice_number_flag": 0.2,
	},
	"thresholds": {
		"amount_high": 10000.0,
		"high": 0.75,
		"medium": 0.45,
	},
}


def _to_decimal(value, default=Decimal("0.00")):
	if value is None:
		return default

	candidate = str(value).strip().replace(",", "")
	candidate = candidate.replace(" ", "")
	candidate = candidate.replace("O", "0").replace("o", "0")

	try:
		return Decimal(candidate)
	except InvalidOperation:
		match = re.search(r"(\d+(?:\.\d{1,2})?)", candidate)
		if not match:
			return default
		return Decimal(match.group(1))


def _to_float(value, default=0.0):
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


@lru_cache(maxsize=1)
def _load_model_bundle():
	model_path = getattr(settings, "FRAUD_MODEL_PICKLE_PATH", "")
	if model_path and os.path.exists(model_path):
		try:
			with open(model_path, "rb") as model_file:
				loaded = pickle.load(model_file)
			if isinstance(loaded, dict):
				return loaded
		except Exception:
			pass
	return DEFAULT_MODEL_BUNDLE


def _extract_features(payload, model_bundle):
	amount = _to_decimal(payload.get("total_amount"), Decimal("0.00"))
	amount_float = float(amount)
	threshold_amount = _to_float(model_bundle.get("thresholds", {}).get("amount_high"), 10000.0)

	invoice_number = str(payload.get("invoice_number") or "").strip()
	vendor_name = str(payload.get("vendor_name") or "").strip()
	bank_account = str(payload.get("bank_account") or "").strip()
	username = str(payload.get("username") or "").strip()
	ocr_confidence = _to_float(payload.get("ocr_confidence"), 0.0)

	duplicate_count = 0
	if invoice_number:
		duplicate_qs = invoices.objects.filter(invoice_number=invoice_number)
		if username:
			duplicate_qs = duplicate_qs.exclude(username=username)
		duplicate_count = duplicate_qs.count()

	numeric_bank = re.sub(r"\D", "", bank_account)
	features = {
		"amount": amount_float,
		"ocr_confidence": ocr_confidence,
		"high_amount_flag": 1.0 if amount_float >= threshold_amount else 0.0,
		"missing_vendor_flag": 1.0 if not vendor_name else 0.0,
		"missing_invoice_number_flag": 1.0 if not invoice_number else 0.0,
		"bank_account_suspicious_flag": 1.0 if bank_account and len(numeric_bank) < 8 else 0.0,
		"low_ocr_confidence_flag": 1.0 if ocr_confidence < 0.65 else 0.0,
		"duplicate_invoice_number_flag": 1.0 if duplicate_count > 0 else 0.0,
		"duplicate_count": duplicate_count,
	}
	return features


def _score_from_bundle(features, model_bundle):
	weights = model_bundle.get("weights", {})
	thresholds = model_bundle.get("thresholds", {})

	score = 0.0
	for key, weight in weights.items():
		score += _to_float(weight) * _to_float(features.get(key, 0.0))
	score = max(0.0, min(1.0, score))

	high_th = _to_float(thresholds.get("high"), 0.75)
	medium_th = _to_float(thresholds.get("medium"), 0.45)

	if score >= high_th:
		risk_label = "high"
	elif score >= medium_th:
		risk_label = "medium"
	else:
		risk_label = "low"

	reasons = []
	if features.get("high_amount_flag"):
		reasons.append("amount is unusually high")
	if features.get("duplicate_invoice_number_flag"):
		reasons.append("invoice number appears in previous uploads")
	if features.get("low_ocr_confidence_flag"):
		reasons.append("ocr confidence is low")
	if features.get("missing_vendor_flag"):
		reasons.append("vendor name is missing")
	if features.get("bank_account_suspicious_flag"):
		reasons.append("bank account format looks suspicious")

	if not reasons:
		reasons.append("no major fraud indicators found")

	return {
		"risk_score": round(score, 4),
		"risk_label": risk_label,
		"is_fraud": risk_label in {"high", "medium"},
		"reason": "; ".join(reasons),
		"model_version": str(model_bundle.get("version", "demo-rule-v1")),
	}


@csrf_exempt
@require_POST
def detect_risk(request):
	try:
		payload = json.loads(request.body.decode("utf-8"))
	except (json.JSONDecodeError, UnicodeDecodeError):
		return JsonResponse({"error": "Invalid JSON payload"}, status=400)

	required_fields = ["username", "invoice_number", "total_amount", "currency"]
	missing = [field for field in required_fields if not str(payload.get(field, "")).strip()]
	if missing:
		return JsonResponse({"error": f"Missing required fields: {', '.join(missing)}"}, status=400)

	model_bundle = _load_model_bundle()
	features = _extract_features(payload, model_bundle)
	score_result = _score_from_bundle(features, model_bundle)

	record = fraud_analysis.objects.create(
		username=str(payload.get("username", "")).strip(),
		invoice_id=payload.get("invoice_id") if payload.get("invoice_id") else None,
		invoice_number=str(payload.get("invoice_number", "")).strip(),
		vendor_name=str(payload.get("vendor_name", "")).strip(),
		risk_score=score_result["risk_score"],
		risk_label=score_result["risk_label"],
		is_fraud=score_result["is_fraud"],
		reason=score_result["reason"],
		model_version=score_result["model_version"],
		features=features,
		payload=payload,
	)

	invoice_id = payload.get("invoice_id")
	if invoice_id:
		invoices.objects.filter(id=invoice_id).update(
			risk_score=score_result["risk_score"],
			risk_label=score_result["risk_label"],
			fraud_reason=score_result["reason"],
			status="flagged" if score_result["is_fraud"] else "processed",
		)

	response = {
		"analysis_id": record.id,
		"invoice_id": invoice_id,
		"invoice_number": payload.get("invoice_number"),
		"risk_score": score_result["risk_score"],
		"risk_label": score_result["risk_label"],
		"is_fraud": score_result["is_fraud"],
		"reason": score_result["reason"],
		"model_version": score_result["model_version"],
		"features": features,
	}
	return JsonResponse(response, status=200)
