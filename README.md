# Health Care — نموذج أولي

نموذج أولي تعليمي لسير عمل سلامة الأدوية في مستشفى افتراضي. **بيانات اصطناعية فقط. ليس نظامًا سريريًا معتمدًا.**
لا يستخدم التطبيق أي ذكاء اصطناعي في أي قرار؛ الفحص بقواعد ثابتة فقط.

> **القواعد والأدوية الحالية وهمية** (ملف `fixtures/test_ruleset.json`) ومسموحة في بيئة `test` فقط، لاختبار آليات النظام.
> القواعد السبع الحقيقية تُحمَّل بعد مراجعتها سريريًا عبر `scripts/load_ruleset.py`. تحميل ملف لا يعني اعتماده سريريًا.

## ما يعمل
- **موظف التسجيل:** تسجيل المرضى وتعديلهم، وحالة الحساسية (لا توجد / توجد / لم تُسجَّل)، وتاريخ الحساسيات مع سبب إلزامي للإزالة.
- **الطبيب:** إنشاء وصفة (دواء واحد) تُفحص تلقائيًا بالقواعد ثم تُرسل للصيدلي؛ إيقاف وصفاته؛ إغلاق الإحالات.
- **الصيدلي:** مراجعة كل وصفة؛ تسوية التنبيه الحرج بشروط قاعدته (لا يكفي تبرير حر)؛ الإقرار بغير الحرج؛ إعادة الفحص؛ اعتماد أو إعادة.
- **الممرض:** جدول الإعطاء؛ التحقق من رقم المريض والدواء وقرار الصيدلي؛ توثيق «أُعطيت» أو «لم تُعطَ» مع السبب والإحالة؛ منع الإعطاء عند تنبيه حرج غير محلول.
- سجل تدقيق بسلسلة HMAC لكل العمليات، وصلاحيات يفرضها الخادم وقاعدة البيانات.

## تجربة الدورة كاملة محليًا (بيئة اختبار ببيانات وهمية)
```bash
pip install -r requirements-dev.txt
export HC_ENV=test HC_TEST_DATABASE_URL=sqlite:///hc_test.db HC_DISPLAY_TZ=Asia/Aden
export HC_TEST_AUDIT_HMAC_KEY="<مفتاح عشوائي 32 حرفًا أو أكثر>"
python scripts/init_db.py
python scripts/load_test_fixtures.py --with-medication-cycle
# حساب لكل دور (كلمة السر تُطلب بإدخال مخفي؛ لا توجد كلمة سر افتراضية)
python scripts/manage_users.py create --username reg.one --full-name "..." --role registration --operator "<اسمك>"
python scripts/manage_users.py create --username dr.one  --full-name "..." --role doctor       --operator "<اسمك>"
python scripts/manage_users.py create --username ph.one  --full-name "..." --role pharmacist   --operator "<اسمك>"
python scripts/manage_users.py create --username rn.one  --full-name "..." --role nurse        --operator "<اسمك>"
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # ثم عدّلي القيم لتطابق ما سبق (HC_ENV=test …)
streamlit run app.py
```
سيناريو مقترح: سجّلي مريضًا عنده «حساسية-اختبار-أ» ← الطبيب يصف «دواء-اختبار-أ» (يظهر تنبيه حرج وهمي T-R1)
← الصيدلي يستوفي شرطي التسوية ثم يعتمد ← الممرض يتحقق ويوثّق. وللمنع: وصفة «دواء-اختبار-ب» معتمدة ثم وصفة «دواء-اختبار-ج» للمريض نفسه (T-R2).

## الإعدادات التشغيلية (بلا قيم افتراضية)
`scripts/set_policy.py`: `dose_window_minutes`، `late_documentation_max_hours` (رقم أو none)،
`missed_dose_sequence_policy` (strict|warn)، `max_treatment_days`. ما ينقص منها يوقف الوظيفة التي تحتاجه فقط.

## الملفات الرئيسية
| المسار | الغرض |
|---|---|
| `app.py` | الإطار: الدخول، القائمة الجانبية، توجيه الصفحات |
| `hc/ui/` | التصميم (`theme.py`) والمكونات المشتركة وشاشات الأدوار الأربعة |
| `hc/rules.py` | تحميل مجموعة القواعد ومحرك الفحص الثابت |
| `hc/prescriptions.py` · `hc/review.py` · `hc/administration.py` · `hc/doses.py` | دورة الدواء |
| `hc/reference.py` | الأدوية والتكرارات والأسباب والإعدادات |
| `hc/patients.py` · `hc/auth.py` · `hc/audit.py` · `hc/config.py` · `hc/db.py` | المرحلة الأولى |
| `schema/*.sql` | الجداول والمشغّلات لكل محرك (قسم دورة الدواء مولّد من `tools/gen_phase2_schema.py`) |
| `scripts/` | التهيئة، الحسابات، القواعد، الإعدادات، التحقق من السجل، تقرير الاختبارات |
| `fixtures/` | قواعد وإعدادات **وهمية** لبيئة الاختبار |
| `static/fonts/` | خط IBM Plex Sans Arabic (رخصة OFL) |
| `docs/screens/` | لقطات من تشغيل فعلي في المتصفح |

## الاختبارات
```bash
python -m pytest            # SQLite
HC_PG_TEST_SUPERUSER_URL="postgresql+psycopg://postgres@/postgres?host=/tmp&port=5433" python -m pytest
python scripts/make_test_report.py test-results.xml TEST_REPORT.md   # بعد --junitxml=test-results.xml
```
