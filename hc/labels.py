"""التسميات العربية لحالات النظام (مكان واحد للنصوص)."""

RX_STATUS = {
    "awaiting_pharmacist": "بانتظار الصيدلي",
    "approved": "معتمدة",
    "returned": "مُعادة للطبيب",
    "stopped": "موقوفة",
    "ended": "منتهية",
}
DOSE_STATUS = {
    "upcoming": "قادمة",
    "due": "مستحقة الآن",
    "missed": "فائتة غير موثقة",
    "given": "أُعطيت",
    "not_given": "لم تُعطَ",
    "cancelled": "ملغاة بالإيقاف",
    "unknown": "تعذّر الحساب (إعداد ناقص)",
}
TIMING = {"on_time": "في الموعد", "early": "مبكرة", "late": "متأخرة"}
SEVERITY = {"critical": "حرج", "non_critical": "غير حرج"}
RULE_TYPE = {"allergy": "حساسية", "interaction": "تداخل دوائي"}
RESOLUTION_POLICY = {"return_only": "إعادة إلزامية للطبيب", "conditional": "تسوية بشروط"}
EXISTING_RX_POLICY = {"block_until_resolved": "منع جرعات الوصفة القائمة حتى التسوية",
                      "warn_only": "تحذير دون منع"}
REVIEW_DECISION = {"approved": "اعتماد", "returned": "إعادة للطبيب"}
REFERRAL_ACTION = {"stopped": "أوقفتُ الوصفة", "new_prescription": "أنشأتُ وصفة جديدة",
                   "no_action": "لا إجراء"}
