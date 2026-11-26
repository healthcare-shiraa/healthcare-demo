# دليل نشر وإدارة نسخة العرض (demo)

> نسخة العرض تستخدم **قواعد توضيحية غير معتمدة سريريًا** و**بيانات اصطناعية فقط**، ولا تُستخدم لاتخاذ أي قرار علاجي.
> قواعد الاختبار (`fixtures/`) لا تُحمَّل في نسخة العرض أبدًا، والنظام يرفضها هناك.

## المكونات
| المكون | الخدمة | ملاحظات |
|---|---|---|
| الكود | GitHub | لا أسرار في المستودع (`.streamlit/secrets.toml` مستبعد) |
| قاعدة البيانات الدائمة | Neon (PostgreSQL) | حسابان: المالك (للإدارة فقط) و `hc_app` (للتطبيق، صلاحيات محدودة) |
| التطبيق | Streamlit Community Cloud | يقرأ الأسرار من App settings > Secrets |
| الإدارة | GitHub Actions (`demo-admin`) | تشغيل يدوي؛ الأسرار من GitHub Secrets |

## أين توضع الأسرار
| السر | GitHub Secrets (للإدارة) | Streamlit Secrets (للتطبيق) |
|---|:-:|:-:|
| `HC_DEMO_ADMIN_DATABASE_URL` (عنوان حساب المالك من Neon) | ✅ | ❌ أبدًا |
| `HC_DEMO_DATABASE_URL` (عنوان `hc_app`) | ✅ | ✅ |
| `HC_DEMO_APP_ROLE_PASSWORD` | ✅ | ❌ (موجود داخل العنوان السابق) |
| `HC_DEMO_AUDIT_HMAC_KEY` | ✅ | ✅ |
| `HC_DEMO_PW_REGISTRATION` / `_DOCTOR` / `_PHARMACIST` / `_NURSE` | ✅ | ❌ |
| `HC_ANCHOR_KEY` (البصمة المرجعية) | ❌ | ❌ — مع المنفّذ فقط |

قيم Streamlit غير السرية: `HC_ENV = "demo"`, `HC_DISPLAY_TZ = "Asia/Aden"`, `HC_DEMO_ALLOW_ILLUSTRATIVE_RULES = "true"`.

## خطوات النشر الأولى
1. **Neon:** أنشئ مشروعًا `healthcare-demo`. انسخ عنوان الاتصال لحساب المالك ← سر GitHub `HC_DEMO_ADMIN_DATABASE_URL`.
2. **عنوان التطبيق:** هو عنوان المالك نفسه بعد استبدال اسم المستخدم وكلمة السر بـ `hc_app` وكلمة سره ← `HC_DEMO_DATABASE_URL`.
3. **GitHub > Settings > Secrets and variables > Actions:** أضف الأسرار في الجدول أعلاه.
4. **GitHub > Actions > demo-admin > Run workflow** بالترتيب:
   `init-database` ← `load-illustrative-rules` ← `create-demo-accounts` ← `verify-audit`.
5. **Streamlit Community Cloud > Create app:** المستودع، الفرع `main`، الملف `app.py`، Python 3.12،
   والصق في Advanced settings > Secrets القيم المسموحة في الجدول.
6. افتح الرابط وجرّب الأدوار الأربعة.

## إدارة لاحقة
- **تحديث الموقع:** أي دفع إلى الفرع `main` يعيد Streamlit نشره تلقائيًا.
- **تغيير المخطط:** `init-database` آمن للتكرار (ينشئ الجداول الناقصة فقط) لكنه لا يرحّل أعمدة جديدة في جداول موجودة؛ أي تغيير كهذا يحتاج خطة ترحيل.
- **أمان سير العمل:** المدخلات (`operator`، `username`) لا تُدرج داخل الأوامر أبدًا؛ تُمرَّر كمتغيرات بيئة،
  وتُفحص بنمط صارم في الخطوة الأولى، وتُستعمل بين علامتي تنصيص. حساب التطبيق يُنشأ بـ `scripts/create_app_role.py`
  بجملة SQL مبنية بأدوات psycopg الآمنة، بلا صلاحيات إدارية.
- **ثوابت الاختبار ممنوعة في العرض:** كلمات السر والمفاتيح الثابتة الموجودة في `tests/` (وقيمة المثال في
  `secrets.toml.example`) يرفضها النظام في بيئة demo: كمفتاح سجل، أو مفتاح بصمة، أو كلمة سر حساب، أو كلمة سر `hc_app`.
  القائمة في `hc/known_test_secrets.py` (بصمات SHA-256 فقط)، واختبار K6 يتحقق أن كل ثابت سري جديد في الاختبارات مدرج فيها.
- **إيقاف حساب:** `demo-admin` > `deactivate-user` مع اسم المستخدم. لا يُحذف أي حساب.
- **التحقق من السجل:** `demo-admin` > `verify-audit`. تصدير البصمة المرجعية يتم من جهاز المنفّذ بـ `scripts/verify_audit.py export-anchor` مع `HC_ANCHOR_KEY`، وتُحفظ خارج المستودع والاستضافة.
- **السكون:** تطبيقات Streamlit المجانية تنام بعد فترة بلا زيارات؛ افتح الرابط قبل العرض بدقائق.
- **القواعد الحقيقية لاحقًا:** بعد المراجعة السريرية تُحمَّل بـ `scripts/load_ruleset.py` (نوع `clinical`)، ويُزال `HC_DEMO_ALLOW_ILLUSTRATIVE_RULES`.
