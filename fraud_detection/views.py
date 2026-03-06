import json
import os
import pickle
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from invoices.models import invoices

from .models import fraud_analysis

try:
    import joblib
    import pandas as pd
    HAS_ML_DEPS = True
except ImportError:
    HAS_ML_DEPS = False



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
	# Note: by default this path looks for fraud_detection/model/fraud_model.pkl
	# But in InvGuard the real model is often saved as invoice_fraud_model.pkl
	real_model_path = os.path.join(settings.BASE_DIR, "fraud_detection", "invoice_fraud_model.pkl")
	
	for path in [model_path, real_model_path]:
		if path and os.path.exists(path):
			try:
				if HAS_ML_DEPS:
					loaded = joblib.load(path)
					if hasattr(loaded, "predict"):
						return {"type": "sklearn", "model": loaded}
			except Exception:
				pass
			try:
				with open(path, "rb") as model_file:
					loaded = pickle.load(model_file)
				if isinstance(loaded, dict):
					return {"type": "dict", "model": loaded}
			except Exception:
				pass
	return {"type": "dict", "model": DEFAULT_MODEL_BUNDLE}


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
	
	vendor_avg_amount = 0.0
	is_new_vendor = 1.0
	amount_ratio = 1.0
	days_since_last_invoice = 30.0
	vendor_risk_score = 50.0
	amount_anomaly_flag = 0.0

	if username and vendor_name:
		from invoices.models import Vendor
		vendor = Vendor.objects.filter(username=username, name__iexact=vendor_name).first()
		if vendor:
			is_new_vendor = 0.0
			vendor_avg_amount = float(vendor.average_amount)
			vendor_risk_score = float(vendor.risk_score)
			
			if vendor_avg_amount > 0:
				amount_ratio = float(amount_float / vendor_avg_amount)
				
			if amount_ratio >= 3.0 and amount_float > 1000.0:
				amount_anomaly_flag = 1.0
				
			if vendor.last_invoice_date:
				try:
					today = datetime.now().date()
					days_since_last_invoice = float((today - vendor.last_invoice_date).days)
				except Exception:
					pass
					
	features.update({
		"vendor_avg_amount": vendor_avg_amount,
		"is_new_vendor": is_new_vendor,
		"amount_ratio": amount_ratio,
		"days_since_last_invoice": days_since_last_invoice,
		"vendor_risk_score": vendor_risk_score,
		"amount_anomaly_flag": amount_anomaly_flag,
	})

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

def _score_from_sklearn(payload, model, features=None):
	if not HAS_ML_DEPS:
		return _score_from_bundle(_extract_features(payload, DEFAULT_MODEL_BUNDLE), DEFAULT_MODEL_BUNDLE)
		
	if features is None:
		features = {}

	# Convert bank account to purely numeric explicitly, because the ML model pipeline expects a float here
	numeric_bank = re.sub(r"\D", "", str(payload.get('bank_account', '')))
	bank_account_num = float(numeric_bank) if numeric_bank else 0.0

	# Try to build a dataframe row based on typical features
	row_dict = {
		'invoice_id': payload.get('invoice_id', 'UNK'),
		'invoice_number': payload.get('invoice_number', ''),
		'vendor_id': 'V000',
		'vendor_name': payload.get('vendor_name', ''),
		'vendor_email': '',
		'vendor_address': '',
		'purchase_order_number': '',
		'item_description': 'Unknown',
		'quantity': 1.0,
		'unit_price': _to_float(payload.get('total_amount'), 0.0),
		'subtotal': _to_float(payload.get('total_amount'), 0.0),
		'tax_amount': 0.0,
		'discount': 0.0,
		'total_amount': _to_float(payload.get('total_amount'), 0.0),
		'currency': payload.get('currency', 'USD'),
		'currency_change_flag': 0.0,
		'bank_account_number': bank_account_num,
		'bank_name': 'Unknown',
		'payment_method': 'Bank Transfer',
		'duplicate_invoice': float(features.get('duplicate_count', 0.0)),
		'bank_changed': 0.0,
		'vendor_avg_amount': float(features.get('vendor_avg_amount', 0.0)),
		'amount_ratio': float(features.get('amount_ratio', 1.0)),
		'invoice_frequency_last30days': 1.0,
		'vendor_risk_score': float(features.get('vendor_risk_score', 50.0)),
		'days_since_last_invoice': float(features.get('days_since_last_invoice', 30.0)),
		'is_new_vendor': float(features.get('is_new_vendor', 1.0)),
		'invoice_day': 1,
		'invoice_month': 1,
		'invoice_year': 2026,
		'due_day': 1,
		'due_month': 1
	}

	date_str = payload.get("invoice_date")
	if date_str:
		try:
			dt = datetime.fromisoformat(date_str)
			row_dict['invoice_day'] = dt.day
			row_dict['invoice_month'] = dt.month
			row_dict['invoice_year'] = dt.year
		except:
			pass
			
	due_str = payload.get("due_date")
	if due_str:
		try:
			dt = datetime.fromisoformat(due_str)
			row_dict['due_day'] = dt.day
			row_dict['due_month'] = dt.month
		except:
			pass

	df = pd.DataFrame([row_dict])
	
	try:
		if hasattr(model, "predict_proba"):
			probas = model.predict_proba(df)
			score = float(probas[0][1]) if probas.shape[1] > 1 else float(probas[0][0])
		else:
			preds = model.predict(df)
			score = 1.0 if preds[0] else 0.0
	except Exception as e:
		score = 0.5 # fallback

	# ---------------------------------------------------------
	# HYBRID AI SYSTEM: Boost ML Score with Hard Fraud Rules
	# ---------------------------------------------------------
	reasons = ["Machine Learning AI Analysis completed."]
	
	if features:
		if features.get("amount_anomaly_flag", 0) == 1.0:
			score += 0.20
			reasons.append(f"Amount {payload.get('currency', 'USD')} {payload.get('total_amount', '0.0')} is unusually high for this historically verified vendor.")
		if features.get("is_new_vendor") == 1.0 and payload.get('vendor_name'):
			score += 0.05
			reasons.append("First-time vendor detected. Risk inherently increased.")
		if features.get("duplicate_count", 0) > 0:
			score = max(score, 0.95)
			reasons.append("Exact Duplicate Invoice Number Detected in System.")
		if features.get("bank_account_suspicious_flag"):
			score += 0.25
			reasons.append("Bank account format is highly suspicious.")
		if features.get("high_amount_flag"):
			score += 0.15
			reasons.append("Total amount exceeds normal bounds.")
		if features.get("missing_vendor_flag"):
			score += 0.15
			reasons.append("Unrecognized or missing vendor name.")
		if features.get("low_ocr_confidence_flag"):
			score += 0.10
			reasons.append("Poor document quality; AI confidence is very low.")

	# Cap score at 1.0 maximum
	score = min(1.0, score)

	high_th = 0.75
	medium_th = 0.45

	if score >= high_th:
		risk_label = "high"
	elif score >= medium_th:
		risk_label = "medium"
	else:
		risk_label = "low"

	if score >= medium_th and len(reasons) == 1:
		reasons.append("High risk hidden patterns flagged by ML model.")

	return {
		"risk_score": round(score, 4),
		"risk_label": risk_label,
		"is_fraud": risk_label in {"high", "medium"},
		"reason": " ".join(reasons),
		"model_version": "hybrid-ml-rules-v2",
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

	model_bundle_info = _load_model_bundle()
	
	if model_bundle_info["type"] == "sklearn":
		features = _extract_features(payload, DEFAULT_MODEL_BUNDLE) # keep fallback features for DB
		score_result = _score_from_sklearn(payload, model_bundle_info["model"], features)
	else:
		model_bundle = model_bundle_info["model"]
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
