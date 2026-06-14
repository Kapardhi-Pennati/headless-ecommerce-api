# Headless E-Commerce REST API Template

A production-grade, secure, and modular headless REST API backend for e-commerce platforms. Built with Django 5, Django REST Framework, and Django SimpleJWT. Designed specifically for swift frontend pairing using AI coding assistants.

## 🚀 Key Features

* **Headless Architecture:** Zero HTML views or page templates. Communicates entirely via JSON REST endpoints.
* **Auto-generated OpenAPI 3 Schema:** Integrated with `drf-spectacular`. Interactive documentation is served via Swagger UI (`/api/schema/swagger-ui/`) and ReDoc (`/api/schema/redoc/`).
* **Flexible Payments:** Configurable Payment Gateway factory featuring Razorpay and Cash on Delivery (COD) adapters, powered by a database-backed dynamic configuration settings model.
* **Robust Security Suite:**
  - Argon2 password hashing (OWASP recommended)
  - JWT Authentication stored inside HttpOnly, Secure, SameSite cookies
  - Strict Content Security Policy (CSP) and security headers
  - Per-user and per-IP atomic rate limiting (Redis-backed)
  - Lockout protection after consecutive failed logins
  - Atomic stock reservations (prevents race-condition overselling)
  - Email OTP checkouts to prevent fake orders

---

## 🛠️ Local Development Setup

### 1. Install Dependencies
Ensure you are running Python 3.10+ and install all required packages inside a virtual environment:
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configuration Settings
Copy the `.env.example` file to `.env` and fill out the configurations:
```env
DEBUG=True
SECRET_KEY=your-local-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1
# Keep blank to default to SQLite locally
DB_NAME=
```

### 3. Run Migrations & Seed Catalog
```bash
python manage.py migrate
python manage.py seed_data
```

### 4. Run Development Server
```bash
python manage.py runserver
```

* Swagger UI: [http://127.0.0.1:8000/api/schema/swagger-ui/](http://127.0.0.1:8000/api/schema/swagger-ui/)
* ReDoc: [http://127.0.0.1:8000/api/schema/redoc/](http://127.0.0.1:8000/api/schema/redoc/)

---

## 🔗 Frontend Integration

A step-by-step wiring guide, along with sample Razorpay integration code and copy-paste prompt templates for your AI code generators, is available in the root file:
📄 [FRONTEND_INTEGRATION_GUIDE.txt](file:///FRONTEND_INTEGRATION_GUIDE.txt)

---

## 🧪 Testing

To run the payment and system integrity tests:
```bash
$env:DB_ENGINE="django.db.backends.sqlite3"; $env:DB_NAME=":memory:"; python manage.py test payments
```
