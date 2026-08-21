# Backend - Shivalik

A Django-based backend application providing REST APIs.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/swciitg/backend-shivalik.git
cd backend-shivalik
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

### 3. Activate the virtual environment

**Windows**

```bash
venv\Scripts\activate
```

**Linux / macOS**

```bash
source venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure environment variables

Create a `.env` file using `.env.example` and configure the required environment variables.

PostgreSQL is required. Set `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_HOST`, and `POSTGRES_PORT` in `.env` before running migrations.

### 6. Apply migrations

```bash
python manage.py migrate
```

### 7. Start the development server

```bash
python manage.py runserver
```

The backend will be available at:

```
http://127.0.0.1:8000/
```

---

## Project Structure

```text
backend-shivalik/
├── api/
├── config/
├── manage.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## Useful Commands

### Run the development server

```bash
python manage.py runserver
```

### Create migrations

```bash
python manage.py makemigrations
```

### Apply migrations

```bash
python manage.py migrate
```

### Create a superuser

```bash
python manage.py createsuperuser
```
