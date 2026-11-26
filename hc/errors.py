"""أنواع الأخطاء في النظام ورسائلها العربية.

DomainError: خطأ متوقع (صلاحية، تحقق، تعارض). يُرفض فيه الطلب ولا يُحفظ شيء،
ويُسجَّل الرفض في سجل التدقيق بمعاملة مستقلة.
"""


class DomainError(Exception):
    outcome = "rejected"
    code = "rejected"

    def __init__(self, message: str, *, code: str | None = None,
                 entity_type: str | None = None, entity_id: str | None = None,
                 details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.details = details or {}
        # تُضبط بعد محاولة تسجيل الرفض: هل حُفظ قيد الرفض في قاعدة البيانات فعلًا؟
        self.audit_persisted: bool | None = None


class PermissionDenied(DomainError):
    outcome = "denied"
    code = "permission_denied"


class AuthenticationFailed(DomainError):
    outcome = "denied"
    code = "authentication_failed"


class ValidationFailed(DomainError):
    outcome = "validation_error"
    code = "validation_error"


class NotFound(DomainError):
    outcome = "validation_error"
    code = "not_found"


class Conflict(DomainError):
    outcome = "conflict"
    code = "conflict"


class Busy(DomainError):
    outcome = "busy"
    code = "busy"


class OperationFailed(Exception):
    """خطأ غير متوقع. العملية لم تُحفظ.

    audit_persisted: هل حُفظ قيد الخطأ في قاعدة البيانات؟ إذا كانت False فقد
    كُتب الخطأ في سجل التشغيل الخارجي فقط، ولا يجوز ادعاء غير ذلك.
    """

    def __init__(self, *, audit_persisted: bool, connection_failure: bool):
        self.audit_persisted = audit_persisted
        self.connection_failure = connection_failure
        if connection_failure:
            msg = "تعذر الاتصال بقاعدة البيانات. لم يُحفظ أي شيء."
        else:
            msg = "حدث خطأ غير متوقع. لم يُحفظ أي شيء."
        if audit_persisted:
            msg += " سُجّل الخطأ في سجل التدقيق."
        else:
            msg += " تعذر تسجيل الخطأ في قاعدة البيانات، وكُتب في سجل التشغيل الخارجي."
        super().__init__(msg)
        self.message = msg


class ConfigError(Exception):
    pass


class EnvironmentMismatch(Exception):
    pass
