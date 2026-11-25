# 🎪 סוכן האינסטגרם של קרקס בראבו

סוכן AI שמנהל את עמוד האינסטגרם של קרקס בראבו – לבד, כל יום:

| מה | מתי | איך |
|---|---|---|
| **מתכנן פוסטים** לשבוע קדימה (טקסט, האשטגים, בחירת תמונות) | כל יום ראשון בבוקר | Claude מסתכל על התמונות בתיקיית `media/` וכותב פוסט לכל יום ב-`content/queue.yaml` |
| **מפרסם פוסט** לאינסטגרם | כל יום בשעה שנקבעה (ברירת מחדל 18:00) | Instagram API |
| **עונה ללקוחות** בתגובות (ובהודעות פרטיות – אופציונלי) | כל 30 דקות | Claude עונה לפי `brand/brand.md` |
| **מעביר אליכם** תלונות / החזרים / פניות עסקיות | מיד | נפתח Issue בגיטהאב (מגיע אליכם במייל) |
| **מסתיר ספאם** | מיד | |

הכל רץ בחינם על **GitHub Actions** – אין שרת.

---

## 🚀 הפעלה (פעם אחת, ~20 דקות)

### 1. חשבון אינסטגרם מקצועי
האינסטגרם של הקרקס צריך להיות **Business** או **Creator** (בהגדרות האינסטגרם ← סוג חשבון).

### 2. אפליקציה ב-Meta וטוקן
1. נכנסים ל-https://developers.facebook.com/apps ← **Create App** ← סוג **Business**.
2. מוסיפים את המוצר **Instagram** ← **API setup with Instagram login**.
3. ב-"Generate access tokens" מוסיפים את חשבון האינסטגרם של הקרקס ולוחצים **Generate token**.
   הרשאות נדרשות: `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_comments`
   (ולהודעות פרטיות גם `instagram_business_manage_messages`).
4. מעתיקים את **הטוקן** ואת **Instagram User ID** (מופיע ליד שם החשבון).

### 3. מפתח Claude
https://console.anthropic.com ← API Keys ← Create Key.

### 4. שמירת הסודות בגיטהאב
בריפו: **Settings ← Secrets and variables ← Actions ← New repository secret**:

| שם | ערך |
|---|---|
| `IG_USER_ID` | ה-ID של חשבון האינסטגרם |
| `IG_ACCESS_TOKEN` | הטוקן מ-Meta |
| `ANTHROPIC_API_KEY` | המפתח של Claude |
| `GH_PAT` *(מומלץ)* | [Personal access token](https://github.com/settings/personal-access-tokens) עם הרשאת Secrets: write לריפו הזה – כדי שהטוקן של אינסטגרם יתחדש לבד כל שבועיים (בלי זה הוא פג אחרי 60 יום) |

### 5. למלא את המידע על הקרקס
עורכים את **`brand/brand.md`** ומשלימים כל מקום שכתוב **[להשלים]** – שעות, מחירים, קישור לקופה, גילאים.
**הסוכן עונה ללקוחות רק לפי מה שכתוב שם.**

### 6. להעלות תמונות וסרטונים
מעלים לתיקייה **`media/`** (Add file ← Upload files).
- תמונות: **JPG** בלבד · סרטונים (רילס): **MP4**
- שם קובץ באנגלית, בלי רווחים (למשל `juggler-rehearsal.jpg`)
- כמה שיותר – לפחות 7 לשבוע. אם נגמרות תמונות חדשות, הסוכן ישתמש שוב בישנות עם טקסט חדש.

### 7. ניסוי יבש ואז הפעלה
1. **Actions ← תכנון פוסטים לשבוע ← Run workflow** – הסוכן יכתוב פוסטים ל-`content/queue.yaml`. בודקים שזה נראה טוב.
2. **Actions ← מענה לתגובות והודעות ← Run workflow** – בלוג רואים מה הוא *היה* עונה (עדיין לא שולח כלום).
3. כשמרוצים: **Settings ← Secrets and variables ← Actions ← Variables** ← מוסיפים `DRY_RUN` = `false`. מעכשיו הוא חי ✅

---

## ⚙️ הגדרות (Variables)

| משתנה | ברירת מחדל | מה עושה |
|---|---|---|
| `DRY_RUN` | `true` | `false` = מפרסם ועונה באמת |
| `AUTO_APPROVE` | `true` | `false` = פוסטים נכנסים כטיוטה, ומאשרים ידנית ב-`queue.yaml` (`approved: true`) |
| `ENABLE_DMS` | `false` | `true` = עונה גם להודעות פרטיות (דורש הרשאת messages) |
| `WEEKLY_BRIEF` | — | הנחיה קבועה לתכנון, למשל "להתמקד במכירת כרטיסים לחנוכה" |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | המודל שכותב ועונה |

## ✏️ שליטה ידנית
- **לשנות/למחוק פוסט מתוכנן** – עורכים את `content/queue.yaml` (טקסט, שעה, תמונות, `approved`).
- **הנחיה לשבוע ספציפי** – Run workflow על "תכנון פוסטים לשבוע" וכותבים בשדה "הנחיות לשבוע".
- **פניות שהועברו אליכם** – לשונית **Issues**. מומלץ להפעיל Watch על הריפו כדי לקבל אותן במייל.

## 🗂️ מבנה
```
agent/           קוד הסוכן (instagram.py – API, brain.py – Claude, main.py – פקודות)
brand/brand.md   הידע והטון של המותג
content/queue.yaml  תור הפוסטים
media/           תמונות וסרטונים לפרסום
state/           מה כבר נענה (מתעדכן אוטומטית)
.github/workflows/  התזמונים
```

הרצה מקומית: `pip install -r requirements.txt && python -m agent.main check`
