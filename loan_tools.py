"""Tools the loan assistant can call: a payment calculator and the Telegram lead hand-off."""

import json

import telegram_bot

# Illustrative annual interest rate for estimates. The assistant always calls
# the result an estimate; a loan officer confirms the real rate.
SAMPLE_ANNUAL_RATE = 8.0
MAX_LEADS_PER_CONVERSATION = 3

TOOLS = [
    {
        "name": "estimate_monthly_payment",
        "description": (
            "Calculate the monthly installment and total interest for a loan with equal monthly "
            "payments. Use this instead of doing the arithmetic yourself whenever you quote a payment."
        ),
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "loan_amount": {"type": "number", "description": "Amount borrowed, in the loan currency"},
                "annual_rate_percent": {"type": "number", "description": f"Annual interest rate in percent; use {SAMPLE_ANNUAL_RATE} unless the customer gives one"},
                "term_months": {"type": "integer", "description": "Loan term in months"},
            },
            "required": ["loan_amount", "annual_rate_percent", "term_months"],
            "additionalProperties": False,
        },
    },
    {
        "name": "send_loan_lead_to_telegram",
        "description": (
            "Send the customer's loan request to the PPCBank loan team's Telegram chat so a loan "
            "officer can contact them. Call it only after you have every required detail, have read "
            "the details back to the customer, and the customer has confirmed they are correct and "
            "agreed to be contacted. Call it once per request; if it fails, tell the customer."
        ),
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "full_name": {"type": "string", "description": "Customer's full name, as they gave it (Khmer or Latin script)"},
                "phone": {"type": "string", "description": "Customer's phone number"},
                "address": {"type": "string", "description": "Village/sangkat, district/khan and province or city"},
                "loan_type": {"type": "string", "description": "e.g. Home loan, Car loan, Business loan, Personal loan"},
                "loan_amount": {"type": "number", "description": "Amount requested"},
                "currency": {"type": "string", "enum": ["USD", "KHR"]},
                "term_months": {"type": "integer", "description": "Requested term in months"},
                "monthly_income": {"type": "number", "description": "Customer's monthly income, same currency"},
                "estimated_monthly_payment": {"type": "number", "description": "Estimate you quoted, if any"},
                "notes": {"type": "string", "description": "Anything else useful for the officer (purpose, employer, best time to call)"},
            },
            "required": ["full_name", "phone", "address", "loan_type", "loan_amount", "currency", "term_months", "monthly_income"],
            "additionalProperties": False,
        },
    },
]


class ToolInputError(ValueError):
    """The model's tool input did not match the schema."""


def _check(data: dict, schema: dict) -> dict:
    """Validate a parsed tool input against its (simple, flat) JSON schema."""
    if not isinstance(data, dict):
        raise ToolInputError("input must be an object")
    props = schema["properties"]
    unknown = set(data) - set(props)
    if unknown:
        raise ToolInputError(f"unknown fields: {sorted(unknown)}")
    missing = [k for k in schema["required"] if data.get(k) in (None, "")]
    if missing:
        raise ToolInputError(f"missing fields: {missing}")
    for key, value in data.items():
        kind = props[key]["type"]
        if kind == "string" and not isinstance(value, str):
            raise ToolInputError(f"{key} must be a string")
        if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ToolInputError(f"{key} must be a number")
        if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise ToolInputError(f"{key} must be an integer")
        if "enum" in props[key] and value not in props[key]["enum"]:
            raise ToolInputError(f"{key} must be one of {props[key]['enum']}")
    return data


SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS}


def monthly_payment(amount: float, annual_rate_percent: float, months: int) -> float:
    r = annual_rate_percent / 100 / 12
    if r == 0:
        return amount / months
    return amount * r / (1 - (1 + r) ** -months)


def run_tool(name: str, data: dict, context: dict) -> tuple[str, bool]:
    """Run a tool. Returns (result text for Claude, is_error).

    `context` carries per-conversation facts the model does not supply:
    language, source, and how many leads were already sent.
    """
    if name not in SCHEMAS:
        return json.dumps({"error": f"unknown tool {name}"}), True
    try:
        data = _check(data, SCHEMAS[name])
    except ToolInputError as e:
        return json.dumps({"INVALID_INPUT": str(e), "received": data}, ensure_ascii=False, default=str), True

    if name == "estimate_monthly_payment":
        amount, rate, months = data["loan_amount"], data["annual_rate_percent"], data["term_months"]
        if amount <= 0 or months <= 0 or not 0 <= rate <= 100:
            return json.dumps({"error": "amount and term must be positive, rate between 0 and 100"}), True
        payment = monthly_payment(amount, rate, months)
        return json.dumps({
            "monthly_payment": round(payment, 2),
            "total_interest": round(payment * months - amount, 2),
            "annual_rate_percent": rate,
            "term_months": months,
            "note": "Estimate only; the loan officer confirms the actual rate and terms.",
        }), False

    # send_loan_lead_to_telegram
    if data["loan_amount"] <= 0 or data["term_months"] <= 0 or data["monthly_income"] < 0:
        return json.dumps({"error": "loan_amount and term_months must be positive"}), True
    if context.get("leads_sent", 0) >= MAX_LEADS_PER_CONVERSATION:
        return json.dumps({"error": "lead limit reached for this conversation; ask the customer to call the bank"}), True
    lead = {**data, "language": context.get("language") or "-", "source": context.get("source", "-")}
    try:
        telegram_bot.send_message(telegram_bot.format_lead(lead))
    except telegram_bot.TelegramError as e:
        return json.dumps({"sent": False, "error": str(e)}), True
    context["leads_sent"] = context.get("leads_sent", 0) + 1
    return json.dumps({"sent": True}), False
